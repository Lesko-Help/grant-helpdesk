# NAME
Status: draft

Part of: `docs/specs/INDEX.md` · Deploy: `deploy-NAME.sh` · Updated: DATE

Read `~/.werk/SPECS.d/STYLE.md` before filling this in.

## Overview

Eleven lines or fewer, this note included.

*What it is for, one line.*
*What it owns, one line.*
*What it depends on, one line.*
*Public entry points, by name — one line.*
*Not in scope, one line.*

## Functions

One subsection per public function or entry point. An unfilled one is just
the heading, the signature, and the `<!-- spec:stub -->` marker — nothing
else, until a worktree actually touches that function, like this:

### function_name(args)

*Signature, as it is in code.*

<!-- spec:stub -->

Once a worktree has actually touched the function, the subsection fills in
like this instead:

### other_function_name(args)

*Signature, as it is in code.*

*What it does:*
- R1: when INPUT is X, it does Y.
- R2: when INPUT is Z, it does W instead.

*Examples:* INPUT -> OUTPUT.

*Inputs:* one line.

*Outputs:* one line.

*Errors:* TRIGGER -> exit CODE -> `BTB_ALERT` CODE.

*Test:* the exact command, the input or fixture it uses, what is observed
(output, exit code or file), and "red first against `origin/main`" — names
the rule number it proves.

## Decisions

- DATE: the decision, in one line, and why.

<!-- spec:template -->
