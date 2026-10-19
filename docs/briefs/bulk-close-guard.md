---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: BigQuery
module: bq_writes
spec: docs/specs/modules/bq_writes.md
folder: repo root (`bq_reads.py`, `bq_writes.py`, `tests/`)
---

# Brief: bulk-close-guard

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Extract one shared row-selection helper used by both execute_bulk_close and preview_bulk_close, exclude archived from the sweep, and add the first bulk-close test with a red-first proof for each rule

## Done when

`tests/test_bulk_close.py`: test_r2, test_r3, test_r4, test_r9 go red against `origin/main` (no helper to import; archived swept), then green. Details in the gate section below.

Spec: unchanged because specs are the overseer's; the new R4 and R9 wording (drop "not yet in the code") is proposed under Spec proposals.

# Gate — bulk-close-guard

Architecture and design: `docs/specs/modules/bq_writes.md`, section
`### execute_bulk_close(...)`, rules R2, R3, R4, R9, R10. Agreed text, on main.

## Product — why this first

A coach presses Preview, reads "40 will be closed, 3 skipped", presses the
button. That number is the whole of the consent: nobody re-reads forty rows.
Today the number and the sweep are two separate copies of the same SQL
(`bq_writes.execute_bulk_close`, `bq_reads.preview_bulk_close`), and no test
covers either — `grep -rn bulk_close tests/` finds nothing. helpdesk-05 asks
for the same sweep over member questions, which would make a third copy. One
shared row-selection helper, guarded, has to exist first.

## Slice order

1. Capture today's SQL for a few filter sets as a fixture, so the extraction
   is provably row-identical except for the one intended change.
2. Extract one pure helper that builds the row selection (WHERE + `base` CTE)
   from filters and returns SQL text — `bq_reads._reopen_predicate`'s shape.
3. Exclude `archived` alongside `closed` and `cancelled` (R4, Martin, 2026-10-19)
   — the only rule whose red comes from live behaviour, not a missing import.
4. `tests/test_bulk_close.py` asserts R2, R3, R4 and R9 on strings, with no
   BigQuery client. R9 is one assertion that both callers use the helper.
5. Update `bq_writes.md` R4 and R9, which today say "not yet in the code".

Slice replies (overseer, relaying Martin, 2026-10-19): slice 1 accepted, no red/green for a capture. Slice 2 "Continue as proposed": helper in `bq_reads.py`, `bq_writes` imports it (new dependency edge, chosen over `bq_base.py`); R3 stays per caller, so the R3 test asserts both strings and says so. Slices 3-5: carry on without checking in.

## Done when

- One pure helper builds the row selection; neither function inlines it.
- `archived` is excluded; a ticket in that state survives a matching sweep.
- Red-first shown as output for each of R2, R3, R4, R9, against `origin/main`.
- `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_bulk_close.py -q`
  passes. Never bare `pytest tests/` — it runs `smoke_test.py`, which writes
  live `ticket_metadata`. No change beyond `archived`: R7 and R10 stay put.

## May touch

`bq_writes.py`, `bq_reads.py`, `tests/test_bulk_close.py`,
`docs/specs/modules/bq_writes.md`. Not `app.py`, not `coach_inbox.py`.

## Agentic review

### Verdict
Verdict: `<fill in — pass, or changes requested>`

### Findings
What the overseer's review subagent flagged — style, bugs, security —
one line each. A trimmer before Martin's read, not a replacement for it.

Round 1, from the overseer, word for word:

FINDING 1 (blocker). `tests/fixtures/bulk_close_sql_before.json` is never read. `grep -rn bulk_close_sql_before tests/ *.py` returns nothing; the test file imports only `re`, `pytest`, `bq_reads`, `bq_writes`. Slice 1's whole purpose — proving the extraction preserved behaviour — is therefore unguarded, and 42 lines of data sit there that any reader will assume is asserted. Either assert against it or delete it; a captured-but-unread fixture is worse than none, because it reads as proof.

FINDING 2 (blocker, and I am promoting it from the nit it was reported as). R9 is guarded only by substring containment at `tests/test_bulk_close.py:142-143`. Appending `WHERE f.domain != 'excluded-domain'` after `bq_reads.py:566` makes preview and execute select different rows **and all ten tests still pass**. That was demonstrated by mutation, not theorised. R9 — preview and execute select the same rows — is the single invariant this whole worktree exists to make provable, and the number a coach consents to is the thing it protects, so a guard that green-lights a real divergence is not a nit. It is made worse by the helper's base now exposing `assigned_to` and `domain` to preview, which previously saw only `content_id`: there is more to narrow on than before.

