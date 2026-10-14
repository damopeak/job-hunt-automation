import type { Context, Config } from "@netlify/functions";

const AIRTABLE_BASE_URL = "https://api.airtable.com/v0";

export default async (req: Request, context: Context) => {
  const dashboardPassword = process.env.DASHBOARD_PASSWORD || Netlify.env.get("DASHBOARD_PASSWORD");
  const providedKey = req.headers.get("x-dashboard-key");
  if (dashboardPassword && providedKey !== dashboardPassword) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  }

  const token = process.env.AIRTABLE_TOKEN || Netlify.env.get("AIRTABLE_TOKEN");
  const baseId = process.env.AIRTABLE_BASE_ID || Netlify.env.get("AIRTABLE_BASE_ID");
  const tableName = process.env.AIRTABLE_TABLE_NAME || Netlify.env.get("AIRTABLE_TABLE_NAME") || "Jobs";

  if (!token || !baseId) {
    return new Response(
      JSON.stringify({ error: "Server not configured — missing AIRTABLE_TOKEN or AIRTABLE_BASE_ID" }),
      { status: 500, headers: { "content-type": "application/json", "cache-control": "private, no-store" } }
    );
  }

  let body: any;
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON body" }), {
      status: 400,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  }

  const { recordId, status } = body || {};
  if (!recordId) {
    return new Response(JSON.stringify({ error: "recordId is required" }), {
      status: 400,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  }

  // Default "Not applying" = Status: "Rejected by me" — the same status the
  // user has been setting manually in Airtable directly (e.g. the Postdoctoral
  // Research Fellow / TPP Mandarin Speaker jobs found earlier this session).
  // "I Applied" on the Job Dashboard also calls this endpoint with
  // status: "Applied" (added 06 Aug 2026) so applied-to jobs stop showing
  // under the "Not applied" filter here too — previously "I Applied" only
  // wrote to the separate Google Sheet tracker and never touched this Status
  // field, so the two views disagreed with each other.
  const newStatus = status || "Rejected by me";
  const url = `${AIRTABLE_BASE_URL}/${baseId}/${encodeURIComponent(tableName)}/${encodeURIComponent(recordId)}`;
  try {
    const resp = await fetch(url, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ fields: { "Status": newStatus } }),
    });
    if (!resp.ok) {
      const detail = await resp.text();
      return new Response(JSON.stringify({ error: `Airtable update failed (${resp.status})`, detail }), {
        status: 502,
        headers: { "content-type": "application/json", "cache-control": "private, no-store" },
      });
    }
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: "Failed to reach Airtable", detail: String(err) }), {
      status: 502,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  }
};

export const config: Config = {
  path: "/api/dismiss",
};
