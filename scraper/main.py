import concurrent.futures
import logging
import os
import re
import sys
import time
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
import rater
from airtable_client import AirtableClient
from matching import compile_terms, any_match
from scrapers import (
    reed, adzuna,
    totaljobs, cwjobs, jobsite, guardian, fish4jobs,
    milkround,
    jora, s1jobs, gradcracker, trackr, linkedin,
    prospects, targetjobs, grb, greenhouse,
    description_fetcher,
)
import qualification_checker

# Word-boundary-safe versions of config.EXCLUDED_TITLE_KEYWORDS — plain
# substring checks let short entries like "cto" false-match inside "factory"
# or "doctor" (found 26 Jul 2026 during the ratings audit).
_EXCLUDED_TITLE_PATTERNS = compile_terms(config.EXCLUDED_TITLE_KEYWORDS)

# Explicit carve-outs: these compound titles are deliberately allowed target
# roles even though they contain a word that's otherwise excluded on its own
# ("partner" is excluded to catch senior law/consulting "Partner" titles, but
# "Partner Manager" — added as a target role 26 Jul 2026 — is a real word
# match for "partner" too, not a substring bug, so it needs an explicit
# exception rather than the matching.py word-boundary fix).
_EXCLUDED_TITLE_CARVE_OUTS = ("partner manager",)

_lock_file = None  # kept open for the life of the process; the OS releases the lock on exit


def _acquire_single_instance_lock(path: str) -> None:
    """Refuses to start a second instance — an overlapping launch (e.g. the
    Startup shortcut firing while a prior session's process is still alive)
    is what caused two processes to fight over scraper.log's file handle."""
    global _lock_file
    f = open(path, "w")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"Another instance already holds {path} — exiting.")
        sys.exit(0)
    _lock_file = f


_acquire_single_instance_lock("scraper.lock")
os.makedirs("logs", exist_ok=True)


def _open_log_handler(path: str, retries: int = 5, delay: float = 2.0) -> logging.FileHandler:
    """Retries on PermissionError — transient file locks (antivirus, indexing,
    a not-yet-exited previous instance) shouldn't take the whole scraper down."""
    last_err = None
    for _ in range(retries):
        try:
            return logging.FileHandler(path, encoding="utf-8")
        except PermissionError as e:
            last_err = e
            time.sleep(delay)
    raise last_err


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        _open_log_handler("logs/scraper.log"),
    ],
)
logger = logging.getLogger(__name__)


def _is_excluded(title: str) -> bool:
    t = title.lower()
    if any(c in t for c in _EXCLUDED_TITLE_CARVE_OUTS):
        return False
    return any_match(_EXCLUDED_TITLE_PATTERNS, t)


def _normalize_title(title: str) -> str:
    """Strip reference codes and normalise for dedup comparison."""
    t = re.sub(r'\s*\([A-Z]{1,4}\d{4,}\)', '', title, flags=re.IGNORECASE)  # (HF1234567)
    t = re.sub(r'\s*\(ref:?\s*[\w\d\-]+\)', '', t, flags=re.IGNORECASE)     # (Ref: 123)
    t = t.replace('-', ' ')
    t = re.sub(r'\s+', ' ', t).strip()
    return t.lower()



