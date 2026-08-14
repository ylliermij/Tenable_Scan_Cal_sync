---
name: tenable-scan-status-calendar
description: "Puts upcoming Tenable VM scan jobs on Google Calendar and flags any scan whose last run aborted or failed. Use this whenever the person asks to sync, calendar, or schedule their Tenable scans, wants a heads-up on scans that need attention before their next run, or asks about the health/status of their recurring vulnerability scans alongside when they next fire. Trigger even if they just say something like 'put my scan schedule on my calendar' or 'let me know if any scans are broken before they run again' — don't wait for them to mention severity counts or asset counts explicitly."
---

# Tenable Scan Status → Calendar

## What this skill does

For every Tenable VM scan with an active recurring schedule that's due to fire in the next 7 days, create one Google Calendar event. Each event's description says when it's projected to run, and summarizes the **most recent run of that same scan ID** — findings by severity and number of assets scanned. If that most recent run aborted or failed, the description opens with a clear warning that the scan needs review before its next run, since a broken scan config that just keeps re-running unattended is worse than a scan that quietly finds nothing.

The core idea: a calendar full of "next run" times is only half useful. Pairing it with "how did last time go" turns the calendar into an early-warning system, and the abort/failure flag is the part that actually gets someone to go fix something instead of letting a broken scan cycle silently.

## Step 1: Find candidates

1. Call `scan_list_scans` to get every scan.
2. For each scan, check whether its schedule is enabled by calling `scan_configure` with **only** `scan_id` (no other fields). This looks like an "update" call, but passing no fields to change doesn't alter anything — it's just the only way to read back the current `Enabled` state, since Tenable's MCP surface doesn't expose a pure read-only schedule-details call.
   - `Enabled: True` → keep it.
   - `Enabled: False` / `Enabled: None` → not self-scheduled, skip it.
   - An error like "Scanner not found" or "Invalid uuid" → broken/orphaned scan definition. Skip it, but keep a short note so you can mention to the person that some scans couldn't be verified rather than silently dropping that information.

## Step 2: Work out when each enabled scan will next run

Tenable's API doesn't expose the schedule's rrule/start-time directly, so infer cadence from history:

1. Call `scan_history` for the scan (the default limit, recent ~10-15 runs, is plenty).
2. Look at the start times of the last several runs to read off the cadence (usually weekly on a consistent day/time, sometimes daily or monthly — read the actual pattern rather than assuming weekly).
3. Project forward from the most recent run using that cadence to find the next occurrence inside the rolling 7-day window starting today (use the current date from your environment, not a hardcoded one).
4. If the history is too irregular to confidently infer a cadence (gaps vary a lot, or fewer than 3 runs exist), still surface the scan but flag explicitly that the next-run time is a best guess.
5. If the projected next run falls outside the 7-day window, skip this scan for this pass.

## Step 3: Identify the most recent run and its status

This is the step that's different from a plain "show me the last completed scan" summary — deliberately look at the run itself, not just the last *clean* run:

1. In the `scan_history` results you already pulled, find the single most recent entry regardless of status — this is "the last scan job that ran."
2. Check its `Status`:
   - `completed` → no warning needed. This run is also your source for the findings summary in Step 4.
   - `aborted`, `canceled`, `failed`, or similar → this scan needs a warning. Findings/severity data from an aborted or failed run isn't trustworthy (the scan may not have finished touching every asset), so for the *numbers* in Step 4, look back through history for the most recent entry with `Status: completed` instead, and label it clearly as an earlier run so the person isn't confused about which run the numbers came from.
   - `running` → the scan is mid-flight right now. Treat this like the aborted/failed case for sourcing numbers (use the last completed run instead), but the top-of-description note should say it's currently running rather than that it needs review — that's a different situation from a scan that's broken.
3. If there's no completed run anywhere in history, say so plainly in the description instead of fabricating numbers ("No completed run on record for this scan").

## Step 4: Pull severity counts and asset count from the sourced run

A zero-host result deserves the same skepticism as a wildly-different-from-normal result: a scan that finds 0 hosts every time is more likely hitting an unreachable or misconfigured target than a genuinely empty network. If the host count comes back 0, say so plainly rather than reporting it the same way you'd report a clean, fully-populated scan — those two look identical in the numbers but mean very different things to the person reading the calendar.

1. Call `scan_results` with the scan's `scan_id` and the `history_id` of the run you settled on in Step 3.
2. This can come back two ways:
   - **Inline in the response** (small scans) — write the markdown text straight to a file under your outputs directory (the one your Bash tool can reach — check the mapping between your file-tool paths and shell paths, they often differ).
   - **Saved to a file** because it's too large for context — you'll get a file path instead, which usually lives on a mount your Bash tool *cannot* reach even though Read/Grep can. Don't assume it's Bash-reachable; check first.
