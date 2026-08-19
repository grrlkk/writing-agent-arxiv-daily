"""Look up publication venues on Semantic Scholar for papers arXiv says nothing about.

Most arXiv entries never get an acceptance line in their comment, so metadata
alone leaves ~85% of a collection unclassified. Semantic Scholar knows where a
paper actually appeared and answers by arXiv id, with no API key required.

Results are cached on each entry (`s2` field in papers.json), so a run only
queries papers it has never looked up - plus recent ones whose lookup came back
empty, since a preprint from last month may be published next month.

Failure here is never fatal: the tracker falls back to arXiv metadata alone.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta

import requests

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "title,venue,year,publicationVenue,publicationTypes,externalIds"

# Semantic Scholar records unpublished preprints with these as the "venue".
# Counting them would turn every arXiv paper into a published one.
NON_VENUES = {
    "arxiv.org",
    "arxiv",
    "corr",
    "ssrn",
    "biorxiv",
    "medrxiv",
    "chemrxiv",
    "openreview",
    "research square",
    "preprints.org",
}

log = logging.getLogger("daily_arxiv.enrich")


def _needs_lookup(entry: dict, recheck_days: int, today: date) -> bool:
    cached = entry.get("s2")
    if not cached:
        return True
    if cached.get("venue"):
        return False  # a venue never changes once assigned
    checked = cached.get("checked")
    if not checked:
        return True
    try:
        last = datetime.strptime(checked, "%Y-%m-%d").date()
    except ValueError:
        return True
    # Empty answers get retried: today's preprint is next year's ACL paper.
    return today - last >= timedelta(days=recheck_days)


def _post_batch(ids: list[str], timeout: float, retries: int, interval: float) -> list | None:
    headers = {"Content-Type": "application/json", "User-Agent": "writing-agent-arxiv-daily/1.0"}
    api_key = os.environ.get("S2_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(
                S2_BATCH_URL,
                params={"fields": S2_FIELDS},
                json={"ids": ids},
                headers=headers,
                timeout=timeout,
            )
            if response.status_code == 429:
                wait = interval * (2**attempt)
                log.warning("semantic scholar rate limited, waiting %.0fs", wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            log.warning("semantic scholar batch failed (attempt %d/%d): %s", attempt, retries, exc)
            time.sleep(interval * attempt)
    return None


def clean_venue(record: dict | None) -> str:
    """Venue name from an S2 record, or "" when it is a preprint server or missing."""
    if not record:
        return ""
    venue = (record.get("venue") or "").strip()
    published = record.get("publicationVenue") or {}
    if not venue:
        venue = (published.get("name") or "").strip()
    if venue.lower() in NON_VENUES:
        return ""
    return venue


def enrich_store(store: dict, cfg: dict) -> dict[str, int]:
    """Fill in `s2` for stored papers that need it. Returns counts for logging."""
    today = date.today()
    recheck_days = int(cfg.get("s2_recheck_days", 30))
    batch_size = int(cfg.get("s2_batch_size", 100))
    interval = float(cfg.get("s2_interval", 3.0))
    max_requests = int(cfg.get("s2_max_requests", 40))
    timeout = float(cfg.get("s2_timeout", 60))
    retries = int(cfg.get("s2_retries", 3))

    # One lookup per paper, then copy the answer to every topic holding it.
    unique: dict[str, list[dict]] = {}
    for bucket in store.get("topics", {}).values():
        for entry in bucket.values():
            unique.setdefault(entry["id"], []).append(entry)

    pending = [pid for pid, copies in unique.items() if _needs_lookup(copies[0], recheck_days, today)]
    stats = {"looked_up": 0, "with_venue": 0, "not_found": 0, "skipped": len(unique) - len(pending)}
    if not pending:
        return stats

    log.info("semantic scholar: %d papers to look up", len(pending))
    stamp = today.strftime("%Y-%m-%d")
    requests_made = 0

    for start in range(0, len(pending), batch_size):
        if requests_made >= max_requests:
            log.warning("semantic scholar: hit the %d request cap, rest waits for tomorrow", max_requests)
            break
        chunk = pending[start : start + batch_size]
        records = _post_batch([f"ARXIV:{pid}" for pid in chunk], timeout, retries, interval)
        requests_made += 1
        if records is None:
            log.warning("semantic scholar: giving up on this batch, keeping arXiv metadata only")
            break

        for pid, record in zip(chunk, records):
            venue = clean_venue(record)
            payload = {
                "venue": venue,
                "year": (record or {}).get("year") or "",
                "types": (record or {}).get("publicationTypes") or [],
                "checked": stamp,
            }
            for entry in unique[pid]:
                entry["s2"] = payload
            stats["looked_up"] += 1
            if venue:
                stats["with_venue"] += 1
            elif record is None:
                stats["not_found"] += 1

        time.sleep(interval)

    return stats
