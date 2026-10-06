# Goal
Status: agreed 2026-10-06

## What this repo is for
Lesko's coaches answer members' grant questions in one place, instead of chasing
them across chat zones.

## Who uses it
Lesko's coaches, daily; Martin runs and deploys it; Lesko's leads read the
Reports tab.

## The number that says it works
`BTB_ALERT grant-helpdesk/` lines in Cloud Logging, project `bigtribebuilders`,
and no scheduled runnable silent past its margin. Reading on 2026-10-06: zero in
the last 30 days, against a rail proven able to fire — the silence drill passed
2026-10-05. Zero only counts while that stays true, so the drill is the number's
other half, not a nice-to-have.

## Decisions

- 2026-10-06: the health number is the alert rail, not a helpdesk-work count
  (tickets in vs answered, tickets closed). Why: the rail is the one number that
  is wrong when the repo is broken and nobody is watching; work counts move for
  reasons that have nothing to do with the software being healthy.
- 2026-10-06: the rail is counted in Cloud Logging, not in
  `grant_helpdesk.app_logs`. Why: `raillog.alert()` prints a JSON line with
  `"severity": "ERROR"` to stdout, which Cloud Run promotes above DEFAULT
  (`raillog.py:59`); `app_logs` is a separate BigQuery table that `bq_base.py:33`
  streams app rows into for the admin tab, and it has never held a BTB_ALERT row.
