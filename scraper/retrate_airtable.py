"""
One-off re-rate: recomputes Rating/Rating Notes/Seniority Match for existing
"Not applied" Airtable records using the current rater.py logic. Needed
because rater.py changes (e.g. the harder experience-years exclusion) only
apply to newly scraped jobs — existing rows keep whatever rating they were
given at add-time. Run once after any rater.py scoring-logic change, then
this file can be re-run again for the next change (not single-use like
cleanup_airtable.py).
"""

import sys
import time
from types import SimpleNamespace

import requests

# Windows' console defaults to cp1252, which can't encode every character
# that shows up in scraped company names — reconfigure so a stray accented
# character doesn't crash the report after the real Airtable updates succeed.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import rater
import qualification_checker
from scrapers import description_fetcher

# Threshold moved to config.MIN_USABLE_DESCRIPTION_CHARS 10 Aug 2026 so
# main.py's live scrape path and this backlog-refresh path can't drift apart
# — main.py had its own separate (and looser, empty-only) check until the
# same truncated-Adzuna-description bug was found affecting live scrapes too.
MIN_USABLE_DESCRIPTION_CHARS = config.MIN_USABLE_DESCRIPTION_CHARS

HEADERS = {"Authorization": f"Bearer {config.AIRTABLE_TOKEN}", "Content-Type": "application/json"}
BASE_URL = f"https://api.airtable.com/v0/{config.AIRTABLE_BASE_ID}/{config.AIRTABLE_TABLE_NAME}"


def fetch_not_applied() -> list:
    records = []
    offset = None
    while True:
        params = {"pageSize": 100, "filterByFormula": "{Status}='Not applied'"}
        if offset:
            params["offset"] = offset
        resp = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return records


def update_records(updates: list):
    """updates: list of {"id": ..., "fields": {...}}"""
    for i in range(0, len(updates), 10):
        batch = updates[i:i + 10]
        resp = requests.patch(BASE_URL, headers=HEADERS, json={"records": batch, "typecast": True}, timeout=15)
        resp.raise_for_status()
        time.sleep(0.25)


def main():
    print("Fetching 'Not applied' Airtable records...")
    records = fetch_not_applied()
    print(f"Found {len(records)} records.\n")

    updates = []
    dropped_below_threshold = []
    changed_count = 0
    refetched_count = 0
    ai_excluded_count = 0

    for i, record in enumerate(records):
        fields = record.get("fields", {})
        description = fields.get("Description") or ""
        url = fields.get("URL") or ""
        description_changed = False

        # 5900-6000 check added 11 Aug 2026 — one-time cleanup for the old
        # MAX_DESCRIPTION_CHARS=6000 head-truncation bug (description_fetcher.py
        # etc., raised to 20000 same day). A description landing in this exact
        # narrow band is very likely cut off mid-posting, before a
        # "Requirements"/"What you'll need" section that often sits well past
        # 6000 chars behind a long company-intro preamble — found via "Growth
        # & Business Development Analyst" (Square Mile Farms, rated 8, flagged
        # by user): the stored 6000-char description ended before "You'll
        # probably have around 3 years' experience...", so neither the rater
        # hard-exclusion nor the AI check ever saw it. This condition can be
        # removed once this one-time backlog pass has run.
        needs_refetch = len(description) < MIN_USABLE_DESCRIPTION_CHARS or 5900 <= len(description) <= 6000
        if needs_refetch and url:
            fetched = description_fetcher.fetch_description(url)
            if fetched != description:
                description = fetched
                description_changed = True
                if fetched:
                    refetched_count += 1

        job = SimpleNamespace(
            title=fields.get("Job Title") or "",
            description=description,
            location=fields.get("Location") or "",
            salary=fields.get("Salary") or "",
        )
        old_rating = fields.get("Rating")
        result = rater.rate(job)
        new_rating = result["rating"]
        new_notes = result["notes"]
        ai_uncertain = False

        # Second-pass AI qualification check — only worth the API call for
        # records that would otherwise still pass the keyword threshold.
        if new_rating >= config.MIN_RATING:
            qualifies, ai_reason, uncertain = qualification_checker.check_qualifies(
                config.ANTHROPIC_API_KEY, config.CANDIDATE_PROFILE, job.title, job.description,
                profile_data=config.PROFILE,
            )
            if not qualifies:
                ai_excluded_count += 1
                new_rating = 1
                new_notes = f"EXCLUDED (AI): {ai_reason}"
            else:
                new_notes = f"{new_notes} AI check: {ai_reason}"
                if uncertain:
                    ai_uncertain = True

        # A record can carry a stale Flag Category="AI Uncertain" from an
        # earlier run whose uncertain=True at the time. If THIS run resolves
        # it confidently — either the rater/AI now excludes it outright
        # (new_rating < MIN_RATING) or the AI check ran again and came back
        # confident (ai_uncertain False) — the flag needs clearing, otherwise
        # it sits in the dashboard forever looking unreviewed even though the
        # rating logic has already moved on. Found 12 Aug 2026: 6 records were
        # stuck exactly like this (rating 1, "EXCLUDED (AI)" notes, but still
        # flagged "AI Uncertain" from a prior pass).
        should_clear_stale_flag = (
            fields.get("Flag Category") == "AI Uncertain"
            and (new_rating < config.MIN_RATING or not ai_uncertain)
        )

        if new_rating != old_rating or description_changed or ai_uncertain or should_clear_stale_flag:
            changed_count += 1
            update_fields = {
                "Rating": new_rating,
                "Rating Notes": new_notes,
                "Seniority Match": "Yes" if result["seniority_match"] else "No",
            }
            if description_changed:
                update_fields["Description"] = description
            if ai_uncertain:
                update_fields["Flag Category"] = "AI Uncertain"
                update_fields["Flag Note"] = ai_reason
            elif should_clear_stale_flag:
                update_fields["Flag Category"] = ""
                update_fields["Flag Note"] = ""
            updates.append({"id": record["id"], "fields": update_fields})
            if old_rating is not None and old_rating >= config.MIN_RATING and new_rating < config.MIN_RATING:
                dropped_below_threshold.append((fields.get("Company", ""), job.title, old_rating, new_rating, new_notes))

        if (i + 1) % 25 == 0:
            print(f"  ...processed {i + 1}/{len(records)} (refetched {refetched_count} descriptions so far)")

    if not updates:
        print("No rating changes needed.")
        return

    print(f"Updating {len(updates)} records ({changed_count} rating changes, {ai_excluded_count} AI-excluded)...")
    update_records(updates)
    print("Done.\n")

    if dropped_below_threshold:
        print(f"{len(dropped_below_threshold)} record(s) dropped below MIN_RATING ({config.MIN_RATING}) — likely over-qualified:")
        for company, title, old_r, new_r, notes in dropped_below_threshold:
            print(f"  {company} — {title!r}: {old_r} -> {new_r}  ({notes})")


if __name__ == "__main__":
    main()
