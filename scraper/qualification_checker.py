"""
Second-pass LLM qualification check. The keyword-based rater (rater.py) is
fast and free but fundamentally a bag-of-words heuristic — it can be fooled
by coincidental buzzword overlap (e.g. a Water Treatment Engineer posting
that happens to mention "Junior Account Manager" as a future career step)
and needs an ever-growing exclusion list for every new irrelevant industry
that slips through. This module asks Claude directly: does the candidate
actually meet this posting's minimum qualifications? Only called on jobs
that already cleared rater.py's MIN_RATING threshold, to keep API volume low.
"""

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"

PROMPT_TEMPLATE = """You are screening a job posting against a candidate's profile to check ONLY whether the candidate meets the posting's MINIMUM stated qualifications — not whether it's a good fit or good career move, just eligibility.

CANDIDATE PROFILE:
{profile}

JOB TITLE: {title}

JOB DESCRIPTION:
{description}

Focus specifically on:
1. Required years of professional experience (the candidate has {years_experience} years of full-time employed experience — {experience_note}). If the posting requires "X+ years" of experience in a professional/employed capacity where X >= 2, they do NOT qualify.
2. Required industry licenses or professional qualifications the candidate doesn't hold (e.g. qualified accountant, professional engineer, specific degree not held, security clearance, right to work issues). Only count something as required if the posting says so explicitly ("required", "essential", "must have", "must hold"). If the posting frames a specific degree/subject/qualification as "preferred", "desirable", "advantageous", "a plus", or "nice to have" rather than required, the candidate's {degree} still satisfies the underlying "Bachelor's degree" requirement even though it isn't the preferred subject — do not reject for this.
3. Whether the role's actual subject matter is even remotely relevant to the candidate's background ({background_sectors}) — reject roles in totally unrelated technical/scientific/engineering trades (e.g. geoscience, civil/mechanical/water engineering) even if some buzzwords coincidentally overlap with the candidate's profile.

Do NOT reject or flag based on salary. The profile's target salary is a floor, not a ceiling — a higher salary is never a disqualifying factor and is irrelevant to eligibility. Salary fit is scored separately elsewhere in the pipeline; ignore it entirely for this check.

Respond with ONLY a compact JSON object, no other text: {{"qualifies": true, false, or "uncertain", "reason": "one brief sentence"}}

Use "uncertain" ONLY when the posting genuinely doesn't give you enough information to make a confident call (e.g. no experience requirement stated, vague/thin description) or it's a truly borderline judgment call — not as a default hedge. When the posting gives a clear signal, answer true or false."""


def check_qualifies(api_key: str, profile: str, title: str, description: str, timeout: int = 20,
                     profile_data: dict | None = None) -> tuple:
    """Returns (qualifies: bool, reason: str, uncertain: bool). "uncertain"
    jobs are still let through (qualifies=True) but flagged separately so a
    human can review the borderline call. Fails OPEN (qualifies=True) on
    any API/parsing error or missing key, so a transient outage or missing
    config doesn't silently suppress every job — the keyword-based Rating
    threshold already gates what reaches this check in the first place."""
    # Off by default (ENABLE_AI_CHECK=false) to avoid API costs — rater.py's
    # keyword exclusions were hardened using patterns pulled from this check's
    # own exclusion history, to recover as much coverage as possible for free.
    # Set ENABLE_AI_CHECK=true (plus ANTHROPIC_API_KEY) to switch it back on.
    if os.getenv("ENABLE_AI_CHECK", "false").lower() not in ("1", "true", "yes"):
        return True, "AI check disabled — rater.py keyword exclusions only", False
    if not api_key:
        return True, "AI check skipped (no API key configured)", False
    # Raised from 4000 to 20000 on 11 Aug 2026, matching description_fetcher's
    # storage cap — a job requiring a preceding fix (that cap) so the full
    # text even reaches this function is pointless if this slice re-truncates
    # it again right before the AI ever sees it. Haiku's 200K context and
    # per-call cost make a larger slice negligible.
    p = profile_data or {}
    prompt = PROMPT_TEMPLATE.format(
        profile=profile.strip(),
        title=title,
        description=(description or "")[:20000],
        degree=p.get("degree", "degree"),
        years_experience=p.get("years_full_time_experience", 0),
        experience_note=p.get("experience_note", "only internships and self-employment"),
        background_sectors=", ".join(p.get("background_sectors", [])) or "see profile",
    )
    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 150,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        data = json.loads(text)
        raw = data.get("qualifies", True)
        reason = str(data.get("reason", ""))[:300]
        if isinstance(raw, str) and raw.strip().lower() == "uncertain":
            return True, reason, True
        return bool(raw), reason, False
    except Exception as e:
        logger.warning(f"Qualification check failed, defaulting to pass: {e}")
        return True, "AI check failed (defaulted to pass)", False