### Fixed in
Which commit fixed each finding, or "not fixed — see report" — one line
each.

Finding 1: fixed in e88b0b0, `test_r9_sql_differs_from_the_before_fixture_only_where_allowed` reads the fixture and compares lines (multiset) for all four filter sets, with the nesting lines pinned.
Finding 2: fixed in e88b0b0, same test; the reviewer's mutation (WHERE on `f.domain` in preview) now fails 4 tests. Also red: the same on execute (4), a narrowed COUNTIF (5), a changed MERGE SET value (4). Unmutated: 18 pass. No extra assertion was needed.

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


## May touch (module)

Module `bq_writes`. Files: `bq_writes.py`, `bq_reads.py`, `tests/test_bulk_close.py`. Nothing else.

## Deploy implied

`deploy.sh` (Cloud Run app) after the merge: `app.py` calls both functions. No Dataform change. The worktree never runs it.

## Context

2026-10-19, from the overseer's memory message: this is an extraction, not a new feature (`execute_bulk_close` `bq_writes.py:145`, `preview_bulk_close` `bq_reads.py:490`, UI `app.py:1751-1797`). Leave alone: R7 (`closed_by` defaults to empty), R10 (interpolation; the dormant `bq-writes-params` worktree owns it), deprecated `utcnow()`, community tickets only. R8 is deliberate: the sweep skips reopened tickets. The auto-reopen lives in `definitions/marts/grant_tickets.sqlx:105-107`, so any member message reopens a closed ticket. Martin, 2026-10-19: exclude `archived` because sweeping it silently edits history in status reports. Test command always names the file; never bare `pytest tests/`. Next worktree `bulk-close-convo` will reuse the helper, so keep it clean.

Red-first proof (2026-10-19), `tests/test_bulk_close.py`, 10 tests: against `origin/main` (no helper) 8 fail, namely R2 x3, R4 x2, R9 x3, and the 2 R3 tests pass because that code already obeys R3. Against slice 2 (helper, `archived` not yet excluded) only the 2 R4 tests fail: live behaviour, an archived ticket is swept. On the branch all 10 pass. R3 red comes from breaking the code on a scratch copy: dropping `NOT IN` in execute fails the execute test, replacing `COUNTIF` in preview fails the preview test. Also red on purpose: R2 with OR instead of AND (2 fail), R2 with empty status matching (2 fail), R9 with preview altering the helper text (3 fail). R3 is guarded in two places by decision (Martin, 2026-10-19).

Fixture diff: against `tests/fixtures/bulk_close_sql_before.json`, after normalising whitespace, the SQL differs only in nesting (execute wraps the helper in a subselect; preview's CTE moves into the helper) and in `'archived'` added to the exclusion list. Filters, pending-follow-up clauses, MERGE and its values are line-identical. The text is not byte-identical, and the helper's base CTE carries two extra columns for preview that it ignores.

Design choice: the helper `bulk_close_rows_sql(status_filter, assigned_to, before_date)` lives in `bq_reads.py` (next to `preview_bulk_close`, `bq_writes` imports it). It returns the `base` CTE plus the filtered SELECT; the pending-follow-up handling (R3) stays with each caller. R10 stays as is (interpolation), as the brief says.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

1. File `docs/specs/modules/bq_writes.md`, rule R4. Now: "The code excludes only the first two today, so an archived ticket inside the filters is swept and comes back `closed`." Propose: "`bq_reads.bulk_close_rows_sql` excludes all three, so neither the preview number nor the sweep touches an archived ticket; `tests/test_bulk_close.py::test_r4_*` guards it." Also drop "Carried by R4; not yet in the code." from the later section (about line 170).
2. Same file, rule R9. Now: "They are two copies of that logic today, so a change to one is a change to both in the same commit." Propose: "Both call `bq_reads.bulk_close_rows_sql`, which builds the `base` CTE and the filtered SELECT once; the pending-follow-up predicate (R3) stays per caller (execute: `NOT IN`; preview: LEFT JOIN with `COUNTIF`). `test_r9_*` asserts the helper's text sits inside what both callers send."
3. Same file, `*Test:*` paragraph. Now: "none exists ... A worktree taking this on adds `tests/test_bulk_close.py`". Propose: "`tests/test_bulk_close.py` guards R2, R3 (in both callers), R4 and R9, on SQL strings with no BigQuery client; R7, R8 and R10 are not tested." Keep the never-bare-pytest warning.
4. Same file, Overview or dependency note if one exists: `bq_writes` now imports `bq_reads` (new edge, chosen by Martin over `bq_base.py`).

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
In flight (file:line):
Next:
Traps (with dates):
