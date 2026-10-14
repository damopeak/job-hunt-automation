import requests
import logging
from datetime import datetime
from .base import Job

logger = logging.getLogger(__name__)
BASE_URL = "https://www.reed.co.uk/api/1.0/search"


def scrape(keyword: str, api_key: str) -> list:
    if not api_key:
        return []
    jobs = []
    try:
        resp = requests.get(
            BASE_URL,
            params={"keywords": keyword, "locationName": "United Kingdom", "resultsToTake": 100, "sortBy": "date"},
            auth=(api_key, ""),
            timeout=15,
        )
        resp.raise_for_status()
        for j in resp.json().get("results", []):
            jobs.append(Job(
                title=j.get("jobTitle", ""),
                company=j.get("employerName", ""),
                location=j.get("locationName", ""),
                salary=_fmt(j.get("minimumSalary"), j.get("maximumSalary")),
                url=j.get("jobUrl") or f"https://www.reed.co.uk/jobs/{j.get('jobId')}",
                source="Reed",
                keywords=keyword,
                description=j.get("jobDescription", ""),
                date_posted=_parse_date(j.get("date", "")),
            ))
    except Exception as e:
        logger.error(f"Reed error for '{keyword}': {e}")
    return jobs


def _parse_date(d: str) -> str:
    try:
        return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%dT00:00:00.000Z")
    except Exception:
        return ""


def _fmt(lo, hi):
    if lo and hi:
        return f"£{int(lo):,} - £{int(hi):,}"
    if lo:
        return f"£{int(lo):,}+"
    return ""
