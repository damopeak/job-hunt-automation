import requests
from bs4 import BeautifulSoup
import logging
from .base import Job

logger = logging.getLogger(__name__)
# Maths/Business discipline captures commercial, ecommerce, analyst, buying roles
BASE_URL = "https://www.gradcracker.com/search/maths-business/jobs"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
}


def scrape_all() -> list:
    """Fetch the full Gradcracker maths-business feed. Call once per run, not per keyword."""
    jobs = []
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for card in soup.select("article"):
            title_el = card.select_one("a[class*=tw-leading-tight]")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            url = title_el.get("href", "")

            img = card.select_one("img")
            company = img.get("alt", "") if img else ""

            salary = location = ""
            dl = card.select_one("dl")
            if dl:
                for div in dl.select("div"):
                    dt = div.select_one("dt")
                    dd = div.select_one("dd")
                    if dt and dd:
                        label = dt.get_text(strip=True)
                        value = dd.get_text(strip=True)
                        if label == "Salary":
                            salary = value
                        elif label == "Location":
                            location = value

            jobs.append(Job(
                title=title,
                company=company,
                location=location,
                salary=salary,
                url=url,
                source="Gradcracker",
                keywords="gradcracker",
                description="",
            ))
        logger.info(f"Gradcracker: {len(jobs)} jobs fetched")
    except Exception as e:
        logger.error(f"Gradcracker error: {e}")
    return jobs
