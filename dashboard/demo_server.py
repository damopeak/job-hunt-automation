"""Job Dashboard - demo mode.

Serves the dashboard pages from this folder at http://127.0.0.1:8798 and answers the same
/api/* routes as the Netlify functions (jobs, tracker, updates, flag, dismiss) with realistic
but entirely FAKE data, generated relative to today's date.

    python demo_server.py

Any password is accepted on the login screen. No Netlify, Airtable or Google account is needed
(standard library only). Changes you make (flag, dismiss, I applied, moving tracker cards) are
kept in memory until the server stops, so the pages behave as they would for real.
"""
import json
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", 8798
ROOT = Path(__file__).parent
LOCK = threading.Lock()

# company, role, location, salary, rating, source, days since found, status, rating notes
JOB_ROWS = [
    ("Northwind Analytics", "Graduate Data Analyst", "London (Hybrid)", "£30,000", 10, "LinkedIn", 0, "Not applied", "Strong match: SQL, Excel and Python all mentioned; graduate level; London hybrid."),
    ("Lakeside Group", "Business Analyst", "Manchester (Hybrid)", "£32,000", 10, "Reed", 0, "Not applied", "Entry-level BA role, stakeholder and data skills match the profile."),
    ("Brightwave Software", "Sales Development Representative", "London", "£28,000 + OTE", 9, "Totaljobs", 0, "Not applied", "SDR with full training; graduate welcome; salary above target."),
    ("Contoso Retail", "Junior Insights Analyst", "Remote (UK)", "£29,500", 9, "Adzuna", 1, "Applied", "Insights team, Excel and dashboards; remote."),
    ("Fabrikam Foods", "Graduate Commercial Analyst", "Leeds (Hybrid)", "£31,000", 9, "Prospects", 1, "Not applied", "Commercial graduate scheme; pricing and promotions analysis."),
    ("Bluebird Payments", "Business Development Representative", "London (Hybrid)", "£30,000 + OTE", 9, "Greenhouse", 1, "Not applied", "BDR in fintech, no prior sales experience required."),
    ("Harbour Logistics", "Operations Analyst", "Birmingham", "£29,000", 9, "Guardian Jobs", 2, "Applied", "Operations reporting, Excel heavy; graduate level."),
    ("Tailspin Travel", "Graduate Data Analyst", "Bristol (Hybrid)", "£28,500", 9, "Milkround", 2, "Not applied", "Graduate scheme with SQL training; travel sector."),
    ("Woodgrove Bank", "Graduate Analyst Programme", "London", "£34,000", 8, "Trackr", 2, "Not applied", "Bank graduate programme; rotation includes data and risk."),
    ("Litware Media", "Marketing Data Analyst", "London (Hybrid)", "£27,000", 8, "Jobsite", 3, "Not applied", "Marketing analytics; some campaign experience preferred, not essential."),
    ("Adventure Works", "Junior Business Analyst", "Reading", "£28,000", 8, "CWJobs", 3, "Not applied", "Junior BA; requirements gathering and process mapping."),
    ("Proseware Health", "Data Analyst (Graduate)", "Nottingham", "£26,500", 8, "Gradcracker", 4, "Not applied", "Healthcare data, graduate entry, Power BI desirable."),
    ("Margie's Travel", "Sales Development Representative", "Remote (UK)", "£25,000 + OTE", 7, "Indeed", 4, "Not applied", "SDR, remote; salary slightly below target."),
    ("Alpine Ski House", "Revenue Analyst", "Edinburgh", "£29,000", 8, "S1Jobs", 5, "Not applied", "Revenue and pricing analysis; graduate welcome."),
    ("Coho Winery", "Graduate Buyer / Analyst", "London", "£27,500", 7, "Fish4Jobs", 5, "Not applied", "Buying team analyst; retail interest a plus."),
    ("Wide World Importers", "Supply Chain Analyst", "Manchester", "£30,500", 8, "Adzuna", 6, "Not applied", "Supply chain data and forecasting; Excel and SQL."),
    ("Fourth Coffee", "Commercial Insight Analyst", "Leeds", "£28,000", 7, "Reed", 6, "Not applied", "Category insight role; FMCG data experience preferred."),
    ("Graphic Design Institute", "Business Operations Associate", "London (Hybrid)", "£27,000", 7, "Jora", 7, "Not applied", "Ops associate; broad role with reporting tasks."),
    ("Blue Yonder Airlines", "Graduate Pricing Analyst", "London", "£32,500", 9, "TargetJobs", 7, "Rejected by me", "Pricing graduate scheme; strong fit but relocation needed."),
    ("Trey Research", "Research Analyst", "Cambridge", "£27,000", 7, "GRB", 8, "Not applied", "Market research analyst; graduate entry."),
    ("City Power & Light", "Junior Data Analyst", "Glasgow", "£26,000", 7, "S1Jobs", 9, "Not applied", "Junior analyst in energy; on-site."),
    ("The Phone Company", "Account Development Representative", "Birmingham (Hybrid)", "£26,500 + OTE", 7, "Totaljobs", 10, "Not applied", "Inside sales, graduate level."),
    ("Humongous Insurance", "Graduate Actuarial Analyst", "London", "£35,000", 1, "Prospects", 10, "Not applied", "Excluded: requires a STEM degree and actuarial exams in progress."),
    ("VanArsdel Ltd", "Senior Business Analyst", "London", "£55,000", 1, "LinkedIn", 11, "Not applied", "Excluded: 5+ years' experience required."),
    ("Relecloud", "Graduate Customer Success Analyst", "Remote (UK)", "£27,500", 8, "Greenhouse", 12, "Not applied", "Customer success with data focus; remote."),
]
FLAGS = {7: ("Rating too high", "Asks for previous SDR experience in the essentials."), 12: ("Rating too low", "Remote and well paid, should be 9."),
         17: ("Wrong sector/role", "Mostly admin, not analysis.")}


