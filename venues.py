"""Classify an arXiv entry by publication venue, from its own metadata.

arXiv has no venue field. What it has is `journal_ref` (rare, reliable) and the
free-text `comment` authors write, which is where "Accepted to ACL 2025" lives.
This module reads both and decides three things separately:

    status  accepted / submitted / unknown   — "Submitted to EACL 2026" is not an EACL paper
    track   main / findings / demo / workshop — an ICLR workshop is not ICLR
    tier    top / strong / other / none       — the venue table's tier, downgraded by the two above

Nothing here queries the network, so it re-runs for free on every render: edit
venues.yaml, run `python daily_arxiv.py --offline`, and every stored paper is
re-classified.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

# "Submitted to X" / "under review at X" means the paper is not published there.
NEGATIVE_STATUS = re.compile(
    r"\b(submitted to|submitted for|under review|in submission|under submission)\b", re.I
)
POSITIVE_STATUS = re.compile(
    r"\b(accepted|to appear|camera[- ]?ready|published|proceedings|appears? in|presented at|"
    r"in the proceedings|forthcoming)\b",
    re.I,
)
WORKSHOP = re.compile(r"\bworkshops?\b|\bSemEval\b|\bshared task\b|@\s*[A-Z]{2,}", re.I)
# "ACL style", "NeurIPS format" — the venue is named as a template, not a publication.
MENTION_ONLY = re.compile(r"\b(style|template|format(ting)?|guidelines?)\b", re.I)
FINDINGS = re.compile(r"\bfindings\b", re.I)
DEMO = re.compile(r"\b(demo|demonstration|system demonstrations?)\b", re.I)
# No word boundary in front: authors write "AAAI2026" and "BEA2025" with no space.
YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
# Two-digit conference shorthand: UIST '26, CHI '25.
SHORT_YEAR = re.compile(r"['\u2019](\d{2})(?!\d)")

# Findings and workshop/demo tracks are real publications but not the main track,
# so they get their own tier instead of inheriting the venue's.
TRACK_TIER_OVERRIDE = {"workshop": "workshop", "demo": "demo", "findings": "findings"}


def load_rules(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    rules = []
    for venue in data["venues"]:
        rules.append(
            {
                "name": venue["name"],
                "tier": venue.get("tier", "other"),
                "patterns": [re.compile(p, re.I) for p in venue["patterns"]],
            }
        )
    return rules


def _match_venue(text: str, rules: list[dict]) -> tuple[dict | None, re.Match | None]:
    for rule in rules:
        for pattern in rule["patterns"]:
            found = pattern.search(text)
            if found:
                return rule, found
    return None, None


def _year_near(text: str, match: re.Match | None) -> str:
    """Prefer a year sitting next to the venue mention over any year in the string."""
    if match is not None:
        window = text[max(0, match.start() - 20) : match.end() + 20]
        near = YEAR.search(window)
        if near:
            return near.group(1)
        short = SHORT_YEAR.search(window)
        if short:
            return f"20{short.group(1)}"
    any_year = YEAR.search(text)
    if any_year:
        return any_year.group(1)
    short = SHORT_YEAR.search(text)
    return f"20{short.group(1)}" if short else ""


def classify(entry: dict, rules: list[dict]) -> dict:
    """Return venue fields for one entry. Empty venue means 'no evidence', not 'unpublished'."""
    blank = {
        "venue": "",
        "venue_year": "",
        "track": "",
        "tier": "none",
        "status": "unknown",
        "venue_evidence": "",
        "venue_source": "",
    }

    # Ordered by how much each source can be trusted: journal_ref is set by the
    # author on publication, Semantic Scholar is an indexed record, and the
    # comment is free text that may describe an intention rather than a fact.
    sources = [
        ("journal_ref", (entry.get("journal_ref") or "").strip()),
        ("s2", ((entry.get("s2") or {}).get("venue") or "").strip()),
        ("comment", (entry.get("comment") or "").strip()),
    ]
    for source, text in sources:
        if not text:
            continue
        rule, match = _match_venue(text, rules)
        if rule is None:
            continue

        if NEGATIVE_STATUS.search(text):
            # e.g. "Submitted to EACL 2026 Demo Track" — record the intent, claim nothing
            return {
                "venue": rule["name"],
                "venue_year": _year_near(text, match),
                "track": "",
                "tier": "none",
                "status": "submitted",
                "venue_evidence": text[:160],
                "venue_source": source,
            }

        # The venue name comes from the trusted source, but the track has to be
        # read across all of them: Semantic Scholar files a Findings paper under
        # the parent conference, and only the author's comment says "Findings".
        # Where sources disagree, the more specific (and more conservative)
        # reading wins - a workshop paper must never be counted as main track.
        combined = " ".join(t for _, t in sources if t)
        if WORKSHOP.search(combined):
            track = "workshop"
        elif FINDINGS.search(combined):
            track = "findings"
        elif DEMO.search(combined):
            track = "demo"
        else:
            track = "main"

        # Accepting needs evidence: a journal_ref at all, an explicit acceptance
        # phrase, or a year next to the venue ("EMNLP 2025"). A bare mention with
        # none of those - "written in ACL style" - is recorded but not claimed.
        year = _year_near(text, match)
        if not year and source == "s2":
            year = str((entry.get("s2") or {}).get("year") or "")
        # An indexed venue record is itself the evidence; free text needs more.
        accepted = source in ("journal_ref", "s2") or bool(POSITIVE_STATUS.search(text)) or bool(year)
        if MENTION_ONLY.search(text) and not POSITIVE_STATUS.search(text):
            accepted = False

        if not accepted:
            return {
                "venue": rule["name"],
                "venue_year": year,
                "track": "",
                "tier": "none",
                "status": "mentioned",
                "venue_evidence": text[:160],
                "venue_source": source,
            }

        tier = TRACK_TIER_OVERRIDE.get(track, rule["tier"])

        return {
            "venue": rule["name"],
            "venue_year": year,
            "track": track,
            "tier": tier,
            "status": "accepted",
            "venue_evidence": text[:160],
            "venue_source": source,
        }

    return blank


def label(entry: dict) -> str:
    """Short human-readable venue label for a table cell."""
    venue = entry.get("venue")
    if not venue:
        return "-"
    year = entry.get("venue_year", "")
    name = f"{venue} {year}".strip()
    status = entry.get("status")
    track = entry.get("track")
    if status in ("submitted", "mentioned"):
        return f"{name} ({status})"
    if track and track != "main":
        return f"{name} ({track})"
    return name


def annotate_store(store: dict, rules: list[dict]) -> dict[str, int]:
    """Classify every stored entry in place; return a tier histogram of unique papers."""
    seen: dict[str, str] = {}
    for bucket in store.get("topics", {}).values():
        for entry in bucket.values():
            entry.update(classify(entry, rules))
            seen[entry["id"]] = entry["tier"]
    counts: dict[str, int] = {}
    for tier in seen.values():
        counts[tier] = counts.get(tier, 0) + 1
    return counts
