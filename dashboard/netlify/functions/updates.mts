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
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "private, no-store" },
  });
}

// Sheet stores dates as DD-MM-YYYY strings — convert to ISO for reliable sorting.
function toIso(ddmmyyyy: string): string {
  const m = /^(\d{2})-(\d{2})-(\d{4})$/.exec((ddmmyyyy || "").trim());
  if (!m) return "";
  const [, dd, mm, yyyy] = m;
  return `${yyyy}-${mm}-${dd}`;
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

  try {
    const resp = await fetch(`${SHEETS_API}/${SHEET_ID}/values/'Daily Changes Log'!A2:D10000`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!resp.ok) return json({ error: `Sheets read failed (${resp.status})`, detail: await resp.text() }, 502);
    const data = await resp.json();
    const entries = (data.values || [])
      .map((r: string[]) => ({
        date: r[0] || "",
        isoDate: toIso(r[0] || ""),
        company: r[1] || "",
        role: r[2] || "",
        change: r[3] || "",
      }))
      .filter((e: any) => e.date && e.change)
      .sort((a: any, b: any) => (a.isoDate < b.isoDate ? 1 : a.isoDate > b.isoDate ? -1 : 0));
    return json({ entries });
  } catch (err) {
    return json({ error: "Failed to reach Sheets API", detail: String(err) }, 502);
  }
};

export const config: Config = {
  path: "/api/updates",
};
