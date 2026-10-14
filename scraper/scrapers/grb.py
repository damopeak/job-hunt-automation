"""
GRB (Graduate Recruitment Bureau, grb.uk.com) is Cloudflare-protected against
plain HTTP clients — a bare `requests.get()` gets a 403 even on robots.txt —
and its listing pagination is JS-driven (FacetWP AJAX; there's no per-page
URL to request directly). Every other scraper in this project uses
requests+BeautifulSoup, but that approach cannot reach this site at all, so
this one drives a real headless Chromium browser via Playwright instead.

Individual job pages embed the full posting as schema.org JobPosting JSON-LD
(same mechanism scrapers/description_fetcher.py relies on for other sites),
so once Playwright gets past Cloudflare the actual data extraction is clean
and reliable.
"""

import html
import json
import logging
import re
import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from .base import Job

logger = logging.getLogger(__name__)

LISTING_URL = "https://www.grb.uk.com/graduate-jobs"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
JOB_URL_RE = re.compile(r"^https://www\.grb\.uk\.com/graduate-jobs/[a-z0-9-]+-\d+/?$")
MAX_PAGES = 20  # safety cap against a pagination-detection bug; site currently has ~5 pages
MAX_DESCRIPTION_CHARS = 20000  # raised from 6000 11 Aug 2026, see description_fetcher.py
DETAIL_FETCH_DELAY = 0.3  # be polite between per-job detail page navigations


def _extract_job_posting(html_text: str) -> dict | None:
    """Pull the schema.org JobPosting object out of a GRB job page's JSON-LD."""
    soup = BeautifulSoup(html_text, "lxml")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        candidates = data.get("@graph", [data]) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") == "JobPosting":
                return c
    return None


def _job_from_posting(posting: dict, url: str) -> Job:
    title = posting.get("title", "") or ""

    org = posting.get("hiringOrganization")
    company = org.get("name", "") if isinstance(org, dict) else ""

    location = ""
    loc = posting.get("jobLocation")
    if isinstance(loc, dict):
        address = loc.get("address")
        if isinstance(address, dict):
            location = address.get("addressLocality", "") or ""

    salary = ""
    base = posting.get("baseSalary")
    if isinstance(base, dict):
        value = base.get("value")
        amount = value.get("value") if isinstance(value, dict) else None
        if amount:
            try:
                salary = f"£{int(float(amount)):,}"
            except (TypeError, ValueError):
                salary = str(amount)

    raw_desc = posting.get("description", "") or ""
    desc_text = BeautifulSoup(html.unescape(raw_desc), "lxml").get_text(separator=" ", strip=True)
    desc_text = re.sub(r"\s+", " ", desc_text).strip()[:MAX_DESCRIPTION_CHARS]

    return Job(
        title=title,
        company=company,
        location=location,
        salary=salary,
        url=url,
        source="GRB",
        keywords="grb",
        description=desc_text,
        date_posted=posting.get("datePosted", "") or "",
    )


def scrape_all(seen_urls: set | None = None) -> list[Job]:
    """Fetch all current GRB graduate-jobs listings not already in seen_urls.
    Call once per run, not per keyword. seen_urls lets us skip the expensive
    per-job detail-page visit for postings main.py would dedup away anyway —
    without it, every run would re-visit all ~90 listings via a full browser
    navigation just to throw most of them away."""
    seen_urls = seen_urls or set()
    jobs: list[Job] = []
    job_urls: list[str] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=UA)
            page.goto(LISTING_URL, timeout=30000, wait_until="networkidle")

            seen_on_listing = set()
            stagnant_rounds = 0
            for _ in range(MAX_PAGES):
                hrefs = page.eval_on_selector_all(
                    "a[href*='/graduate-jobs/']", "els => els.map(e => e.href)"
                )
                before = len(seen_on_listing)
                for href in hrefs:
                    if JOB_URL_RE.match(href) and href not in seen_on_listing:
                        seen_on_listing.add(href)
                        job_urls.append(href)

                if len(seen_on_listing) == before:
                    stagnant_rounds += 1
                    if stagnant_rounds >= 2:
                        break
                else:
                    stagnant_rounds = 0

                next_btn = page.locator("a.facetwp-page.next")
                if next_btn.count() == 0:
                    break
                try:
                    next_btn.first.click(timeout=5000)
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    break

            logger.info(f"GRB: {len(job_urls)} job URLs found across listing pages")

            new_urls = [u for u in job_urls if u not in seen_urls]
            for url in new_urls:
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    posting = _extract_job_posting(page.content())
                    if posting:
                        jobs.append(_job_from_posting(posting, url))
                    time.sleep(DETAIL_FETCH_DELAY)
                except Exception as e:
                    logger.debug(f"GRB job page failed for {url}: {e}")

            browser.close()
    except Exception as e:
        logger.error(f"GRB error: {e}")

    logger.info(f"GRB: {len(jobs)} new jobs fetched ({len(job_urls)} listed, {len(job_urls) - len(jobs)} skipped/already-seen)")
    return jobs
