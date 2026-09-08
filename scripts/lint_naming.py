#!/usr/bin/env python3
"""Guardrail linter for the mandatory naming rule (spec 1, 14.1).

Two vocabularies must never mix:

    scientific track   Foundation / Core / Advanced
    commercial tier    Basic / Moderate / Expert

This script fails when a tier word appears in a scientific-track context, when a
track word appears in a commercial context, and when a scientific threshold is
hard-coded outside the parameter registry (spec 14.3). Run it in CI before merge.

Usage:  python scripts/lint_naming.py [paths...]
"""

import argparse
import os
import re
import sys
from typing import Iterable, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TIER_WORDS = r"(?:basic|moderate|expert)"
TRACK_WORDS = r"(?:foundation|core|advanced)"

#: A tier word used where a scientific track belongs.
TIER_IN_SCIENCE = [
    re.compile(rf"\b{TIER_WORDS}[_\- ](?:track|pipeline|analysis|workflow)\b", re.I),
    re.compile(rf"\b(?:track|pipeline|analysis|assay)\s*[:=]\s*[\"']{TIER_WORDS}[\"']", re.I),
    re.compile(rf"AnalysisTrack\.{TIER_WORDS.upper()}", re.I),
]

#: A track word used where a commercial permission belongs.
TRACK_IN_COMMERCE = [
    re.compile(rf"\b{TRACK_WORDS}[_\- ](?:tier|plan|subscription|entitlement|price|pricing)\b", re.I),
    re.compile(rf"\b(?:tier|plan|entitlement)\s*[:=]\s*[\"']{TRACK_WORDS}[\"']", re.I),
    re.compile(rf"AccessTier\.{TRACK_WORDS.upper()}", re.I),
    re.compile(rf"\bupgrade to {TRACK_WORDS}\b", re.I),
]

#: Scientific thresholds that belong in the parameter registry (spec 14.3).
THRESHOLD_NAMES = re.compile(
    r"\b(?:fdr|padj|pvalue_cutoff|p_value_cutoff|resolution|n_top_genes|n_neighbors|"
    r"n_comps|min_genes|max_genes|min_counts|max_counts|max_mito|mito_pct|"
    r"min_cells|min_samples|min_gene_set_size)\b\s*=\s*(?!None)[\d.]",
    re.I,
)

SKIP_DIRECTORIES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".pytest_cache",
}
SCANNED_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".sql", ".html"}

#: Files allowed to declare the vocabularies and the registry itself.
ALLOWLIST = {
    os.path.join("backend", "app", "constants.py"),
    os.path.join("backend", "app", "core", "parameters.py"),
    os.path.join("scripts", "lint_naming.py"),
    os.path.join("docs", "naming-rule.md"),
    # Contains deliberate violations as linter fixtures.
    os.path.join("backend", "tests", "test_guardrails.py"),
}


class Finding(Tuple):
    pass


def iter_files(paths: Iterable[str]) -> Iterable[str]:
    for path in paths:
        if os.path.isfile(path):
            yield path
            continue
        for directory, subdirectories, filenames in os.walk(path):
            subdirectories[:] = [d for d in subdirectories if d not in SKIP_DIRECTORIES]
            for filename in filenames:
                if os.path.splitext(filename)[1] in SCANNED_EXTENSIONS:
                    yield os.path.join(directory, filename)


def relative(path: str) -> str:
    return os.path.relpath(os.path.abspath(path), ROOT)


def scan(paths: List[str]) -> List[tuple]:
    findings = []
    for path in iter_files(paths):
        rel = relative(path)
        if rel in ALLOWLIST:
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, start=1):
            for pattern in TIER_IN_SCIENCE:
                if pattern.search(line):
                    findings.append(
                        (
                            rel,
                            number,
                            "tier_word_in_scientific_context",
                            "A commercial tier name is being used to label a "
                            "scientific analysis track.",
                            line.strip(),
                        )
                    )
            for pattern in TRACK_IN_COMMERCE:
                if pattern.search(line):
                    findings.append(
                        (
                            rel,
                            number,
                            "track_word_in_commercial_context",
                            "A scientific track name is being used to label a "
                            "commercial permission.",
                            line.strip(),
                        )
                    )
            if THRESHOLD_NAMES.search(line) and "parameters.get" not in line:
                findings.append(
                    (
                        rel,
                        number,
                        "hardcoded_scientific_threshold",
                        "A scientific threshold is assigned outside the parameter "
                        "registry. Declare it in app/core/parameters.py instead.",
                        line.strip(),
                    )
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=None)
    arguments = parser.parse_args()
    paths = arguments.paths or [
        os.path.join(ROOT, "backend"),
        os.path.join(ROOT, "frontend", "src"),
        os.path.join(ROOT, "scripts"),
    ]

    findings = scan(paths)
    if not findings:
        print("Naming rule and parameter registry guardrails: clean.")
        return 0

    print(f"{len(findings)} guardrail violation(s):\n")
    for path, number, code, message, snippet in findings:
        print(f"  {path}:{number}  [{code}]\n    {message}\n    {snippet}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
