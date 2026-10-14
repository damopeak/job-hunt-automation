"""
One-off backfill: fetches the real posting date for existing Adzuna records
that are missing "Date Posted" (root cause: Airtable's Date field silently
rejected Adzuna's raw timestamp format — fixed in scrapers/adzuna.py, but
that only affects future scrapes, not rows already in Airtable).

Adzuna's own job pages embed the true date as schema.org JSON-LD
("datePosted"), already at midnight UTC — exactly the format Airtable's
Date Posted field accepts. For each affected record: fetch its stored URL,
extract datePosted, and PATCH it in. If the page is gone/unreachable or has
no datePosted (listing expired, URL dead), DELETE the record instead — per
user instruction: a job with no verifiable posted date shouldn't be sitting
in the tracker at all.
"""

import re
import sys
import time

import requests

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {"Authorization": f"Bearer {config.AIRTABLE_TOKEN}", "Content-Type": "application/json"}
BASE_URL = f"https://api.airtable.com/v0/{config.AIRTABLE_BASE_ID}/{config.AIRTABLE_TABLE_NAME}"
PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
DATE_POSTED_REGEX = re.compile(r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})')


def fetch_adzuna_missing_dates() -> list:
    records = []
    offset = None
    while True:
        params = {"pageSize": 100, "filterByFormula": "AND({Source}='Adzuna', {Date Posted}='')"}
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


class FetchResult:
    """status: 'ok' (got a date), 'gone' (404/410 — listing genuinely removed,
    safe to delete), or 'blocked' (anything else — request failed for a reason
    unrelated to the listing's existence, e.g. 403/timeout; NOT safe to delete,
    since that would destroy a record over a fetch limitation, not a real
    'no date available' case)."""

    def __init__(self, status: str, date_posted: str = ""):
        self.status = status
        self.date_posted = date_posted


def get_date_posted(url: str) -> "FetchResult":
    try:
        resp = requests.get(url, headers=PAGE_HEADERS, timeout=15)
    except Exception:
        return FetchResult("blocked")

    if resp.status_code in (404, 410):
        return FetchResult("gone")
    if resp.status_code != 200:
        return FetchResult("blocked")

    m = DATE_POSTED_REGEX.search(resp.text)
    if m:
        return FetchResult("ok", m.group(1))
    # 200 but no JSON-LD date found — page loaded but didn't have the data;
    # treat as blocked/unverifiable rather than gone, since the listing itself
    # clearly still exists (200, not 404/410).
    return FetchResult("blocked")


def batch_delete(record_ids: list):
    for i in range(0, len(record_ids), 10):
        batch = record_ids[i:i + 10]
        params = [("records[]", rid) for rid in batch]
        resp = requests.delete(BASE_URL, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        time.sleep(0.25)


def batch_update(updates: list):
    for i in range(0, len(updates), 10):
        batch = updates[i:i + 10]
        resp = requests.patch(BASE_URL, headers=HEADERS, json={"records": batch}, timeout=15)
        resp.raise_for_status()
        time.sleep(0.25)


def main():
    print("Fetching Adzuna records missing Date Posted...")
    records = fetch_adzuna_missing_dates()
    print(f"Found {len(records)} records.\n")

    updates = []
    to_delete = []
    blocked = []  # ambiguous — not deleted, reported separately

    for i, record in enumerate(records):
        url = record["fields"].get("URL", "")
        result = get_date_posted(url) if url else FetchResult("blocked")
        if result.status == "ok":
            updates.append({"id": record["id"], "fields": {"Date Posted": result.date_posted}})
        elif result.status == "gone":
            to_delete.append(record["id"])
        else:
            blocked.append((record["id"], record["fields"].get("Job Title", ""), url))
        time.sleep(0.3)  # be polite to Adzuna's site

        if (i + 1) % 25 == 0:
            print(f"  ...processed {i + 1}/{len(records)} (backfilled {len(updates)}, gone {len(to_delete)}, blocked {len(blocked)})")

    print(f"\nBackfilling {len(updates)} records with real dates...")
    if updates:
        batch_update(updates)
    print(f"Deleting {len(to_delete)} records confirmed gone (404/410)...")
    if to_delete:
        batch_delete(to_delete)

    print("\nDone.")
    print(f"Backfilled: {len(updates)}")
    print(f"Deleted (confirmed gone, 404/410): {len(to_delete)}")
    print(f"Blocked/unverifiable (left untouched — not deleted): {len(blocked)}")
    if blocked:
        print("\nBlocked/unverifiable records (review manually):")
        for rid, title, url in blocked:
            print(f"  {rid} | {title} | {url}")


if __name__ == "__main__":
    main()