def jobs_state():
    t = date.today()
    out = []
    for i, (company, role, loc, sal, rating, src, ago, status, notes) in enumerate(JOB_ROWS):
        found = t - timedelta(days=ago)
        flag = FLAGS.get(i, ("", ""))
        out.append({"id": f"recDEMO{i:04d}", "company": company, "role": role, "rating": rating, "status": status, "source": src,
                    "location": loc, "salary": sal, "url": f"https://www.example.com/jobs/demo-{i}", "dateFound": str(found),
                    "datePosted": str(found - timedelta(days=1)), "keywords": "graduate analyst" if "Analyst" in role else "graduate sales",
                    "notes": notes, "flagCategory": flag[0], "flagNote": flag[1]})
    return out


def tracker_state():
    t = date.today()
    rows = [
        ("Northwind Analytics", "Graduate Data Analyst", "Interview", t + timedelta(days=2), "45-min video interview with the analytics lead."),
        ("Lakeside Group", "Business Analyst", "Online Assessment", t + timedelta(days=1), "Numerical and situational judgement tests."),
        ("Brightwave Software", "Graduate SDR", "Assessment Centre", t + timedelta(days=10), "Group exercise and role play."),
        ("Contoso Retail", "Junior Insights Analyst", "Screening Call", None, "Recruiter call went well."),
        ("Harbour Logistics", "Operations Analyst", "Applied, waiting for response", None, ""),
        ("Tailspin Travel", "Graduate Data Analyst", "Applied, waiting for response", None, ""),
        ("Bluebird Payments", "BDR", "Applied, waiting for response", None, "Referred by a friend."),
        ("Fabrikam Foods", "Commercial Analyst", "Waiting for response", None, "Completed video interview last week."),
        ("Adventure Works", "Junior Business Analyst", "Applied, waiting for response", None, ""),
        ("Woodgrove Bank", "Graduate Analyst", "Denied after application", None, ""),
        ("Litware Media", "Marketing Analyst", "Denied after assessment", None, "Feedback: strong numeracy, practise case studies."),
        ("Alpine Ski House", "Revenue Analyst", "Offer", t + timedelta(days=6), "Verbal offer, written offer to follow. Reply by the deadline."),
    ]
    return [{"rowIndex": i + 2, "company": c, "role": r, "status": s, "deadline": d.strftime("%d/%m/%Y") if d else "", "notes": n}
            for i, (c, r, s, d, n) in enumerate(rows)]


def updates_state():
    t = date.today()
    src = [(0, "Northwind Analytics", "Graduate Data Analyst", "Interview booked for Friday"),
           (0, "Harbour Logistics", "Operations Analyst", "Applied"),
           (0, "Contoso Retail", "Junior Insights Analyst", "Moved to Screening Call"),
           (1, "Lakeside Group", "Business Analyst", "Online assessment received"),
           (1, "Tailspin Travel", "Graduate Data Analyst", "Applied"),
           (2, "Woodgrove Bank", "Graduate Analyst", "Denied after application"),
           (2, "Bluebird Payments", "BDR", "Applied"),
           (3, "Alpine Ski House", "Revenue Analyst", "Offer received"),
           (3, "", "", "No changes detected."),
           (4, "Fabrikam Foods", "Commercial Analyst", "Video interview completed, waiting for response"),
           (5, "Litware Media", "Marketing Analyst", "Denied after assessment"),
           (6, "Brightwave Software", "Graduate SDR", "Invited to assessment centre"),
           (7, "Adventure Works", "Junior Business Analyst", "Applied")]
    out = []
    for d, c, r, ch in src:
        day = t - timedelta(days=d)
        out.append({"date": day.strftime("%d-%m-%Y"), "isoDate": str(day), "company": c, "role": r, "change": ch})
    return out


