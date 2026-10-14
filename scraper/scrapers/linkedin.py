import logging
import time

import requests
from bs4 import BeautifulSoup

from .base import Job

logger = logging.getLogger(__name__)

# LinkedIn's unauthenticated "guest" search endpoint — no login required, but
# unofficial and rate-limited. Kept to a small keyword list (see
# config.LINKEDIN_KEYWORDS) with a delay between every request, and backs off
# hard on 429s, to offset the risk of paging deep into results.
SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}
REQUEST_DELAY_SECONDS = 3
RESULTS_PER_PAGE = 10  # LinkedIn's guest endpoint pages in batches of 10, not 25
MAX_PAGES = 6


def _fetch_page(keyword: str, start: int):
    resp = requests.get(
        SEARCH_URL,
        params={
            "keywords": keyword,
            "location": "United Kingdom",
            "f_TPR": "r86400",  # posted in the last 24h
            "start": start,
        },
        headers=HEADERS,
        timeout=15,
    )
    if resp.status_code == 429:
        logger.warning("LinkedIn rate-limited us (429) — backing off for this cycle")
        time.sleep(REQUEST_DELAY_SECONDS * 3)
        return None
    resp.raise_for_status()
    return resp.text


def scrape(keyword: str) -> list:
    jobs = []
    try:
        for page in range(MAX_PAGES):
            html = _fetch_page(keyword, page * RESULTS_PER_PAGE)
            if html is None:
                break  # rate-limited — stop paging this keyword

            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("li > div.base-card, div.job-search-card")
            if not cards:
                break  # no more results

            for card in cards:
                link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
                title_el = card.select_one("h3.base-search-card__title")
                company_el = card.select_one("h4.base-search-card__subtitle a, h4.base-search-card__subtitle")
                location_el = card.select_one("span.job-search-card__location")
                date_el = card.select_one("time.job-search-card__listdate, time")

                if not link_el or not title_el:
                    continue

                href = link_el.get("href", "").split("?")[0]
                jobs.append(Job(
                    title=title_el.get_text(strip=True),
                    company=company_el.get_text(strip=True) if company_el else "",
                    location=location_el.get_text(strip=True) if location_el else "",
                    salary="",
                    url=href,
                    source="LinkedIn",
                    keywords=keyword,
                    description="",
                    date_posted=date_el.get("datetime", "") if date_el else "",
                ))

            time.sleep(REQUEST_DELAY_SECONDS)

            if len(cards) < RESULTS_PER_PAGE:
                break  # last page
    except Exception as e:
        logger.error(f"LinkedIn error for '{keyword}': {e}")
    return jobs
