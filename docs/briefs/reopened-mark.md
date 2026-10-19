---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: BigQuery (grant_tickets read; Dataform mart in slice 3)
module: bq_reads
spec: docs/specs/modules/bq_reads.md
folder: repo root (bq_reads.py, app.py, definitions/marts/, tests/)
---

# Brief: reopened-mark

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Mark a ticket reopened when a member comments after a close, as a derived flag not a new status

## Done when

New cases in `tests/test_bq_reads_urgency.py` (run `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bq_reads_urgency.py -q`): all four built queries select `is_reopened` from the same predicate as their reopen branch (R1a, R13a, R15a), and under a schema without `last_member_activity_at` it is still selected as constant `FALSE` (R4a). Red first against `3ecd4d6`, where `is_reopened` appears in no query; the existing R7 case stays green throughout. Slice 2 adds the chip at three render sites in `app.py`; slice 3 the `.sqlx` column.

Spec: unchanged because specs are the overseer's — R1a, R4a, R13a, R15a, R18a already describe this change; one conflict is raised under Spec proposals.

# Gate: a reopened ticket reads as reopened, not as brand new

## Product
Problem: a member comments on a ticket a coach answered and closed; it reopens as
plain `open`, so the fact it was answered is thrown away and the row looks new.
User: Lesko's coaches on the Tickets tab, each time a member replies after a
close — they need "answered once, came back" before they open the ticket.
Success: every ticket whose `closed_at` precedes `last_member_activity_at` is
marked REOPENED in list, header and dialog — today 0 are; clears on the next close.
Not in scope: no new status value (see Design) — `TICKET_STATUSES`,
`TERMINAL_STATUSES`, `is_open_status`, `STATUS_ICON`, the dropdown, the urgency
clock (R7) and `get_daily_stats` all stay as they are.
Mock-up — a reopened row beside a new one, same list:
```
  🔵 🟢 #4821  How do I evidence match funding?    2h
  🔵 🟢 #4702  Still stuck on the budget tab       1h  ↩ REOPENED · answered 3d ago
  ✅ 🟢 #4699  Which lane for a CIC?               5h
```

## Slices
1. Live CTE, `bq_reads.py`: in = the reopen predicate inlined four times at :33,
   :176, :227, :271; out = it named once, plus an `is_reopened` BOOL in all four.
   Proof: `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bq_reads_urgency.py -q`
   red-then-green — new cases assert all four queries select it; R7 case stays green.
2. The mark, `app.py`: in = `row["is_reopened"]`; out = a `↩ REOPENED` chip at
   :653 (list), :1115 (detail header), :1514 (group dialog) — status icon, the
   :416 filter and the :1116/:1121 dropdown untouched. Proof: same command, then app.
3. LAST — `definitions/marts/grant_tickets.sqlx`: in = rule (4) at :95 and its
   branch at :107-108; out = `ticket_status` still `'open'`, plus a matching
   `is_reopened` column. Additive, so no existing reader breaks.

Slice 3 lands by a push to `main`, which Dataform compiles within the hour, so
push and `deploy.sh` are one indivisible window — the overseer's, not the
worker's. It is the only task in this set whose landing hits production at once;
hence the `.sqlx` last, after 1-2 are proven. Never bare `pytest tests/` —
`tests/smoke_test.py` writes the live `ticket_metadata`.

Design: docs/specs/modules/bq_reads.md — `## Derived` (R1, new R1a/R4a), the four `## Functions` sections, `## Decisions` 2026-10-19.

## Agentic review

### Verdict
Verdict: pass — overseer review 2026-10-19. Checked the rule this change exists
to get right: `_reopen_predicate()` tests no `tm.status`, so the mark stays true
after a coach clicks `answered` (R1a) and clears on the next close, while
`_live_status_cte()` adds the status test on top so the status branch still
yields to a coach's click (R1). Also confirmed FALSE on an old schema (R4a), the
`.sqlx` column additive with rule (4) and `ticket_status` untouched, and the chip
drawn beside the status in all four places, never instead of it. 17 tests green
here. One observation accepted rather than sent back: `is_reopened` is also
selected in `get_open_stats` and `get_daily_stats`, where nothing reads it. It
cannot move the KPI numbers — both CTEs select named columns and the outer
queries are COUNTIF over named columns, no `SELECT *` and no UNION, and both
already read `last_member_activity_at` and `closed_at`, so there is no extra
scan. R18a governs the cards, not the CTEs, so it contradicts nothing, and
re-cutting the two KPI queries to drop an inert column would be churn in the
riskiest part of the diff. Landing authorised by Martin 2026-10-19.

