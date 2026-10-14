"""
Greenhouse (boards-api.greenhouse.io) is the ATS behind a large number of
companies' own "Careers" pages — including finance/banking firms that never
post to Reed/Adzuna/LinkedIn and would otherwise be invisible to this
scraper (e.g. William Blair, found 09 Aug 2026 via two job links the user
had found manually). Unlike GRB and Bright Network, Greenhouse's job board
API is completely open — no Cloudflare, no auth, plain JSON — and
`?content=true` returns every open role's full description in a single
request, so there's no per-job detail-page fetch needed at all.

GREENHOUSE_BOARDS lists which companies' boards to check. Add a company by
finding its board token: visit the company's Careers page, find a job, and
its URL either contains `?gh_jid=...` (board token is often the URL's
subdomain, e.g. jobs.<token>.com) or links out to
`boards.greenhouse.io/<token>` / `job-boards.greenhouse.io/<token>` — that
token is what goes in this list. Verify with:
  https://boards-api.greenhouse.io/v1/boards/<token>/jobs
A 200 with a "jobs" array confirms the token; a 404 means it's not on
Greenhouse (or uses a different token) — try the company's own board
directly.
"""

import html
import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import Job

logger = logging.getLogger(__name__)

GREENHOUSE_BOARDS = [
    "williamblair",
]

API_URL_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
MAX_DESCRIPTION_CHARS = 20000  # raised from 6000 11 Aug 2026, see description_fetcher.py


def _job_from_posting(posting: dict) -> Job:
    title = posting.get("title", "") or ""
    company = posting.get("company_name", "") or ""
    location = posting.get("location", {}).get("name", "") or ""
    url = posting.get("absolute_url", "") or ""
    date_posted = posting.get("first_published", "") or ""

    raw_desc = posting.get("content", "") or ""
    desc_text = BeautifulSoup(html.unescape(raw_desc), "lxml").get_text(separator=" ", strip=True)
    desc_text = re.sub(r"\s+", " ", desc_text).strip()[:MAX_DESCRIPTION_CHARS]

    return Job(
        title=title,
        company=company,
        location=location,
        salary="",  # Greenhouse postings don't expose salary in structured data
        url=url,
        source="Greenhouse",
        keywords="greenhouse",
        description=desc_text,
        date_posted=date_posted,
    )


def scrape_all(timeout: int = 20) -> list[Job]:
    """Fetch all current open roles for every board in GREENHOUSE_BOARDS.
    No seen_urls param needed (unlike GRB) — the whole catalog for a board
    comes back in one lightweight request with full descriptions included,
    so there's no expensive per-job step worth skipping; main.py's own
    seen_urls dedup handles not re-adding already-known jobs."""
    jobs: list[Job] = []
    for token in GREENHOUSE_BOARDS:
        try:
            resp = requests.get(API_URL_TEMPLATE.format(token=token), headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            postings = resp.json().get("jobs", [])
            for posting in postings:
                jobs.append(_job_from_posting(posting))
            logger.info(f"Greenhouse ({token}): {len(postings)} open roles fetched")
        except Exception as e:
            logger.error(f"Greenhouse ({token}) error: {e}")
    return jobs
