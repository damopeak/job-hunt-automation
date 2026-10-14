import requests
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AirtableClient:
    BASE_URL = "https://api.airtable.com/v0"

    def __init__(self, token: str, base_id: str, table_name: str):
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.url = f"{self.BASE_URL}/{base_id}/{table_name}"

    def get_all_urls(self) -> set:
        seen = set()
        offset = None
        while True:
            params = {"fields[]": "URL", "pageSize": 100}
            if offset:
                params["offset"] = offset
            resp = requests.get(self.url, headers=self.headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for record in data.get("records", []):
                url = record.get("fields", {}).get("URL")
                if url:
                    seen.add(url)
            offset = data.get("offset")
            if not offset:
                break
        return seen

    def get_all_company_titles(self) -> set:
        """Returns a set of (company_lower, title_lower) tuples from existing records."""
        seen = set()
        offset = None
        while True:
            params = [("pageSize", 100), ("fields[]", "Company"), ("fields[]", "Job Title")]
            if offset:
                params.append(("offset", offset))
            resp = requests.get(self.url, headers=self.headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for record in data.get("records", []):
                fields = record.get("fields", {})
                company = (fields.get("Company") or "").lower().strip()
                title = (fields.get("Job Title") or "").strip()
                if company and title:
                    seen.add((company, title))
            offset = data.get("offset")
            if not offset:
                break
        return seen

    def add_job(self, job, rating: dict) -> bool:
        try:
            missing = [f for f, v in [("Salary", job.salary), ("Location", job.location), ("Company", job.company), ("Description", job.description)] if not v]
            notes = rating.get("notes", "")
            if missing:
                notes = (notes + f" Missing: {', '.join(missing)}.").strip()

            fields = {
                "Job Title": job.title,
                "URL": job.url,
                "Source": job.source,
                "Keywords": job.keywords,
                "Date Found": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "Rating": rating.get("rating"),
                "Seniority Match": "Yes" if rating.get("seniority_match") else "No",
                "Rating Notes": notes,
                "Status": "Not applied",
            }
            if job.date_posted:
                fields["Date Posted"] = job.date_posted
            if job.company:
                fields["Company"] = job.company
            if job.location:
                fields["Location"] = job.location
            if job.salary:
                fields["Salary"] = job.salary
            if job.description:
                fields["Description"] = job.description
            if rating.get("flag_category"):
                fields["Flag Category"] = rating["flag_category"]
            if rating.get("flag_note"):
                fields["Flag Note"] = rating["flag_note"]

            # typecast lets Airtable auto-create a new single-select option
            # (e.g. "AI Uncertain" on Flag Category) instead of rejecting it
            payload = {"fields": fields, "typecast": True}
            resp = requests.post(self.url, headers=self.headers, json=payload, timeout=15)
            if resp.status_code == 422 and "Date Posted" in resp.text and "Date Posted" in fields:
                fields.pop("Date Posted")
                resp = requests.post(self.url, headers=self.headers, json={"fields": fields, "typecast": True}, timeout=15)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Airtable error for '{job.title}': {e} — {getattr(getattr(e, 'response', None), 'text', '')}")
            return False