### Findings
What the overseer's review subagent flagged — style, bugs, security —
one line each. A trimmer before Martin's read, not a replacement for it.

### Fixed in
Which commit fixed each finding, or "not fixed — see report" — one line
each.

This section is filled last, after the overseer runs its review subagent
and sends the findings back — never by the worker reviewing its own
diff. Record the findings under Findings (word for word) and the
fixes under Fixed in (one line per finding, naming its commit), fix
what needs fixing, commit, then report again the normal way. Also
leave the `Verdict:` line exactly as it stands: the overseer fills
it at review.

wt-done.sh's check on this is literal: it greps this brief for a line
starting with exactly `Verdict:` at the very start of the line (column 0)
— no bold, no indent, no renamed label, no different case. Keep the
`Verdict:` line reading exactly as it does above, or the guard cannot see
it and treats the brief as not yet reviewed.


## May touch

Module `bq_reads`. Files: `bq_reads.py`, `app.py` (only the three render sites, :653, :1115, :1514), `tests/test_bq_reads_urgency.py`, and in slice 3 `definitions/marts/grant_tickets.sqlx`. Nothing in `config.py`, `member_history.py` or `docs/specs/`.

## Deploy implied

Slices 1-2: `deploy.sh` (Cloud Run app), run by the overseer from main after landing. Slice 3: a push to `main` that Dataform compiles within the hour, so push and `deploy.sh` are one window, the overseer's.

## Context

2026-10-19: the overseer's memory message had not arrived when this brief was committed; its content gets added here when it comes. Spec: `docs/specs/modules/bq_reads.md` (`## Derived`, R1a/R4a/R13a/R15a/R18a, Decisions 2026-10-19). The reopen predicate sits at `bq_reads.py` :33, :176, :227, :271; the app reads the live CTE, not `grant_tickets.ticket_status`, so the `.sqlx` copy alone would change nothing a coach sees. Never bare `pytest tests/`: `smoke_test.py` writes the live `ticket_metadata`.

2026-10-19 (overseer): the mock-up's "answered 3d ago" age is deliberately not built, since the row carries no `closed_at` and the spec asks only for the mark; the overseer is putting the age to Martin as a separate follow-up. Known limit, not a bug: in the ticket list a multi-ticket group shows the REOPENED chip on its first row only (`row = grp.iloc[0]`); the group dialog shows each ticket's own. Site names, not line numbers: list row = `render_ticket_table`, detail header = `show_ticket_dialog`, group dialog = `show_group_dialog`; `app.py:644` is `STATUS_ICON.get(...)`, the status snap is `app.py:1116` against the list at `:1023`.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

1. Resolved 2026-10-19 by the overseer on main (`8b4eb3f`): R1a is now its own status-free predicate, R1 keeps `tm.status = 'closed'`. This branch builds the corrected text; nothing further proposed.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done: brief (f51d3d6); slice 1 (6cf05ff): status-free `is_reopened` in `bq_reads.py` via `_reopen_predicate()`, branch adds `tm.status = 'closed'`; slice 2 (82016b4): `_reopened_chip(row)` in `app.py`; slice 3: `is_reopened` column in `definitions/marts/grant_tickets.sqlx` after `ticket_status` (rule 4 untouched, no new status value), `tests/test_grant_tickets_sqlx_is_reopened.py`. 17 tests pass across the three test files.
In flight: merge origin/main, `wt-done.sh --check reopened-mark`, queue row, report.
Next: after the report, wait for the overseer's review; the push to main plus `deploy.sh` is the overseer's window (app deploy may go before the `.sqlx` push thanks to the EXCEPT guard).
Traps (with dates): 2026-10-19: once slice 3 adds `is_reopened` to `grant_tickets`, `gt.* EXCEPT(...)` would duplicate the name; slice 1 already EXCEPTs it when the table has it, so the app deploy can precede the `.sqlx` push. 2026-10-19: the R7 test also guards the mark (it slices from `AS ticket_status,` to `AS urgency`, which holds the `is_reopened` line); keep that anchor. 2026-10-19: `TERMINAL_STATUSES` has three values: closed, cancelled, archived. 2026-10-19: the brief's slice-2 line numbers are off: the list row is `render_ticket_table` (~:1514), the detail header is the badge row in `show_ticket_dialog` (~:667), the group dialog cards are in `show_group_dialog` (~:1063, :1148); :1115 is the status dropdown. `app.py` cannot be imported by tests (Streamlit starts on import), so the chip test reads it with `ast`. In a multi-ticket list group the chip shows on the group's first row only (`row = grp.iloc[0]`); the group dialog shows each ticket's own.