STATE = {"jobs": jobs_state(), "tracker": tracker_state(), "updates": updates_state()}


def log_change(company, role, change):
    day = date.today()
    STATE["updates"].insert(0, {"date": day.strftime("%d-%m-%Y"), "isoDate": str(day), "company": company or "", "role": role or "", "change": change})


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        return self.path.split("?")[0].replace("/.netlify/functions/", "/api/")

    def do_GET(self):
        p = self.route()
        if not p.startswith("/api/"):
            return super().do_GET()
        # Demo mode: any password is accepted (the real functions compare x-dashboard-key with DASHBOARD_PASSWORD)
        with LOCK:
            if p == "/api/jobs":
                jobs = list(STATE["jobs"])
                return self.send_json({"jobs": jobs, "count": len(jobs), "fetchedAt": datetime.now(timezone.utc).isoformat()})
            if p == "/api/tracker":
                return self.send_json({"rows": STATE["tracker"]})
            if p == "/api/updates":
                return self.send_json({"entries": STATE["updates"]})
        if p in ("/api/flag", "/api/dismiss"):
            return self.send_json({"error": "Method not allowed"}, 405)
        return self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        p = self.route()
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
        except ValueError:
            return self.send_json({"error": "Invalid JSON body"}, 400)
        with LOCK:
            if p == "/api/flag":
                job = next((j for j in STATE["jobs"] if j["id"] == body.get("recordId")), None)
                if not job or not body.get("category"):
                    return self.send_json({"error": "recordId and category are required"}, 400)
                clear = body["category"] == "__clear__"
                job["flagCategory"], job["flagNote"] = ("", "") if clear else (body["category"], body.get("note", ""))
                return self.send_json({"ok": True})
            if p == "/api/dismiss":
                job = next((j for j in STATE["jobs"] if j["id"] == body.get("recordId")), None)
                if not job:
                    return self.send_json({"error": "recordId is required"}, 400)
                job["status"] = body.get("status") or "Rejected by me"
                return self.send_json({"ok": True})
            if p == "/api/tracker":
                return self.send_json(self.tracker_post(body))
            if p == "/api/updates":
                return self.send_json({"ok": True})
        return self.send_json({"error": "Not found"}, 404)

    def tracker_post(self, b):
        rows = STATE["tracker"]
        company, role = (b.get("company") or "").strip(), (b.get("role") or "").strip()
        if b.get("remove"):
            match = next((r for r in rows if r["company"].lower() == company.lower() and (not role or r["role"].lower() == role.lower())), None)
            if match:
                rows.remove(match)
                log_change(company, role, "Removed - added by mistake")
            return {"ok": True}
        if b.get("logOnly"):
            log_change(company, role, b.get("change") or "No changes detected.")
            return {"ok": True}
        if b.get("rowIndex"):
            row = next((r for r in rows if r["rowIndex"] == int(b["rowIndex"])), None)
            if row:
                old = row["status"]
                for k in ("status", "notes"):
                    if b.get(k) is not None:
                        row[k] = b[k]
                log_change(row["company"], row["role"], f"{old} → {row['status']}")
            return {"ok": True}
        match = next((r for r in rows if r["company"].lower() == company.lower() and r["role"].lower() == role.lower()), None) if b.get("upsert") else None
        if match:
            match["status"] = b.get("status") or match["status"]
            log_change(company, role, match["status"])
            return {"ok": True, "updated": True}
        rows.append({"rowIndex": max([r["rowIndex"] for r in rows] or [1]) + 1, "company": company, "role": role,
                     "status": b.get("status") or "Applied, waiting for response", "deadline": "", "notes": b.get("notes") or ""})
        log_change(company, role, "Applied")
        return {"ok": True, "appended": True}

    def end_headers(self):
        if "Cache-Control" not in "".join(h.decode(errors="ignore") for h in getattr(self, "_headers_buffer", [])):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), partial(Handler, directory=str(ROOT)))
    print(f"Job Dashboard DEMO running at http://{HOST}:{PORT}/  (fake data, any password works, Ctrl+C to stop)")
    if "--open" in sys.argv:
        import webbrowser
        webbrowser.open(f"http://{HOST}:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
