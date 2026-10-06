# Brief: reopen-urgency

Stages: product (gate 1) · architecture (gate 2) · review:300 — DOWNGRADED (dropped: design · slices)
Downgraded: repo default "groot" wanted design · slices.
Reason: architecture is already agreed in docs/specs/modules/bq_reads.md R5-R8, R12, R18; the change is one derived timestamp in five query sites of one file, no new screen and no schema change, so there is nothing left to design or slice

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Product — gate 1

### Problem
A coach answers a member's grant question and closes it; the member comments
again, the ticket comes back — and comes back badged urgent or critical, as if
it had been left sitting for days. Nobody has been kept waiting, so the badge
lies, and it pushes the tickets that really are waiting down the list.

### User
Lesko's coaches, on the Tickets tab, every time a member replies to a question
that was already answered and closed. Reported by a coach, 2026-10-06.

### Success metric
Count the open tickets that have been reopened — the ones whose
`ticket_metadata.closed_at` is earlier than their
`grant_tickets.last_member_activity_at` — and count how many of those are
badged anything other than `normal`. Today that second number equals every
reopened ticket created more than 24 hours ago, which in practice is all of
them. After shipping it is 0 at the moment of reopening, and rises only as a
reopened ticket genuinely goes unanswered past 24 hours.

### Mock-up
No new screen: the same Tickets rows, the same four KPI cards, the same Urgency
pills. Only the badge a reopened row carries changes.

```
  case                                     before        after
  closed 5 days ago, member comments now   critical      normal
  closed 2 days ago, member comments now   urgent        normal
  reopened now, coach then marks answered  critical      normal
  never closed, created 5 days ago         critical      critical   (unchanged)
  created 3 hours ago                      normal        normal     (unchanged)
```

## Architecture — gate 2

See `docs/specs/modules/bq_reads.md` "## Derived" (both halves: "Live status"
R1-R4 and "The urgency clock" R5-R8), and its `## Functions` sections for the
rule numbers, examples and test line per query site.

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
diff. Record the verdict, fix what needs fixing, commit, then report
again the normal way.

wt-done.sh's check on this is literal: it greps this brief for a line
starting with exactly `Verdict:` at the very start of the line (column 0)
— no bold, no indent, no renamed label, no different case. Keep the
`Verdict:` line reading exactly as it does above, or the guard cannot see
it and treats the brief as not yet reviewed.


## Goal

Count urgency for a reopened ticket from the member comment that reopened it, not from created_at, in the badge, the Urgency pills and the KPI counts, per docs/specs/modules/bq_reads.md R5-R6, R12, R18

## Done when

`tests/test_bq_reads_urgency.py` (new) passes, run as:
`PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bq_reads_urgency.py -q`
— stubbing `_query_with_schema_retry` to return the built SQL and
`_tickets_cols()` to include `last_member_activity_at`, it asserts that:
- `get_tickets`'s urgency CASE and its `urgency='Normal'` filter both read
  `urgency_since`, a column selected inside the `live` CTE as the R5/R6
  clock expression (R12);
- `get_ticket_detail`'s and `get_member_thread_tickets`'s urgency CASEs derive
  from that same clock expression (R14, R15);
- `get_open_stats`'s three `COUNTIF`s bucket on that clock, not on
  `created_at` (R18).
Shown red against `origin/main` before the fix, green after.

Spec: `docs/specs/modules/bq_reads.md` needs a change — not made here (worker
permissions deny writing under `docs/specs/`), proposed instead under
`## Spec proposals` below: drop the trailing "not built yet" mark from R5,
R12, R18, now that they are built. No rule text changes.

## May touch

Module: `bq_reads` (deploy: `deploy.sh`, ships inside the app image).
- `bq_reads.py` — the five sites named in Context below.
- `tests/test_bq_reads_urgency.py` — new.
- `docs/specs/modules/bq_reads.md` — not edited directly (specs belong to the
  overseer); any text change needed goes under `## Spec proposals` instead.

## Deploy implied

`deploy.sh`, from `main`, after the overseer lands this branch. Not run here.

## Context

Overseer's message (2026-10-06, relayed after `wt-new.sh`, no separate memory
message arrived):
- The five query sites, in `bq_reads.py` as of commit `57fc071`: (1) `get_tickets`
  urgency filter map ~125-132, outer `WHERE`, reads `created_at` today; (2)
  `get_tickets` urgency CASE ~172-176, outside the `live` CTE; (3)
  `get_ticket_detail` urgency CASE ~210-214, `tm` in scope; (4)
  `get_member_thread_tickets` urgency CASE ~255-259, inside its `live` CTE,
  `tm` in scope; (5) `get_open_stats` three `COUNTIF`s ~503-510.
