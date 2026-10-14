import type { Context, Config } from "@netlify/functions";
import { createSign } from "node:crypto";

// Google Sheet ID of the application tracker (the long ID in the sheet's URL).
// Resolved per request from GOOGLE_SHEET_ID (see handler below).
let SHEET_ID = "";
const SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets";

function checkAuth(req: Request): Response | null {
  const dashboardPassword = process.env.DASHBOARD_PASSWORD || Netlify.env.get("DASHBOARD_PASSWORD");
  const providedKey = req.headers.get("x-dashboard-key");
  if (dashboardPassword && providedKey !== dashboardPassword) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  }
  return null;
}

function base64url(input: Buffer | string): string {
  const buf = typeof input === "string" ? Buffer.from(input) : input;
  return buf.toString("base64url");
}

async function getAccessToken(): Promise<string> {
  const clientEmail = process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL || Netlify.env.get("GOOGLE_SERVICE_ACCOUNT_EMAIL");
  const rawKey = process.env.GOOGLE_PRIVATE_KEY || Netlify.env.get("GOOGLE_PRIVATE_KEY");
  if (!clientEmail || !rawKey) throw new Error("Missing GOOGLE_SERVICE_ACCOUNT_EMAIL or GOOGLE_PRIVATE_KEY");
  const privateKey = rawKey.replace(/\\n/g, "\n");

  const now = Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const claim = {
    iss: clientEmail,
    scope: "https://www.googleapis.com/auth/spreadsheets",
    aud: "https://oauth2.googleapis.com/token",
    exp: now + 3600,
    iat: now,
  };
  const unsigned = `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(claim))}`;
  const signer = createSign("RSA-SHA256");
  signer.update(unsigned);
  const signature = signer.sign(privateKey, "base64url");
  const jwt = `${unsigned}.${signature}`;

  const resp = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(`Google token exchange failed: ${JSON.stringify(data)}`);
  return data.access_token;
}

function json(body: unknown, status = 200): Response {
  // no-store — this endpoint is behind a password check; a cacheable
  // response would let Netlify's edge CDN serve it regardless of auth header.
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "private, no-store" },
  });
}

// Google Sheets' values:append endpoint "detects a table" within the given
// range and appends after it — but when earlier `clear` calls (Undo, cleanup
// scripts) leave empty gap rows in the middle of the range, that detection
// gets confused and writes land on the wrong row with columns interleaved
// between two different appends (found 06 Aug 2026 — "Verisk Analytics"'s
// company/role ended up smeared into another row's Notes column). Avoid the
// heuristic entirely: read the range ourselves, compute the exact next row
// number (including any gaps, so we never land inside one), and write there
// with a plain values.update instead of :append.
async function appendRowExplicit(authHeader: Record<string, string>, row: string[], existingValues?: string[][]): Promise<Response | null> {
  let values = existingValues;
  if (!values) {
    const readResp = await fetch(`${SHEETS_API}/${SHEET_ID}/values/Assignments!A2:E10000`, { headers: authHeader });
    if (!readResp.ok) return json({ error: `Sheets read failed (${readResp.status})`, detail: await readResp.text() }, 502);
    values = (await readResp.json()).values || [];
  }
  const nextRow = values.length + 2;
  const putResp = await fetch(
    `${SHEETS_API}/${SHEET_ID}/values/Assignments!A${nextRow}:E${nextRow}?valueInputOption=USER_ENTERED`,
    {
      method: "PUT",
      headers: { ...authHeader, "content-type": "application/json" },
      body: JSON.stringify({ values: [row] }),
    }
  );
  if (!putResp.ok) return json({ error: `Sheets write failed (${putResp.status})`, detail: await putResp.text() }, 502);
  return null;
}

