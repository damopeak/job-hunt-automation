import html
import json
import logging
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# Raised from 6000 to 20000 on 11 Aug 2026 — a blind head-truncation was
# silently discarding the "Requirements"/"What you'll need" section on
# postings with a long company-intro preamble (Square Mile Farms "Growth &
# Business Development Analyst", flagged: the stored description cut off
# before "You'll probably have around 3 years' experience...", so neither
# rater.py's hard-exclusion nor the AI qualification check ever saw the
# disqualifying requirement). Airtable long-text fields support up to
# 100,000 chars, so this was far more conservative than necessary.
MAX_DESCRIPTION_CHARS = 20000

# Generic safety net for sites with no JSON-LD JobPosting data: if the
# fetched visible text contains one of these tell-tale phrases, treat it as
# a login/consent wall rather than trusting the (probably boilerplate,
# possibly sidebar-polluted) text.
WALL_PHRASES = [
    "sign in to view", "log in to view", "join now to see",
    "create your free account",
    # "...3rd parties use essential and non-essential cookies" was here too,
    # but that's LinkedIn's universal cookie-banner text present on literally
    # every LinkedIn page (walled or not) — it was silently discarding pages
    # that have real content AFTER the banner (e.g. expired postings with no
    # JSON-LD but a full description still in the rendered text), not just
    # genuine login walls. Removed 07 Aug 2026; the other phrases here are
    # actually content-block-specific and stay.
]


def _extract_jsonld_job_description(soup: BeautifulSoup) -> str:
    """Most job boards (LinkedIn included) embed the full posting as
    schema.org JobPosting JSON-LD for Google Jobs SEO — present in the raw
    HTML even on pages whose rendered view shows a login/cookie wall. Try
    this first since it's the most reliable source when available."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        expanded = []
        for c in candidates:
            if isinstance(c, dict) and isinstance(c.get("@graph"), list):
                expanded.extend(c["@graph"])
            else:
                expanded.append(c)
        for c in expanded:
            if isinstance(c, dict) and c.get("@type") == "JobPosting" and c.get("description"):
                raw = html.unescape(c["description"])
                text = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
                return re.sub(r"\s+", " ", text).strip()
    return ""


def fetch_description(url: str, timeout: int = 20) -> str:
    """Fetches a job posting page and extracts its description so the rater
    can check qualifications/experience requirements that live in the full
    posting rather than just the title. Best-effort: returns "" on any
    failure or detected login/consent wall, since a missing description
    should never break scraping — and a wrong one is worse than a missing one."""
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        jsonld_desc = _extract_jsonld_job_description(soup)
        if jsonld_desc:
            return jsonld_desc[:MAX_DESCRIPTION_CHARS]

        for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if any(p in text.lower() for p in WALL_PHRASES):
            return ""
        return text[:MAX_DESCRIPTION_CHARS]
    except Exception as e:
        logger.debug(f"Description fetch failed for {url}: {e}")
        return ""
