# Tenable Scan Status Calendar

A Claude Code / Claude Cowork skill that puts your upcoming Tenable Vulnerability Management (VM) scan jobs on Google Calendar — and flags any scan whose most recent run aborted or failed, so broken scan configs get noticed instead of quietly re-running unattended.

## What it does

For every Tenable VM scan with an active recurring schedule due to fire in the next 7 days, the skill creates one Google Calendar event. Each event's description includes:

- When the scan is projected to run (inferred from recent run history, since Tenable's API doesn't expose the schedule's start time/rrule directly)
- A summary of the most recent completed run of that scan: findings by severity (critical/high/medium/low/informational) and number of assets scanned
- A warning at the top of the description if the most recent run aborted or failed, so the person knows to investigate before the next scheduled run

## Prerequisites

- Claude Code or Claude Cowork with:
  - A Tenable VM MCP connection (exposes `scan_list_scans`, `scan_configure`, `scan_history`, `scan_results`)
  - A Google Calendar MCP connection (exposes calendar event creation)
- Python 3 (used by the bundled `scripts/parse_severity.py` helper to sum severity/asset counts out of scan results text)
- Read access to the Tenable VM scans you want tracked

## How to run it

Invoke the skill (trigger name: `tenable-scan-status-calendar`) with a request like "put my scan schedule on my calendar" or "let me know if any scans are broken before they run again." The skill:

1. Lists all scans and checks which have an enabled recurring schedule
2. Infers each enabled scan's next run time from its recent history
3. Identifies the most recent run and its status (completed / aborted / failed / running)
4. Pulls severity counts and asset counts from the most recent completed run (falling back to an earlier completed run if the latest one aborted or failed)
5. Creates one Google Calendar event per scan projected to run in the next 7 days
6. Reports back a short summary of what was created and anything that needs attention

To re-run this automatically on a cadence (e.g. every Monday morning), set it up as a scheduled task.

## Output

One Google Calendar event per qualifying scan, set to `AVAILABILITY_FREE` so it doesn't block time. The event description contains the inferred next-run time and cadence, the scan ID/owner, and the sourced findings summary — clearly labeled if the numbers came from an earlier run than the most recent one.

## Known limitations

- Tenable's API doesn't expose the schedule's actual start time or rrule, so next-run times and cadence are inferred from recent scan history. If a scan has fewer than 3 historical runs, or an irregular run pattern, the next-run time is flagged as a best guess rather than treated as authoritative.
- If scan results are too large to read directly, the skill falls back to a targeted text extraction (via regex) rather than parsing the full results — this is a heuristic, not a guaranteed-complete parse, and the skill flags cases where extracted counts look inconsistent (e.g. a declared host count that doesn't match the number of per-host entries found).
- A scan reporting 0 hosts scanned is flagged rather than presented as equivalent to a clean, fully-scanned result, since it's more likely to indicate an unreachable target than a genuinely empty network.
- The skill only reads from Tenable and creates calendar events — it never modifies scan configuration (a "configure" endpoint call is used only as a read-back workaround, with no fields changed).