3. **If the results file isn't reachable from Bash** (common for large scans): don't try to `Read` the whole thing — these can run 100k+ tokens and `Read` will refuse. Instead, use Grep with `-o: true` on that file to extract just what you need, and copy the matches into a new file in your Bash-reachable outputs directory with Write:
   - Pattern A (per-host severity): `Vulns: \[Crit: \d+ \| High: \d+ \| Med: \d+ \| Low: \d+\]`
   - Pattern B (informational plugin counts): `\(Sev: 0\).{0,80}?Count: \d+` with `multiline: true`
   - **Set `head_limit` generously (500-1000+, never the default)** — a truncated extraction silently under-counts with no error message, and confidently-wrong numbers are worse than an honestly-caveated absence of numbers. If the match count looks suspiciously close to your `head_limit`, raise it and re-run.
   - Write both sets of matches into one file, one match per line.
4. Either way, once you have a Bash-reachable file with the relevant text, write the script below to `parse_severity.py` in that same directory (only needs to be written once per session) and run:
   ```
   python3 parse_severity.py <path-to-file>
   ```
   This prints JSON: `{"totals": {"critical": N, "high": N, "medium": N, "low": N, "info": N}, "host_count": N, "declared_host_count": N}`. Always use the script rather than hand-summing — these results can span hundreds of hosts, and manual summation (by you or a subagent) is exactly the kind of arithmetic that quietly drifts wrong.
   - `declared_host_count` comes from the scan's own `**Host Count:**` header. If it's wildly different from `host_count` (the number of per-host entries the script actually found), say so — it usually means the results format shifted or an extraction step above missed entries, and the totals shouldn't be presented as authoritative without that caveat.

   ```python
   #!/usr/bin/env python3
   """
   Sum severity counts and asset (host) counts out of Tenable scan-results text.

   Works on either the full raw scan_results text for a single history run,
   or a file containing only pre-extracted matching lines (useful when the
   full results file was too large to Read directly and you pulled out just
   the relevant lines with Grep -o first).

   Usage: python3 parse_severity.py <path-to-file>
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
       print(json.dumps({
           "totals": totals,
           "host_count": host_count,
           "declared_host_count": declared_host_count,
       }))

   if __name__ == "__main__":
       main()
   ```

## Step 5: Create the calendar event

For each scan that survived Steps 1-2 (enabled AND projected to run in the next 7 days), create a calendar event:

- **summary**: `Tenable Scan: <scan name>`
- **startTime / endTime**: the projected next-run window, in UTC (`...Z` suffix) — pass ISO 8601 timestamps directly rather than guessing the person's timezone; the calendar tool converts to local time automatically. Default to a 2-hour block if the typical run duration isn't clear from history.
- **availability**: `AVAILABILITY_FREE` (a scan running in the background shouldn't block the person's calendar)
- **description**: build it in this order —
  1. **If (and only if)** Step 3 found the most recent run aborted/failed, open with a warning line, e.g.:
     `⚠️ NEEDS REVIEW: last run (2026-08-10) aborted. Investigate and fix before the next scheduled run.`
     If the most recent run is still `running`, use a distinct, non-alarming note instead: `Note: a run of this scan is currently in progress.`
  2. The scan ID/UUID, owner, and inferred cadence (e.g. "weekly, Fridays ~06:00 UTC").
  3. The findings summary, labeled with which run it's from, e.g.:
     ```
     Findings from last completed run (2026-07-24): Critical: 1, High: 12, Medium: 45, Low: 8, Informational: 210
     Assets scanned: 3
     ```
     If the numbers came from an earlier completed run because the most recent run aborted/failed, say that explicitly (e.g. "most recent run aborted with no usable findings; showing the prior completed run instead") rather than letting the person assume the numbers reflect the latest attempt.
  If severity data was uncertain or unavailable for any reason, say so plainly instead of omitting it silently — the person is relying on this to judge whether the next scan matters.

## Step 6: Summarize for the person

After creating the events, report concisely: how many events were created, which scans they're for, and call out anything they should know about — scans flagged for review, scans whose next-run time is a best guess, scans with no completed history yet, or scans that couldn't be verified as scheduled. Keep it to a short list, not a wall of text.

## Notes

- This skill only touches the calendar (create events) and reads from Tenable — it never modifies scan configuration, even though Step 1 technically calls a "configure" endpoint. Never pass any fields to `scan_configure` beyond `scan_id`.
- If the person wants a different lookahead window than 7 days, or wants disabled/broken scans included too, adjust the window/filtering logic rather than treating 7 days as fixed.
- If the person asks to re-run this regularly (e.g. "do this every Monday morning"), offer to set it up as a scheduled task rather than assuming a one-off run is enough.
