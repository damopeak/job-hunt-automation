import requests
import logging
from .base import Job

logger = logging.getLogger(__name__)
BASE_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/1"


def scrape(keyword: str, app_id: str, app_key: str) -> list:
    if not app_id or not app_key:
        return []
    jobs = []
    try:
        resp = requests.get(
            BASE_URL,
            params={
                "app_id": app_id,
                "app_key": app_key,
                "results_per_page": 50,
                "what": keyword,
                "where": "UK",
                "sort_by": "date",
            },
            timeout=15,
        )
        resp.raise_for_status()
        for j in resp.json().get("results", []):
            lo = j.get("salary_min")
            hi = j.get("salary_max")
            if lo and hi:
                salary = f"£{int(lo):,} - £{int(hi):,}"
            elif lo:
                salary = f"£{int(lo):,}+"
            else:
                salary = ""
            jobs.append(Job(
                title=j.get("title", ""),
                company=j.get("company", {}).get("display_name", ""),
                location=j.get("location", {}).get("display_name", ""),
                salary=salary,
                url=j.get("redirect_url", ""),
                source="Adzuna",
                keywords=keyword,
                description=j.get("description", ""),
                # Airtable's "Date Posted" field silently rejects any non-midnight
                # time (Adzuna's "created" has the real time-of-day, e.g.
                # "16:50:58Z") — the whole field gets dropped by airtable_client's
                # 422-retry fallback, which is why Adzuna jobs never had a Date
                # Posted. Truncate to bare YYYY-MM-DD, same as what Reed/LinkedIn
                # already send successfully. Found 28 Jul 2026.
                date_posted=j.get("created", "")[:10],
            ))
    except Exception as e:
        logger.error(f"Adzuna error for '{keyword}': {e}")
    return jobs
