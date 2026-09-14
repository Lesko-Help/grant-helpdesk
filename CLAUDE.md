# grant-helpdesk

## Roles: overseer and worktrees

Two kinds of Claude session run in this repo, and they do different things.
Which one you are is decided by your folder:

- **`~/Lesko/grant-helpdesk` = the overseer** (session `helpdesk-opzichter`,
  tmux window 1, always on `main`). It never writes code. It starts work with
  `wt-new.sh <name> "<one-line goal>"`; it reviews a finished worktree
  (`git add -N .` in the worktree, then `git diff origin/main...HEAD`), lands it
  with `wt-done.sh <name>`, and deploys from `main` afterwards (`deploy.sh`).
  The only files it edits itself are environment files — `CLAUDE.md`,
  `.gitignore`, `.werk.conf`, `docs/briefs/TEMPLATE.md` — committed straight
  to `main` and pushed at once.
- **`.claude/worktrees/<name>` = a worktree session** (session
  `helpdesk.<name>`, tmux window of the same name). Read
  `docs/briefs/<name>.md` before touching anything; fill it in from the goal
  and make it the first commit. Work only on branch `<name>`. Never push to
  `main`, never run `deploy.sh`, never change the Dataform release or workflow
  configs, never `git worktree` anything — those are the overseer's. When the
  brief's done-when holds, report to `helpdesk-opzichter` by message (branch,
  commit range, summary, how red-then-green was proven, deploy implied) and
  stop; the overseer takes it from there.

Why: `deploy.sh` runs `gcloud run deploy --source .`, which ships whatever
folder it runs from, so a deploy from a worktree ships an unmerged branch.
Dataform compiles from GitHub `main`, so anything pushed to `main` reaches the
scheduled runs within the hour — only a landing may push there. And two
sessions in one folder overwrite each other's uncommitted work; a worktree is a
separate folder, so they cannot. Max three open at once (`wt-new.sh` refuses a
fourth).

The `wt-*.sh` scripts live in `~/.werk/` (on PATH, shared by every repo;
lazygit `n`/`o`/`D` call them). What a fresh worktree needs carried in — the
Dataform credentials and the app's secrets — is `WT_CARRY` in `.werk.conf`.
