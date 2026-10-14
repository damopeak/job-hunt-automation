import requests
from bs4 import BeautifulSoup
import logging
from .base import Job

logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def scrape(keyword: str) -> list:
    jobs = []
    try:
        resp = requests.get(
            "https://www.prospects.ac.uk/jobs-and-work-experience/job-sectors",
            params={"search": keyword},
            headers=HEADERS, timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for card in soup.select(".job-listing, .vacancy, article.job, .job-item"):
            title_el = card.select_one("h2 a, h3 a, .job-title a, .title a")
            company_el = card.select_one(".company, .employer, .organisation")
            location_el = card.select_one(".location, .job-location")
            salary_el = card.select_one(".salary, .job-salary")
            if not title_el:
                continue
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.prospects.ac.uk" + href
            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                location=location_el.get_text(strip=True) if location_el else "",
                salary=salary_el.get_text(strip=True) if salary_el else "",
                url=href, source="Prospects", keywords=keyword, description="",
            ))
    except Exception as e:
        logger.error(f"Prospects error for '{keyword}': {e}")
    return jobs
