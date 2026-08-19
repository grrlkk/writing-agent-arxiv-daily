#!/usr/bin/env python3
"""Fetch arXiv papers for writing-agent research topics and render README / archive.

Query arXiv per topic, keep only entries whose title+abstract actually contain a
configured phrase (the arXiv API's phrase search is loose), merge into a JSON
store so history accumulates, then regenerate the Markdown pages.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

import enrich as s2_enrich
import venues as venue_rules

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
GITHUB_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+")
VERSION_RE = re.compile(r"v\d+$")

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("daily_arxiv")


# --------------------------------------------------------------------------- config


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_blacklist(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(strip_version(line))
    return ids


# --------------------------------------------------------------------------- arxiv


def strip_version(arxiv_id: str) -> str:
    return VERSION_RE.sub("", arxiv_id.rsplit("/", 1)[-1])


def build_query(phrases: list[str], topic_cfg: dict, cfg: dict) -> str:
    fields = topic_cfg.get("search_fields") or cfg.get("search_fields") or ["ti", "abs"]
    terms = [f'{field}:"{phrase}"' for phrase in phrases for field in fields]
    query = "(" + " OR ".join(terms) + ")"
    categories = topic_cfg.get("categories") or cfg.get("categories")
    if categories:
        query += " AND (" + " OR ".join(f"cat:{c}" for c in categories) + ")"
    return query


def request_feed(query: str, start: int, page_size: int, retries: int, sleep: float) -> str:
    params = {
        "search_query": query,
        "start": start,
        "max_results": page_size,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, timeout=60, headers={"User-Agent": "writing-agent-arxiv-daily/1.0"})
            response.raise_for_status()
            return response.text
        except Exception as exc:  # network hiccups are routine against export.arxiv.org
            last_error = exc
            log.warning("arXiv request failed (attempt %d/%d): %s", attempt, retries, exc)
            time.sleep(sleep * attempt)
    raise RuntimeError(f"arXiv request failed after {retries} attempts") from last_error


def parse_entries(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    entries = []
    for node in root.findall(f"{ATOM}entry"):
        raw_id = (node.findtext(f"{ATOM}id") or "").strip()
        if not raw_id:
            continue
        versioned = raw_id.rsplit("/", 1)[-1]
        pdf_url = ""
        for link in node.findall(f"{ATOM}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
        summary = " ".join((node.findtext(f"{ATOM}summary") or "").split())
        comment = " ".join((node.findtext(f"{ARXIV_NS}comment") or "").split())
        journal_ref = " ".join((node.findtext(f"{ARXIV_NS}journal_ref") or "").split())
        primary = node.find(f"{ARXIV_NS}primary_category")
        entries.append(
            {
                "id": strip_version(versioned),
                "version": versioned,
                "title": " ".join((node.findtext(f"{ATOM}title") or "").split()),
                "authors": [
                    " ".join((a.findtext(f"{ATOM}name") or "").split())
                    for a in node.findall(f"{ATOM}author")
                ],
                "summary": summary,
                "comment": comment,
                "journal_ref": journal_ref,
                "published": (node.findtext(f"{ATOM}published") or "")[:10],
                "updated": (node.findtext(f"{ATOM}updated") or "")[:10],
                "primary_category": primary.get("term") if primary is not None else "",
                "abs_url": f"https://arxiv.org/abs/{strip_version(versioned)}",
                "pdf_url": pdf_url or f"https://arxiv.org/pdf/{strip_version(versioned)}",
                "code_url": find_code_url(f"{summary} {comment}"),
            }
        )
    return entries


def find_code_url(text: str) -> str:
    match = GITHUB_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,);:'\"").removesuffix(".git")


def fetch_topic(topic: str, topic_cfg: dict, cfg: dict) -> list[dict]:
    """Query the strong and weak phrase sets separately.

    A single merged query would let a high-frequency weak phrase ("faithfulness")
    fill the newest-N window and crowd out the rare strong phrases the topic
    actually exists for.
    """
    page_size = int(cfg.get("page_size", 100))
    wanted = int(
        cfg["max_results"]
        if cfg.get("_force_max_results")
        else (topic_cfg.get("max_results") or cfg.get("max_results", 100))
    )
    sleep = float(cfg.get("request_interval", 3.0))
    retries = int(cfg.get("retries", 3))

    groups = [("strong", topic_cfg.get("filters") or []), ("weak", topic_cfg.get("weak_filters") or [])]
    seen: dict[str, dict] = {}
    for label, phrases in groups:
        if not phrases:
            continue
        query = build_query(phrases, topic_cfg, cfg)
        start = 0
        got = 0
        while got < wanted:
            batch_size = min(page_size, wanted - got)
            log.info("[%s/%s] querying arXiv start=%d size=%d", topic, label, start, batch_size)
            entries = parse_entries(request_feed(query, start, batch_size, retries, sleep))
            for entry in entries:
                seen.setdefault(entry["id"], entry)
            got += len(entries)
            if len(entries) < batch_size:
                break
            start += batch_size
            time.sleep(sleep)
        time.sleep(sleep)
    return list(seen.values())


# --------------------------------------------------------------------------- filtering


def matched_filters(text: str, filters: list[str]) -> list[str]:
    return [phrase for phrase in filters if phrase.lower() in text]


def keep_entry(entry: dict, topic_cfg: dict, cfg: dict, blacklist: set[str]) -> tuple[bool, list[str]]:
    """Two-tier match.

    `filters` are phrases specific enough to qualify a paper on their own (they
    still have to clear the topic's `anchors`, if any). `weak_filters` are
    generic phrases — "corruption", "rubric", "tree search" — that qualify only
    when a `weak_anchors` term shows up too, which is what keeps the code-agent
    and medical-imaging literature out.
    """
    if entry["id"] in blacklist:
        return False, []
    text = f"{entry['title']} {entry['summary']}".lower()

    strong = matched_filters(text, topic_cfg.get("filters") or [])
    weak = matched_filters(text, topic_cfg.get("weak_filters") or [])
    hits = strong + weak
    if not hits:
        return False, []

    anchors = topic_cfg.get("anchors") or []
    strong_ok = bool(strong) and (not anchors or any(a.lower() in text for a in anchors))

    weak_anchors = topic_cfg.get("weak_anchors") or cfg.get("weak_anchors") or []
    weak_ok = bool(weak) and (not weak_anchors or any(a.lower() in text for a in weak_anchors))

    if not (strong_ok or weak_ok):
        return False, hits

    excluded = list(cfg.get("exclude_terms") or []) + list(topic_cfg.get("exclude_terms") or [])
    if any(term.lower() in text for term in excluded):
        return False, hits

    min_hits = int(topic_cfg.get("min_hits", cfg.get("min_hits", 1)))
    if len(hits) < min_hits:
        return False, hits
    return True, hits


# --------------------------------------------------------------------------- store


def load_store(path: Path) -> dict:
    if not path.exists():
        return {"topics": {}, "meta": {}}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("topics", {})
    data.setdefault("meta", {})
    return data


def save_store(path: Path, store: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


def merge_entries(store: dict, topic: str, entries: list[dict], today: str) -> list[dict]:
    bucket = store["topics"].setdefault(topic, {})
    fresh = []
    for entry in entries:
        existing = bucket.get(entry["id"])
        if existing is None:
            entry = dict(entry, first_seen=today)
            bucket[entry["id"]] = entry
            fresh.append(entry)
        else:
            entry = dict(entry, first_seen=existing.get("first_seen", today))
            bucket[entry["id"]] = entry
    return fresh


def sorted_entries(bucket: dict) -> list[dict]:
    return sorted(bucket.values(), key=lambda e: (e.get("published", ""), e.get("id", "")), reverse=True)


# --------------------------------------------------------------------------- rendering


def escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def format_authors(entry: dict, cfg: dict) -> str:
    authors = entry.get("authors") or []
    if not authors or not cfg.get("show_authors", True):
        return "-"
    first = escape_cell(authors[0])
    return f"{first} et al." if len(authors) > 1 else first


def format_row(entry: dict, cfg: dict) -> str:
    title = escape_cell(entry["title"])
    if cfg.get("show_abstract", True):
        abstract = escape_cell(entry.get("summary", ""))
        limit = int(cfg.get("abstract_max_chars", 700))
        if len(abstract) > limit:
            abstract = abstract[:limit].rstrip() + "..."
        title = (
            f"<details><summary>{title}</summary><br>{abstract}</details>"
            if abstract
            else title
        )
    code = f"**[link]({entry['code_url']})**" if entry.get("code_url") else "null"
    return (
        f"|**{entry.get('published', '')}**"
        f"|{title}"
        f"|{venue_rules.label(entry)}"
        f"|{format_authors(entry, cfg)}"
        f"|[{entry['id']}]({entry['abs_url']})"
        f"|{code}|"
    )


def anchor(text: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", text.lower()).strip().replace(" ", "-")
    return slug


def render_table(entries: list[dict], cfg: dict) -> list[str]:
    lines = ["|Publish Date|Title|Venue|Authors|PDF|Code|", "|---|---|---|---|---|---|"]
    lines.extend(format_row(entry, cfg) for entry in entries)
    return lines


def render_page(store: dict, cfg: dict, today: str, *, limit: int | None, header: str, new_today: dict[str, list[dict]] | None) -> str:
    topics = [t for t in cfg["keywords"] if store["topics"].get(t)]
    out: list[str] = [header.rstrip().format(today=today), ""]

    out.append("## Contents")
    out.append("")
    for topic in topics:
        count = len(store["topics"][topic])
        out.append(f"- [{topic}](#{anchor(topic)}) ({count})")
    out.append("")

    if new_today:
        total_new = sum(len(v) for v in new_today.values())
        out.append(f"## New in this update ({total_new})")
        out.append("")
        if total_new:
            for topic, entries in new_today.items():
                for entry in entries:
                    out.append(
                        f"- `{topic}` [{escape_cell(entry['title'])}]({entry['abs_url']})"
                    )
        else:
            out.append("_No new papers matched today._")
        out.append("")

    for topic in topics:
        entries = sorted_entries(store["topics"][topic])
        shown = entries[:limit] if limit else entries
        out.append(f"## {topic}")
        out.append("")
        description = cfg["keywords"][topic].get("description")
        if description:
            out.append(f"> {description}")
            out.append("")
        if limit and len(entries) > limit:
            out.append(
                f"_Showing the {limit} most recent of {len(entries)} papers — "
                f"see [the full archive](docs/archive.md)._"
            )
            out.append("")
        out.extend(render_table(shown, cfg))
        out.append("")
        out.append(f"<p align=right>(<a href=#contents>back to top</a>)</p>")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


README_HEADER = """# Writing Agent arXiv Daily

Automatically updated arXiv tracker for **writing agent** research — the literature
axis behind FEAK-TC (transition-level, value-guided revision control for Korean writing).

> Last updated: **{today}** (UTC) · [Papers by venue](docs/venues.md) · [Topics and research-axis mapping](KEYWORDS.md) · [Full archive](docs/archive.md)

Run it yourself: `pip install -r requirements.txt && python daily_arxiv.py`
"""

ARCHIVE_HEADER = """# Full archive

Every paper ever matched, newest first. Generated on **{today}** (UTC).
Back to the [main page](../README.md).
"""


VENUE_HEADER = """# Papers by venue

Venue comes from three sources, in order of how much each can be trusted: the
arXiv `journal_ref` field, the Semantic Scholar record for the paper, and the
acceptance line authors write in the arXiv comment.

A paper missing here is **not** evidence that it was never published — most of
this collection is preprints posted within the last few months, which have not
reached a venue yet. Those are re-checked monthly, so this page fills in over time.

Workshop, Findings, and demo tracks are listed apart from main-track papers, and
"submitted to X" is never counted as X. Generated on **{today}** (UTC).
Back to the [main page](../README.md).
"""

TIER_TITLES = {
    "top": "Top-tier venues",
    "strong": "Strong venues",
    "findings": "Findings tracks",
    "other": "Other venues",
    "workshop": "Workshops",
    "demo": "Demo tracks",
}


def render_venue_page(store: dict, cfg: dict, today: str, tier_counts: dict[str, int]) -> str:
    unique: dict[str, dict] = {}
    topics_of: dict[str, list[str]] = {}
    for topic, bucket in store.get("topics", {}).items():
        for entry in bucket.values():
            unique[entry["id"]] = entry
            topics_of.setdefault(entry["id"], []).append(topic)

    out = [VENUE_HEADER.format(today=today).rstrip(), ""]
    classified = sum(v for k, v in tier_counts.items() if k != "none")
    out.append(f"{classified} of {len(unique)} papers carry venue evidence.")
    out.append("")

    for tier, title in TIER_TITLES.items():
        entries = [e for e in unique.values() if e.get("tier") == tier and e.get("status") == "accepted"]
        if not entries:
            continue
        out.append(f"## {title} ({len(entries)})")
        out.append("")
        by_venue: dict[str, list[dict]] = {}
        for entry in entries:
            by_venue.setdefault(entry["venue"], []).append(entry)
        for venue in sorted(by_venue, key=lambda v: (-len(by_venue[v]), v)):
            rows = sorted(by_venue[venue], key=lambda e: e.get("published", ""), reverse=True)
            out.append(f"### {venue} ({len(rows)})")
            out.append("")
            out.append("|Publish Date|Title|Venue|Topics|PDF|")
            out.append("|---|---|---|---|---|")
            for entry in rows:
                out.append(
                    f"|**{entry.get('published', '')}**"
                    f"|{escape_cell(entry['title'])}"
                    f"|{venue_rules.label(entry)}"
                    f"|{', '.join(topics_of[entry['id']])}"
                    f"|[{entry['id']}]({entry['abs_url']})|"
                )
            out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--topics", nargs="*", help="only run these topics")
    parser.add_argument("--max-results", type=int, help="override max_results per topic")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    parser.add_argument("--offline", action="store_true", help="re-render pages from the stored JSON only")
    parser.add_argument("--enrich", dest="enrich", action="store_true", default=None,
                        help="look venues up on Semantic Scholar (default: config s2_enabled)")
    parser.add_argument("--no-enrich", dest="enrich", action="store_false",
                        help="skip the Semantic Scholar lookup")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = load_config(Path(args.config))
    if args.max_results:
        cfg["max_results"] = args.max_results
        cfg["_force_max_results"] = True  # CLI wins over per-topic max_results

    store_path = ROOT / cfg.get("store_path", "docs/papers.json")
    store = load_store(store_path)
    blacklist = load_blacklist(ROOT / cfg.get("blacklist_path", "blacklist.txt"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    new_today: dict[str, list[dict]] = {}
    if not args.offline:
        topics = args.topics or list(cfg["keywords"])
        for topic in topics:
            topic_cfg = cfg["keywords"].get(topic)
            if topic_cfg is None:
                log.error("unknown topic: %s", topic)
                continue
            raw = fetch_topic(topic, topic_cfg, cfg)
            kept = []
            for entry in raw:
                ok, hits = keep_entry(entry, topic_cfg, cfg, blacklist)
                if ok:
                    kept.append(dict(entry, matched=hits))
            log.info("[%s] fetched %d, kept %d", topic, len(raw), len(kept))
            if not args.dry_run:
                fresh = merge_entries(store, topic, kept, today)
                if fresh:
                    new_today[topic] = fresh
                log.info("[%s] %d new", topic, len(fresh))
            time.sleep(float(cfg.get("request_interval", 3.0)))

    if args.dry_run:
        log.info("dry run — nothing written")
        return 0

    enrich_enabled = cfg.get("s2_enabled", True) if args.enrich is None else args.enrich
    if enrich_enabled:
        stats = s2_enrich.enrich_store(store, cfg)
        log.info("semantic scholar: %s", ", ".join(f"{k}={v}" for k, v in stats.items()))

    # Re-classified on every run, so editing venues.yaml takes effect with --offline.
    rules = venue_rules.load_rules(ROOT / cfg.get("venues_path", "venues.yaml"))
    tier_counts = venue_rules.annotate_store(store, rules)
    log.info("venues: %s", ", ".join(f"{k}={v}" for k, v in sorted(tier_counts.items())))

    store["meta"] = {
        "updated": today,
        "topics": {t: len(b) for t, b in store["topics"].items()},
        "venue_tiers": tier_counts,
    }
    save_store(store_path, store)

    readme = render_page(
        store,
        cfg,
        today,
        limit=int(cfg.get("readme_max_per_topic", 30)),
        header=README_HEADER,
        new_today=new_today if not args.offline else None,
    )
    (ROOT / cfg.get("readme_path", "README.md")).write_text(readme, encoding="utf-8")

    archive = render_page(store, cfg, today, limit=None, header=ARCHIVE_HEADER, new_today=None)
    archive_path = ROOT / cfg.get("archive_path", "docs/archive.md")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(archive.replace("docs/archive.md", "archive.md"), encoding="utf-8")

    venue_page = render_venue_page(store, cfg, today, tier_counts)
    venue_path = ROOT / cfg.get("venue_page_path", "docs/venues.md")
    venue_path.write_text(venue_page, encoding="utf-8")

    total = sum(len(b) for b in store["topics"].values())
    log.info("done — %d papers across %d topics", total, len(store["topics"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
