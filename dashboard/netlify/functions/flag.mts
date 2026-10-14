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

  const { recordId, category, note } = body || {};
  if (!recordId || !category) {
    return new Response(JSON.stringify({ error: "recordId and category are required" }), {
      status: 400,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  }

  const url = `${AIRTABLE_BASE_URL}/${baseId}/${encodeURIComponent(tableName)}/${encodeURIComponent(recordId)}`;
  try {
    const resp = await fetch(url, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        fields: {
          "Flag Category": category === "__clear__" ? null : category,
          "Flag Note": category === "__clear__" ? null : (note || ""),
        },
      }),
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
  path: "/api/flag",
};
