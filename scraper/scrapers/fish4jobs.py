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
            "https://www.fish4.co.uk/jobs/",
            params={"keywords": keyword, "location": "United Kingdom", "distance": 0, "sort": "date"},
            headers=HEADERS, timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for card in soup.select(".job-result, .listing, article.job"):
            title_el = card.select_one("h2 a, h3 a, .job-title a")
            company_el = card.select_one(".company, .employer, .recruiter")
            location_el = card.select_one(".location, .job-location")
            salary_el = card.select_one(".salary, .job-salary")
            if not title_el:
                continue
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.fish4.co.uk" + href
            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                location=location_el.get_text(strip=True) if location_el else "",
                salary=salary_el.get_text(strip=True) if salary_el else "",
                url=href, source="Fish4Jobs", keywords=keyword, description="",
            ))
    except Exception as e:
        logger.error(f"Fish4Jobs error for '{keyword}': {e}")
    return jobs