function todayDDMMYYYY(): string {
  const d = new Date();
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}-${mm}-${d.getFullYear()}`;
}

export default async (req: Request, context: Context) => {
  const authFail = checkAuth(req);
  if (authFail) return authFail;
  SHEET_ID = process.env.GOOGLE_SHEET_ID || Netlify.env.get("GOOGLE_SHEET_ID") || "";
  if (!SHEET_ID) return json({ error: "Server not configured — missing GOOGLE_SHEET_ID" }, 500);

  let accessToken: string;
  try {
    accessToken = await getAccessToken();
  } catch (err) {
    return json({ error: "Google auth failed", detail: String(err) }, 502);
  }
  const authHeader = { Authorization: `Bearer ${accessToken}` };

  if (req.method === "GET") {
    try {
      const resp = await fetch(`${SHEETS_API}/${SHEET_ID}/values/Assignments!A2:E10000`, { headers: authHeader });
      if (!resp.ok) return json({ error: `Sheets read failed (${resp.status})`, detail: await resp.text() }, 502);
      const data = await resp.json();
      const rows = (data.values || [])
        .map((r: string[], i: number) => ({
          rowIndex: i + 2,
          company: r[0] || "",
          role: r[1] || "",
          status: r[2] || "",
          deadline: r[3] || "",
          notes: r[4] || "",
        }))
        .filter((r: any) => r.company);
      return json({ rows });
    } catch (err) {
      return json({ error: "Failed to reach Sheets API", detail: String(err) }, 502);
    }
  }

  if (req.method === "POST") {
    let body: any;
    try {
      body = await req.json();
    } catch {
      return json({ error: "Invalid JSON body" }, 400);
    }

    const { rowIndex, company, role, status, notes, isNewJob, link, upsert, logOnly, change, remove } = body || {};

    try {
      if (remove) {
        // Undo for the "I Applied" button — clears the row (rather than a
        // true delete, which would need a batchUpdate deleteDimension call
        // referencing the sheet's numeric gridId and would shift every row
        // below it; clearing the values is simpler and leaves no visible gap
        // once the QUERY-formula stage tabs re-filter).
        if (!company) return json({ error: "company is required to remove a row" }, 400);
        const readResp = await fetch(`${SHEETS_API}/${SHEET_ID}/values/Assignments!A2:E10000`, { headers: authHeader });
        if (!readResp.ok) return json({ error: `Sheets read failed (${readResp.status})`, detail: await readResp.text() }, 502);
        const readData = await readResp.json();
        const values: string[][] = readData.values || [];
        const normCompany = company.trim().toLowerCase();
        const normRole = (role || "").trim().toLowerCase();
        let foundRow = -1;
        for (let i = 0; i < values.length; i++) {
          const rowCompany = (values[i][0] || "").trim().toLowerCase();
          const rowRole = (values[i][1] || "").trim().toLowerCase();
          if (rowCompany === normCompany && (!normRole || !rowRole || rowRole === normRole)) {
            foundRow = i + 2;
            break;
          }
        }
        if (foundRow < 0) return json({ error: "No matching row found to remove" }, 404);

        const clearResp = await fetch(`${SHEETS_API}/${SHEET_ID}/values/Assignments!A${foundRow}:E${foundRow}:clear`, {
          method: "POST",
          headers: authHeader,
        });
        if (!clearResp.ok) return json({ error: `Sheets clear failed (${clearResp.status})`, detail: await clearResp.text() }, 502);

        await fetch(`${SHEETS_API}/${SHEET_ID}/values/'Daily Changes Log'!A:D:append?valueInputOption=USER_ENTERED`, {
          method: "POST",
          headers: { ...authHeader, "content-type": "application/json" },
          body: JSON.stringify({ values: [[todayDDMMYYYY(), company, role || "", "Removed - added by mistake"]] }),
        });

        return json({ ok: true, removedRow: foundRow });
      }

      if (logOnly) {
        // Heartbeat entry — e.g. "No application status changes or new jobs
        // detected." — so a quiet day is visibly distinguishable from the
        // routine silently failing to run at all. Doesn't touch Assignments.
        await fetch(`${SHEETS_API}/${SHEET_ID}/values/'Daily Changes Log'!A:D:append?valueInputOption=USER_ENTERED`, {
          method: "POST",
          headers: { ...authHeader, "content-type": "application/json" },
          body: JSON.stringify({ values: [[todayDDMMYYYY(), company || "", role || "", change || "No changes detected."]] }),
        });
        return json({ ok: true });
      }

      if (upsert) {
        // Used by the daily email-reading routine: find an existing row by
        // company (+ role if given), update it if found, otherwise append a
        // new one. Mirrors the old Apps Script's updateStatus/addJob dedupe
        // behaviour in one call, since the routine only knows company/role.
        if (!company) return json({ error: "company is required for upsert" }, 400);
        const readResp = await fetch(`${SHEETS_API}/${SHEET_ID}/values/Assignments!A2:E10000`, { headers: authHeader });
        if (!readResp.ok) return json({ error: `Sheets read failed (${readResp.status})`, detail: await readResp.text() }, 502);
        const readData = await readResp.json();
        const values: string[][] = readData.values || [];
        const normCompany = company.trim().toLowerCase();
        const normRole = (role || "").trim().toLowerCase();
        let foundRow = -1;
        for (let i = 0; i < values.length; i++) {
          const rowCompany = (values[i][0] || "").trim().toLowerCase();
          const rowRole = (values[i][1] || "").trim().toLowerCase();
          if (rowCompany === normCompany && (!normRole || !rowRole || rowRole === normRole)) {
            foundRow = i + 2;
            break;
          }
        }

        if (foundRow > 0) {
          const data: any[] = [];
          if (status !== undefined) data.push({ range: `Assignments!C${foundRow}`, values: [[status]] });
          if (notes !== undefined) data.push({ range: `Assignments!E${foundRow}`, values: [[notes]] });
          if (data.length) {
            const updResp = await fetch(`${SHEETS_API}/${SHEET_ID}/values:batchUpdate`, {
              method: "POST",
              headers: { ...authHeader, "content-type": "application/json" },
              body: JSON.stringify({ valueInputOption: "USER_ENTERED", data }),
            });
            if (!updResp.ok) return json({ error: `Sheets update failed (${updResp.status})`, detail: await updResp.text() }, 502);
          }
        } else {
          const errResp = await appendRowExplicit(
            authHeader,
            [company, role || "", status || "Applied, waiting for response", "", notes || (link ? `Link: ${link}` : "")],
            values
          );
          if (errResp) return errResp;
        }

        const changeText = foundRow > 0 ? status : "New application added - " + (status || "Applied, waiting for response");
        await fetch(`${SHEETS_API}/${SHEET_ID}/values/'Daily Changes Log'!A:D:append?valueInputOption=USER_ENTERED`, {
          method: "POST",
          headers: { ...authHeader, "content-type": "application/json" },
          body: JSON.stringify({ values: [[todayDDMMYYYY(), company, role || "", changeText]] }),
        });

        return json({ ok: true, matched: foundRow > 0, rowIndex: foundRow > 0 ? foundRow : undefined });
      }

      if (isNewJob) {
        const errResp = await appendRowExplicit(
          authHeader,
          [company, role, status || "Applied, waiting for response", "", notes || (link ? `Link: ${link}` : "")]
        );
        if (errResp) return errResp;
      } else {
        if (!rowIndex) return json({ error: "rowIndex is required when isNewJob/upsert is not set" }, 400);
        const data: any[] = [];
        if (status !== undefined) data.push({ range: `Assignments!C${rowIndex}`, values: [[status]] });
        if (notes !== undefined) data.push({ range: `Assignments!E${rowIndex}`, values: [[notes]] });
        if (data.length) {
          const updResp = await fetch(`${SHEETS_API}/${SHEET_ID}/values:batchUpdate`, {
            method: "POST",
            headers: { ...authHeader, "content-type": "application/json" },
            body: JSON.stringify({ valueInputOption: "USER_ENTERED", data }),
          });
          if (!updResp.ok) return json({ error: `Sheets update failed (${updResp.status})`, detail: await updResp.text() }, 502);
        }
      }

      const changeText = isNewJob ? "New application added - Applied, waiting for response" : status;
      await fetch(`${SHEETS_API}/${SHEET_ID}/values/'Daily Changes Log'!A:D:append?valueInputOption=USER_ENTERED`, {
        method: "POST",
        headers: { ...authHeader, "content-type": "application/json" },
        body: JSON.stringify({ values: [[todayDDMMYYYY(), company, role, changeText]] }),
      });

      return json({ ok: true });
    } catch (err) {
      return json({ error: "Failed to write to Sheets API", detail: String(err) }, 502);
    }
  }

  return json({ error: "Method not allowed" }, 405);
};

export const config: Config = {
  path: "/api/tracker",
};
