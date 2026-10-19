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
Verdict: `<fill in — pass, or changes requested>`

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

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

1. File `bq_reads.md`, R1a against the Decisions entry of 2026-10-19. R1a says `is_reopened` is true exactly when R1's branch fired, and R1 requires `tm.status = 'closed'`. The Decisions entry says the mark tests no status, so marking a reopened ticket `answered` moves neither badge nor mark. Both cannot hold: once a coach saves `answered`, `tm.status` is no longer `'closed'`, R1 stops firing, and R1a's mark goes false. Proposed: R1a stays as written (the mark exists to say "a member spoke after the close and nobody has acted yet"; it clears when a coach acts, like the status does), and the Decisions sentence about `answered` is cut back to the clock only (R7). The alternative is a status-free predicate (`closed_at < last_member_activity_at`), which matches the Product line "every ticket whose `closed_at` precedes `last_member_activity_at`" but would need R1a reworded. Until answered, this branch builds R1a as written (same predicate as R1).

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done: brief (f51d3d6); slice 1 (1c9b3a4): `_reopen_predicate()` in `bq_reads.py`, `is_reopened` in all five live CTEs, 4 new tests red-then-green, 10 pass.
In flight: waiting for the overseer's reply to "slice 1 done" and on the R1a question.
Next: slice 2 (`app.py` chip at the three render sites), then slice 3 (`.sqlx`, last).
Traps (with dates): 2026-10-19: the R7 test sliced the SQL from `AS ticket_status,` to `AS urgency`; `is_reopened` legitimately reads `tm.status`, so the slice now starts after `AS is_reopened,`. 2026-10-19: once slice 3 adds `is_reopened` to `grant_tickets`, `gt.* EXCEPT(...)` would duplicate the name; slice 1 already EXCEPTs it when the table has it, so slice 3 is safe to land after the app deploy.
