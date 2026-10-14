import logging
from .base import Job

logger = logging.getLogger(__name__)


def scrape(keyword: str) -> list:
    jobs = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"https://targetjobs.co.uk/search/jobs?term={keyword.replace(' ', '+')}", timeout=20000)
            page.wait_for_timeout(3000)

            cards = page.query_selector_all("article, [data-testid='job-card'], .job-listing, li.vacancy")
            for card in cards:
                title_el = card.query_selector("h2 a, h3 a, .job-title a, a[href*='/jobs/']")
                company_el = card.query_selector(".company, .employer, .organisation")
                location_el = card.query_selector(".location, .job-location")
                salary_el = card.query_selector(".salary, .job-salary")
                if not title_el:
                    continue
                href = title_el.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://targetjobs.co.uk" + href
                jobs.append(Job(
                    title=title_el.inner_text().strip(),
                    company=company_el.inner_text().strip() if company_el else "",
                    location=location_el.inner_text().strip() if location_el else "",
                    salary=salary_el.inner_text().strip() if salary_el else "",
                    url=href, source="TargetJobs", keywords=keyword, description="",
                ))
            browser.close()
    except Exception as e:
        logger.error(f"TargetJobs error for '{keyword}': {e}")
    return jobs
