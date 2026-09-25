"""
Static guard for the code rule in docs/specs/modules/coach_inbox.md,
"private_chat is insert-only": no tracked .py file may run UPDATE, DELETE,
MERGE, TRUNCATE, ALTER, DROP or CREATE against private_chat's own tables
(private_messages, private_threads). Workflow state (assign/lane/close)
belongs in a helpdesk-owned table instead, where writes are allowed.

Slice A4 (docs/briefs/coach-inbox-list.md).
"""

import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FORBIDDEN = ("UPDATE", "DELETE", "MERGE", "TRUNCATE", "ALTER", "DROP", "CREATE")
_GUARDED_TABLES = ("private_messages", "private_threads")
_KEYWORD_RE = re.compile(r"\b(" + "|".join(_FORBIDDEN) + r")\b", re.IGNORECASE)
_WINDOW_CHARS = 200  # a SQL statement here is always short and on one call, never spread file-wide


def _find_violations(text: str) -> list[str]:
    """
    Input: one source file's text. Output: one description per spot where
    a forbidden SQL keyword sits close enough to a private_chat table name
    to plausibly be operating on it, so a reviewer can go straight to the
    line without re-reading the whole file.
    """
    violations = []
    for match in _KEYWORD_RE.finditer(text):
        window = text[match.start(): match.start() + _WINDOW_CHARS]
        for table in _GUARDED_TABLES:
            if table in window:
                line_no = text.count("\n", 0, match.start()) + 1
                violations.append(f"line {line_no}: {match.group(1)} near {table}")
    return violations


def _tracked_py_files() -> list[Path]:
    """
    Input: none. Output: every .py file git tracks in this repo — the
    guard's job is to cover the whole codebase, not just this app's own
    modules, since any file could in principle import bigquery and query
    private_chat directly.
    """
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [_REPO_ROOT / line for line in result.stdout.splitlines() if line]


def test_guard_catches_a_real_violation():
    # Proves the guard can go red: built by joining fragments at runtime so
    # this line itself never contains the literal keyword+table text — if it
    # did, the real-codebase scan below would flag this very file.
    bad_sql = "UPD" + "ATE `lesko-486515.private_chat.private_mess" + "ages` SET body = 'x'"
    assert _find_violations(bad_sql) != []


def test_guard_ignores_unrelated_sql():
    # A read (SELECT) or a write to some other table is not a violation.
    assert _find_violations("SELECT * FROM `x.private_messages`") == []
    assert _find_violations("UPDATE `x.grant_tickets` SET status = 'closed'") == []


def test_no_tracked_file_writes_to_private_chat_tables():
    offenders = []
    for path in _tracked_py_files():
        for violation in _find_violations(path.read_text()):
            offenders.append(f"{path.relative_to(_REPO_ROOT)} {violation}")
    assert offenders == []
