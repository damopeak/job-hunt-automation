import requests
import logging
from datetime import datetime, timezone
from .base import Job

logger = logging.getLogger(__name__)
API_URL = "https://api.the-trackr.com/programmes"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Fetch these combinations every run
QUERIES = [
    {"region": "UK", "industry": "Tech",    "season": "2026", "type": "graduate-programmes"},
    {"region": "UK", "industry": "Finance", "season": "2026", "type": "graduate-programmes"},
    {"region": "UK", "industry": "Finance", "season": "2026", "type": "off-cycle-internships"},
    {"region": "UK", "industry": "Finance", "season": "2027", "type": "off-cycle-internships"},
]


def scrape_all() -> list[Job]:
    jobs = []
    seen_ids = set()
    for params in QUERIES:
        try:
            resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            for item in resp.json():
                if item["id"] in seen_ids:
                    continue
                seen_ids.add(item["id"])
                if not item.get("openingDate"):
                    continue
                now = datetime.now(timezone.utc)
                opening = datetime.fromisoformat(item["openingDate"].replace("Z", "+00:00"))
                if opening > now:
                    continue
                closing = item.get("closingDate")
                if closing:
                    closing_dt = datetime.fromisoformat(closing.replace("Z", "+00:00"))
                    if closing_dt < now:
                        continue
                company = (item.get("company") or {}).get("name") or item.get("companyId", "")
                # Note: item.company.description is the COMPANY blurb, not the
                # job posting — not useful for qualification checks, so leave
                # description empty and let main.py fetch the real job page.
                jobs.append(Job(
                    title=item.get("name", ""),
                    company=company,
                    location="UK",
                    salary="",
                    url=item.get("url", ""),
                    source="Trackr",
                    keywords=f"{params['industry']} {params['type']}",
                    description="",
                    date_posted=item.get("openingDate", ""),
                ))
        except Exception as e:
            logger.error(f"Trackr error ({params}): {e}")
    return jobs