def run():
    logger.info("── Job scrape started ──────────────────────────────")
    client = AirtableClient(config.AIRTABLE_TOKEN, config.AIRTABLE_BASE_ID, config.AIRTABLE_TABLE_NAME)

    try:
        seen_urls = client.get_all_urls()
        logger.info(f"Loaded {len(seen_urls)} existing URLs for dedup")
    except Exception as e:
        logger.warning(f"Could not load existing URLs: {e}")
        seen_urls = set()

    try:
        raw_pairs = client.get_all_company_titles()
        # Normalise titles on load so future comparisons match
        seen_company_titles = {(c.lower().strip(), _normalize_title(t)) for c, t in raw_pairs}
        logger.info(f"Loaded {len(seen_company_titles)} existing company+title pairs for dedup")
    except Exception as e:
        logger.warning(f"Could not load company+title pairs: {e}")
        seen_company_titles = set()

    total_new = 0

    def _process_job(job) -> bool:
        """Returns True if job was added to Airtable."""
        if not job.url or job.url in seen_urls:
            return False
        if _is_excluded(job.title):
            return False
        if any(c in job.company.lower() for c in config.EXCLUDED_COMPANIES):
            return False

        # Company + normalised title dedup (strips ref codes, ignores location differences)
        norm_title = _normalize_title(job.title)
        company_title_key = (job.company.lower().strip(), norm_title)
        if company_title_key in seen_company_titles:
            return False

        seen_urls.add(job.url)
        seen_company_titles.add(company_title_key)

        # Most scrapers can't get a real job description from search-result
        # pages (it lives on the posting page itself). Fetch it lazily here —
        # only for candidates that already survived the cheap filters above —
        # so the rater can actually check qualifications/experience. Below
        # MIN_USABLE_DESCRIPTION_CHARS as well as empty — some API sources
        # (Adzuna confirmed 10 Aug 2026, "Graduate Management Trainee" @
        # Enterprise Rent-A-Car/Mobility, ~85 near-duplicate postings across
        # UK cities) return a short truncated teaser rather than nothing,
        # which silently starved the AI qualification check of the actual
        # requirements text and made it flag every one "AI Uncertain" instead
        # of giving a confident answer. Same threshold retrate_airtable.py
        # already uses for the same reason on the backlog-refresh path.
        if not job.description or len(job.description) < config.MIN_USABLE_DESCRIPTION_CHARS:
            fetched = description_fetcher.fetch_description(job.url)
            if fetched:
                job.description = fetched

        rating = rater.rate(job)
        if rating["rating"] < config.MIN_RATING:
            return False

        # Second-pass LLM qualification check — only on jobs that already
        # cleared the cheap keyword filter above, to keep API volume low.
        # Catches cases the keyword rater can't (coincidental buzzword
        # overlap, irrelevant industries not yet on the exclusion list).
        qualifies, ai_reason, ai_uncertain = qualification_checker.check_qualifies(
            config.ANTHROPIC_API_KEY, config.CANDIDATE_PROFILE, job.title, job.description,
            profile_data=config.PROFILE,
        )
        if not qualifies:
            logger.info(f"  AI-excluded: {job.title!r} @ {job.company!r} — {ai_reason}")
            return False
        rating["notes"] = f"{rating['notes']} AI check: {ai_reason}"
        if ai_uncertain:
            rating["flag_category"] = "AI Uncertain"
            rating["flag_note"] = ai_reason
            logger.info(f"  AI uncertain: {job.title!r} @ {job.company!r} — {ai_reason}")

        if client.add_job(job, rating):
            time.sleep(0.2)
            return True
        return False

    # Gradcracker: scrape once (keyword search doesn't filter well)
    logger.info("Scraping Gradcracker (maths-business discipline)...")
    for job in gradcracker.scrape_all():
        if _process_job(job):
            total_new += 1

    # GRB: Cloudflare-protected + JS-driven pagination, needs a real browser
    # (Playwright) rather than requests — see scrapers/grb.py. seen_urls lets
    # it skip the expensive per-job detail-page visit for already-known jobs.
    logger.info("Scraping GRB (graduate-jobs)...")
    grb_jobs = grb.scrape_all(seen_urls)
    grb_new = sum(_process_job(job) for job in grb_jobs)
    logger.info(f"  GRB: {len(grb_jobs)} new listings fetched, {grb_new} added")
    total_new += grb_new

    # Greenhouse: company career sites (open API, no browser needed) — see
    # GREENHOUSE_BOARDS in scrapers/greenhouse.py to add more companies.
    logger.info("Scraping Greenhouse company boards...")
    greenhouse_jobs = greenhouse.scrape_all()
    greenhouse_new = sum(_process_job(job) for job in greenhouse_jobs)
    logger.info(f"  Greenhouse: {len(greenhouse_jobs)} listings fetched, {greenhouse_new} added")
    total_new += greenhouse_new

    # Trackr: UK Tech + Finance graduate programmes and spring weeks
    logger.info("Scraping Trackr (UK graduate programmes)...")
    trackr_jobs = trackr.scrape_all()
    trackr_new = sum(_process_job(job) for job in trackr_jobs)
    logger.info(f"  Trackr: {len(trackr_jobs)} found, {trackr_new} new added")
    total_new += trackr_new

    # LinkedIn: unauthenticated guest endpoint, kept to a small keyword subset
    # and throttled — see scrapers/linkedin.py for why.
    logger.info("Scraping LinkedIn (limited keyword set)...")
    for keyword in config.LINKEDIN_KEYWORDS:
        jobs = linkedin.scrape(keyword)
        new = sum(_process_job(job) for job in jobs)
        logger.info(f"  LinkedIn '{keyword}': {len(jobs)} found, {new} new added")
        total_new += new

    # All per-keyword site scrapers are independent, stateless HTTP calls (no
    # shared session state — verified 11 Aug 2026), so they're fan out
    # concurrently per keyword rather than run one-after-another. A full
    # cycle was taking ~6-7 hours against a configured 3-hour interval
    # (found 11 Aug 2026 — a job posted on LinkedIn was invisible for 5+
    # hours because the cycle hadn't looped back around), almost entirely
    # spent in this loop summing 12 sequential site latencies per keyword
    # instead of overlapping them.
    _SITE_SCRAPERS = [totaljobs, cwjobs, jobsite, guardian, fish4jobs, milkround, jora, s1jobs, prospects, targetjobs]

    for keyword in config.SEARCH_KEYWORDS:
        logger.info(f"Searching: '{keyword}'")
        jobs = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            futures = []
            if config.REED_API_KEY:
                futures.append(executor.submit(reed.scrape, keyword, config.REED_API_KEY))
            if config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY:
                futures.append(executor.submit(adzuna.scrape, keyword, config.ADZUNA_APP_ID, config.ADZUNA_APP_KEY))
            for site in _SITE_SCRAPERS:
                futures.append(executor.submit(site.scrape, keyword))

            for future in concurrent.futures.as_completed(futures):
                try:
                    jobs += future.result()
                except Exception as e:
                    logger.error(f"Scraper error for '{keyword}': {e}")

        new = sum(_process_job(job) for job in jobs)
        logger.info(f"  '{keyword}': {len(jobs)} found, {new} new added")
        total_new += new

    logger.info(f"── Done: {total_new} new jobs sent to Airtable ────────")


if __name__ == "__main__":
    run()

    scheduler = BlockingScheduler()
    scheduler.add_job(run, IntervalTrigger(hours=config.RUN_INTERVAL_HOURS))
    logger.info(f"Scheduler running — next run in {config.RUN_INTERVAL_HOURS} hours")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopped.")
