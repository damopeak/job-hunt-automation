import type { Context, Config } from "@netlify/functions";

const AIRTABLE_BASE_URL = "https://api.airtable.com/v0";

export default async (req: Request, context: Context) => {
  // Netlify's built-in password-protection API is currently rejecting every
  // request (422) regardless of plan or parameters — app-level gate instead so
  // the actual job data isn't served to an unauthenticated request.
  const dashboardPassword = process.env.DASHBOARD_PASSWORD || Netlify.env.get("DASHBOARD_PASSWORD");
  const providedKey = req.headers.get("x-dashboard-key");
  if (dashboardPassword && providedKey !== dashboardPassword) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
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

  const url = `${AIRTABLE_BASE_URL}/${baseId}/${encodeURIComponent(tableName)}`;
  const headers = { Authorization: `Bearer ${token}` };

  const records: any[] = [];
  let offset: string | undefined;

  try {
    do {
      const params = new URLSearchParams({ pageSize: "100" });
      if (offset) params.set("offset", offset);
      const resp = await fetch(`${url}?${params.toString()}`, { headers });
      if (!resp.ok) {
        const detail = await resp.text();
        return new Response(
          JSON.stringify({ error: `Airtable request failed (${resp.status})`, detail }),
          { status: 502, headers: { "content-type": "application/json", "cache-control": "private, no-store" } }
        );
      }
      const data = await resp.json();
      records.push(...(data.records || []));
      offset = data.offset;
    } while (offset);
  } catch (err) {
    return new Response(
      JSON.stringify({ error: "Failed to reach Airtable", detail: String(err) }),
      { status: 502, headers: { "content-type": "application/json", "cache-control": "private, no-store" } }
    );
  }

  const jobs = records.map((r) => {
    const f = r.fields || {};
    return {
      id: r.id,
      company: f["Company"] || "",
      role: f["Job Title"] || "",
      rating: typeof f["Rating"] === "number" ? f["Rating"] : null,
      status: f["Status"] || "",
      source: f["Source"] || "",
      location: f["Location"] || "",
      salary: f["Salary"] || "",
      url: f["URL"] || "",
      dateFound: f["Date Found"] || "",
      datePosted: f["Date Posted"] || "",
      keywords: f["Keywords"] || "",
      notes: f["Rating Notes"] || "",
      flagCategory: f["Flag Category"] || "",
      flagNote: f["Flag Note"] || "",
    };
  });

  return new Response(
    JSON.stringify({ jobs, count: jobs.length, fetchedAt: new Date().toISOString() }),
    {
      status: 200,
      // MUST be private/no-store — this endpoint is behind a password check
      // and "public" caching let Netlify's edge CDN serve a cached response
      // to ANY request to this URL regardless of the x-dashboard-key header,
      // bypassing auth entirely on a cache hit. Found 06 Aug 2026 during a
      // full security pass (wrong password was returning 200).
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    }
  );
};

export const config: Config = {
  path: "/api/jobs",
};
