"""Checks for venue classification. Run: python test_venues.py

The cases below are real arXiv comment strings pulled from the collected set,
plus the traps that make naive keyword matching wrong.
"""
import sys

from venues import classify, label, load_rules

RULES = load_rules("venues.yaml")

# comment text -> (venue, track, tier, status)
CASES = [
    # plain acceptances
    ("Accepted by AAAI2026", ("AAAI", "main", "top", "accepted")),
    ("Accepted to ACL 2025 main conference", ("ACL", "main", "top", "accepted")),
    ("In The Conference on Empirical Methods in Natural Language Processing (EMNLP), November 2025",
     ("EMNLP", "main", "top", "accepted")),
    ("Paper was accepted by Interspeech 2026", ("Interspeech", "main", "other", "accepted")),

    # a workshop is not the conference
    ("31 pages, Presented at the ICLR 2026 Workshop on AI and Partial Differential Equations",
     ("ICLR", "workshop", "workshop", "accepted")),
    ("Accepted to NSLP@LREC", ("LREC", "workshop", "workshop", "accepted")),

    # findings and demo tracks are marked, not hidden
    ("Accepted to Findings of EMNLP 2025", ("EMNLP", "findings", "findings", "accepted")),
    ("Accepted at ACL 2025 System Demonstrations", ("ACL", "demo", "demo", "accepted")),

    # not published there
    ("Submitted to EACL 2026 Demo Track", ("EACL", "", "none", "submitted")),
    ("Under review at NeurIPS 2026", ("NeurIPS", "", "none", "submitted")),

    # named as a template, not a venue
    ("9 pages, written in ACL style template", ("ACL", "", "none", "mentioned")),

    # the specific name must win over the substring
    ("Accepted at NAACL 2026", ("NAACL", "main", "top", "accepted")),
    ("Accepted at EACL 2026", ("EACL", "main", "top", "accepted")),
    ("To appear in TACL", ("TACL", "main", "top", "accepted")),

    # year glued to the venue name, and two-digit shorthand
    ("BEA2025", ("BEA", "main", "strong", "accepted")),
    ("Accepted by AAAI2026, 9 pages", ("AAAI", "main", "top", "accepted")),
    ("11 pages, The 39th Annual ACM Symposium on User Interface Software and Technology (UIST '26)",
     ("UIST", "main", "top", "accepted")),

    # nothing to go on
    ("10 pages, 4 figures", ("", "", "none", "unknown")),
    ("Code available at https://github.com/foo/bar", ("", "", "none", "unknown")),
]


S2_CASES = [
    # an indexed venue record is evidence on its own, no acceptance phrase needed
    ({"s2": {"venue": "Neural Information Processing Systems", "year": 2022}},
     ("NeurIPS", "main", "top", "accepted")),
    ({"s2": {"venue": "Annual Meeting of the Association for Computational Linguistics", "year": 2024}},
     ("ACL", "main", "top", "accepted")),
    # findings and workshops keep their own tier when they come from S2 too
    ({"s2": {"venue": "Findings of the Association for Computational Linguistics: EMNLP 2023", "year": 2023}},
     ("EMNLP", "findings", "findings", "accepted")),
    # S2 files unpublished preprints under the preprint server - not a venue
    ({"s2": {"venue": "", "year": 2025}}, ("", "", "none", "unknown")),
    # arXiv's own journal_ref still outranks S2
    ({"journal_ref": "Proceedings of ICLR 2025", "s2": {"venue": "Neural Information Processing Systems", "year": 2022}},
     ("ICLR", "main", "top", "accepted")),
    # S2 outranks a comment that only states an intention
    ({"comment": "Submitted to ACL 2025", "s2": {"venue": "Conference on Empirical Methods in Natural Language Processing", "year": 2025}},
     ("EMNLP", "main", "top", "accepted")),
]


def run() -> int:
    failures = 0
    for comment, (venue, track, tier, status) in CASES:
        got = classify({"comment": comment}, RULES)
        actual = (got["venue"], got["track"], got["tier"], got["status"])
        if actual != (venue, track, tier, status):
            failures += 1
            print(f"FAIL {comment[:60]!r}\n  expected {(venue, track, tier, status)}\n  got      {actual}")
    for entry, expected in S2_CASES:
        got = classify(entry, RULES)
        actual = (got["venue"], got["track"], got["tier"], got["status"])
        if actual != expected:
            failures += 1
            print(f"FAIL s2 case {entry}\n  expected {expected}\n  got      {actual}")

    # journal_ref outranks comment
    entry = {"comment": "Submitted to ACL 2025", "journal_ref": "Proceedings of NAACL 2026, pages 1-10"}
    got = classify(entry, RULES)
    if got["venue"] != "NAACL" or got["status"] != "accepted":
        failures += 1
        print(f"FAIL journal_ref should outrank comment, got {got}")
    if label({"venue": "EMNLP", "venue_year": "2025", "track": "findings", "status": "accepted"}) != "EMNLP 2025 (findings)":
        failures += 1
        print("FAIL label formatting")

    total = len(CASES) + len(S2_CASES) + 2
    print(f"{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
