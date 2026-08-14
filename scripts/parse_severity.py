#!/usr/bin/env python3
"""
Sum severity counts and asset (host) counts out of Tenable scan-results text.

Works on either:
  - the full raw scan_results markdown/text for a single history run, or
  - a file containing only the pre-extracted matching lines (useful when the
    full results file is too large to Read directly and you pulled out just
    the relevant lines with Grep -o first).

Usage:
    python3 parse_severity.py <path-to-file>

Prints JSON:
    {
      "totals": {"critical": N, "high": N, "medium": N, "low": N, "info": N},
      "host_count": N,              # number of per-host "Vulns: [...]" lines found
      "declared_host_count": N|null # value from a "**Host Count:** N" header, if present
    }

Why this exists: these results can list hundreds of hosts, and hand-summing
per-host severity counts (by eye or by having a model add them up) is exactly
the kind of arithmetic that quietly goes wrong at scale. Always run the
numbers through here rather than eyeballing the text.
"""
import json
import re
import sys


PER_HOST_RE = re.compile(
    r"Vulns:\s*\[Crit:\s*(\d+)\s*\|\s*High:\s*(\d+)\s*\|\s*Med:\s*(\d+)\s*\|\s*Low:\s*(\d+)\]"
)
INFO_RE = re.compile(r"\(Sev:\s*0\).{0,80}?Count:\s*(\d+)", re.DOTALL)
DECLARED_HOST_COUNT_RE = re.compile(r"\*\*Host Count:\*\*\s*(\d+)")


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 parse_severity.py <path-to-file>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "r", errors="ignore") as f:
        text = f.read()

    totals = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    host_count = 0

    for m in PER_HOST_RE.finditer(text):
        crit, high, med, low = (int(x) for x in m.groups())
        totals["critical"] += crit
        totals["high"] += high
        totals["medium"] += med
        totals["low"] += low
        host_count += 1

    for m in INFO_RE.finditer(text):
        totals["info"] += int(m.group(1))

    declared_match = DECLARED_HOST_COUNT_RE.search(text)
    declared_host_count = int(declared_match.group(1)) if declared_match else None

    result = {
        "totals": totals,
        "host_count": host_count,
        "declared_host_count": declared_host_count,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
