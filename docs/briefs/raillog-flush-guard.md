---
# Pairing block: what this worktree is paired to. Read by control-window.sh
# (cw_pairing) for the overview. wt-new.sh fills repo, and module and spec
# when WT_MODULE was given; everything else is yours or the interview's.
# Never guess a value from a branch, folder or repo name: leave `<fill in`.
client: <fill in>
repo: helpdesk
rails: none
module: raillog
spec: docs/specs/modules/raillog.md
folder: tests
---

# Brief: raillog-flush-guard

Stages: product (gate 1) · architecture (gate 2) · design (gate 3) · slices (gate 4) · review:300

Written by the overseer (window 1) before work starts; the first commit on this
branch. The worktree session reads this before touching anything. (wt-new.sh
fills in the two `<!-- ... -->` markers on this page — the line above with
this task's `Stages: ...` summary, the one below, under Goal and Done when, with this task's gate
fragments from TEMPLATE.d/, in WT_STAGE_ORDER; if either marker text is still
here, something skipped that step.)

## Goal

Add the ast guard that keeps both raillog copies printing the BTB_ALERT marker with flush=True, plus the REPO literal and two-copy equality checks

## Done when

The test or assertion that must go from red to green. Name it. If it does not
exist yet, writing it is the first task — and prove it goes red before trusting
it green.

One fixed extra line, always present, naming the module this task belongs to:
`Spec: docs/specs/modules/<module>.md updated` if the module's spec changed,
or `Spec: unchanged because <reason>` if it did not.

# Gate — raillog-flush-guard

Architecture and design: `docs/specs/modules/raillog.md`, R3, R5, R6 and its
*Test:* paragraph. On main, `7230775`.

## Product — why this first

An unattended failure reaches us as one line — `BTB_ALERT
grant-helpdesk/<runnable> <CODE>: <message>` — matched as text by the alert
policies. Both copies print it with `flush=True` today; nothing keeps them
doing so. Our two tests use `capsys`, which rule 2 bans as the proof: the
buffer empties when the process ends, so a captured read sees the line either
way, and a killed job losing its own alert would pass the suite today.

## Slice order

1. Red first. The invariant already holds, so red cannot come from
   `origin/main`; it comes from four mutations in a SCRATCH COPY, never the
   worktree, each restored after: delete `flush=True` from the marker print;
   point `REPO` at `os.environ`; change one line of code in `jobs/raillog.py`
   only; and a copy with no marker print at all, for the vacuity case.
2. One `ast` walk, in a new `tests/test_raillog_kit.py`, over BOTH `raillog.py`
   and `jobs/raillog.py` — the existing file covers the root copy only:
   `flush=True` on every `print` in the whole file whose source carries
   `BTB_ALERT`, not only those inside `alert()`, with a `file=` print exempt
   and a fail if none was found; `REPO` assigned a string literal (R5); the two
   files equal once comments and docstrings are stripped (R6).
3. Spec proposal back to the overseer, not a spec edit: the "(not built yet)"
   marks on R3 and in the Test paragraph come off.

## Done when

- Each guard shown red against its own mutation and green against the real
  files, the vacuity case included.
- `PATH=/opt/anaconda3/bin:$PATH python -m pytest tests/test_raillog_kit.py
  tests/test_raillog_app.py -q` passes. Never bare `pytest tests/`: it runs
  `smoke_test.py`, which writes the live `ticket_metadata`.
- No `capsys` and no `subprocess.run(...).stdout` as the proof of R3.
- May touch that one new test file. If a guard goes red against the real files,
  STOP and report — that is a live alerting hole, not yours to quietly fix.
- Spec: unchanged because specs are the overseer's; the "(not built yet)" marks coming off R3 and the Test paragraph are proposed under Spec proposals.

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

Name the module first — the smallest thing that deploys or is scheduled on
its own (see docs/specs/INDEX.md for this repo's module list). Then the
folders and files in scope. Anything outside this list is a question back to
the overseer, not a change.

Module: raillog. Files: the new `tests/test_raillog_kit.py` only. `raillog.py` and `jobs/raillog.py` are read, never edited.

## Deploy implied

Which deploy script (or Dataform tag) this change needs to go live. The
worktree session never runs it; the overseer does, from main, after the merge.

None: a test file only, nothing ships.

## Context

Links: the HANDOFF doc, the session log lines, the ids, the numbers measured.
Enough that a fresh session needs no paste.

2026-10-20: the overseer's memory message had not arrived when this was committed. Read at start: both copies print the marker with `flush=True` today and `REPO = "grant-helpdesk"` is a literal; the two files differ only in comments and docstrings (checked with `diff`). Global rule: the R3 proof is an `ast` walk over the whole helper file, never a captured read-back.

## Spec proposals

Specs belong to the overseer (DECISION BY MARTIN 2026-09-24) — this worktree
never edits docs/specs/ itself. Anything found missing, unclear or wrong in a
module's spec goes here instead: what the spec says now, what it should say,
and why. The overseer applies what it agrees with on main.

## State

Replaced in full each time the context guard asks you to save — never append another checkpoint.
About 60 lines max. Old traps stay (they are short and worth keeping); everything else gets
overwritten with the current picture.

Done:
In flight (file:line):
Next:
Traps (with dates):