- Sites 1-2 cannot see `tm` outside the `live` CTE and BigQuery cannot filter
  on a same-level SELECT alias, so the clock is selected inside that CTE as
  `urgency_since`; sites 3-5 have `tm` in scope and use the clock expression
  inline.
- Trap (2026-10-06): R5 does not test ticket status, unlike the reopen clause
  (R1, `_live_status_cte()`). Copying the reopen clause's `tm.status =
  'closed'` guard into the urgency clock would snap a reopened-then-answered
  ticket's badge back to `critical` on one coach click — R7 exists precisely
  to forbid this.
- Do not touch: `get_daily_stats` (counts arrivals/answers by date, not
  waiting time — written down in the spec's Decisions); the reopen status
  clause itself (`_live_status_cte()` and its three inline duplicates — leave
  as is, the clock is a separate expression, not a rewrite); the
  empty-body filter shared by `get_tickets` and `get_open_stats` (R10/R17,
  must stay in sync); `coach_inbox.py` (private 1:1 questions, no urgency).
- `bq_reads.py` has no tests today; this adds the first one. Never run
  `pytest tests/` — it collects `smoke_test.py`, which writes to the live
  `ticket_metadata` table.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

- File: `docs/specs/modules/bq_reads.md`. Three lines each carry the trailing
  mark `` *(agreed 2026-10-06, not built yet)* `` — line 55 (end of R5), line
  86 (end of R12), line 146 (end of R18). Now built and proven by
  `tests/test_bq_reads_urgency.py` (commit `33f8a32`); drop just that trailing
  mark from each of the three lines, no other text changes. The overseer's own
  message asked this worktree to clear the marks itself in its last commit —
  not done here, since worker permissions deny `Edit`/`Write` under
  `docs/specs/` and the repo's own rule is that specs are the overseer's to
  write, not a worker's, even on request.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
- Brief filled in and committed (bcc03b0), architecture gate swapped for a
  link to docs/specs/modules/bq_reads.md per overseer's message.
- Added `_urgency_clock_expr()` to bq_reads.py (R5-R8) and wired it into the
  five sites: get_tickets' urgency filter map + its `live` CTE/outer CASE
  (via a new `urgency_since` column, R12), get_ticket_detail's CASE (R14),
  get_member_thread_tickets' CASE (R15), get_open_stats' three COUNTIFs
  (R18). Commit 33f8a32.
- Wrote tests/test_bq_reads_urgency.py (bq_reads.py's first test, 5 cases),
  proved red against the prior created_at-only queries, green after the fix.
  Run: `PATH=/opt/anaconda3/bin:$PATH python -m pytest
  tests/test_bq_reads_urgency.py -q`.
- Spec change needed (drop "not built yet" from R5/R12/R18 in
  docs/specs/modules/bq_reads.md lines 55/86/146) written under this brief's
  Spec proposals instead of edited directly — worker permissions deny
  Edit/Write under docs/specs/, and specs are the overseer's to write even
  on direct request (commit d669f11).
- origin/main (57fc071) already an ancestor of this branch — no merge
  needed. `wt-done.sh --check reopen-urgency` passes (clean tree, origin/main
  merged).
- Reported to helpdesk-opzichter: branch reopen-urgency, commit range
  57fc071..d669f11, HEAD d669f115ca642962e033027ee8645d41c263750d.

In flight (file:line): none — task reported, waiting on overseer's review
verdict.

Next: when the overseer's review message arrives, either (a) it says "land
it" — stop, nothing further on this branch; or (b) it asks for changes —
make them, commit, run the test suite again, report again the same way.

Traps (with dates):
- 2026-10-06: R5/R7 trap — the urgency clock must NOT test tm.status, unlike
  the reopen clause in `_live_status_cte()` which does test
  `tm.status = 'closed'`. Copying that status guard into the clock would snap
  a reopened-then-answered (non-terminal, still listed) ticket's badge back
  to `critical` on one coach click. `_urgency_clock_expr()` deliberately has
  no status test — keep it that way in any future edit here.
- 2026-10-06: never run `pytest tests/` in this repo — it collects
  `smoke_test.py`, which writes to the live `ticket_metadata` table. Always
  name the test file explicitly.
- 2026-10-06: BigQuery cannot filter (WHERE) on a SELECT alias defined at the
  same query level — that's why `urgency_since` has to be a real column
  selected inside the `live` CTE in get_tickets, not an outer-SELECT alias,
  for the urgency filter to be able to read it.
