"""
Source-level guards for the two raillog.py copies (docs/specs/modules/raillog.md,
R3, R5, R6).

Why it reads source and not output: a test that runs alert() and reads back
what it printed (capsys, subprocess stdout) sees the line whether or not
flush=True is there, because the buffer empties when the process ends. It
cannot tell a flushed print from an unflushed one. So every guard here parses
the file with `ast` and never runs it.

Each guard is a function from source text to a list of problems (empty list =
holds). The real files are checked green; the same functions are then fed
small mutated copies held in memory, and must come back red. That is the
"prove a guard can go red" step, kept in the suite so it reruns every time.
"""

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPIES = {
    "raillog.py": os.path.join(ROOT, "raillog.py"),
    "jobs/raillog.py": os.path.join(ROOT, "jobs", "raillog.py"),
}


def read_source(path):
    """Input: a file path. Output: its text. Why: one place that opens the files."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def check_marker_prints_flush(source):
    """R3: every print in the whole file whose source carries BTB_ALERT has flush=True.

    Input: Python source text. Output: a list of problems, empty when the rule
    holds. Like a CHECK constraint over every row of the file: not just the
    rows inside alert(), so a marker print added next month is covered too.
    A print with a file= keyword (stderr, line-buffered) is exempt. Finding
    no marker print at all is itself a problem, so the guard cannot pass
    vacuously the day the helper stops printing.
    """
    tree = ast.parse(source)
    problems = []
    marker_prints_seen = 0
    for node in ast.walk(tree):
        is_print = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        )
        if not is_print:
            continue
        if "BTB_ALERT" not in (ast.get_source_segment(source, node) or ""):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        if "file" in keywords:
            continue
        marker_prints_seen += 1
        flush_value = keywords.get("flush")
        flushed = isinstance(flush_value, ast.Constant) and flush_value.value is True
        if not flushed:
            problems.append(f"line {node.lineno}: BTB_ALERT print without flush=True")
    if marker_prints_seen == 0:
        problems.append("no BTB_ALERT print found (guard would pass vacuously)")
    return problems


def check_repo_is_literal(source):
    """R5: REPO is assigned a string literal at module level, never computed.

    Input: Python source text. Output: a list of problems, empty when it
    holds. Why: the alert text names the repo, and reading it from the
    environment would let a deploy setting rename every alert silently.
    """
    tree = ast.parse(source)
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "REPO" for target in node.targets)
    ]
    if not assignments:
        return ["no module-level REPO assignment"]
    problems = []
    for node in assignments:
        if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            problems.append(f"line {node.lineno}: REPO is not a string literal")
    return problems


def code_without_comments_and_docstrings(source):
    """Input: Python source text. Output: a string of the code's syntax tree.

    Comments never reach the syntax tree; docstrings are dropped here. What is
    left is the code alone, so two files that differ only in explanation
    produce the same string.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            first_is_docstring = (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            )
            if first_is_docstring:
                node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree)


def check_copies_equal(source_a, source_b):
    """R6: the two copies are the same code once comments and docstrings go.

    Input: two source texts. Output: a list of problems, empty when equal.
    Like comparing two tables with EXCEPT in both directions: any difference
    in code is a drift between the app copy and the job copy.
    """
    if code_without_comments_and_docstrings(source_a) != code_without_comments_and_docstrings(source_b):
        return ["the two copies differ in code, not only in comments or docstrings"]
    return []


# ---- the real files: green ----

def test_every_marker_print_flushes_in_both_copies():
    for name, path in COPIES.items():
        assert check_marker_prints_flush(read_source(path)) == [], name


def test_repo_is_a_string_literal_in_both_copies():
    for name, path in COPIES.items():
        assert check_repo_is_literal(read_source(path)) == [], name


def test_repo_is_grant_helpdesk_in_both_copies():
    for name, path in COPIES.items():
        tree = ast.parse(read_source(path))
        values = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "REPO" for t in node.targets)
        ]
        assert values == ["grant-helpdesk"], name


def test_the_two_copies_hold_the_same_code():
    assert check_copies_equal(
        read_source(COPIES["raillog.py"]), read_source(COPIES["jobs/raillog.py"])
    ) == []


# ---- the same guards against mutated copies: red ----

def test_flush_guard_goes_red_when_flush_is_deleted():
    mutated = read_source(COPIES["raillog.py"]).replace("}), flush=True)", "}))")
    assert mutated != read_source(COPIES["raillog.py"])
    assert check_marker_prints_flush(mutated) != []


def test_flush_guard_goes_red_for_a_marker_print_outside_alert():
    extra = '\nprint("BTB_ALERT x/y UNEXPECTED: late addition")\n'
    assert check_marker_prints_flush(read_source(COPIES["raillog.py"]) + extra) != []


def test_flush_guard_exempts_a_stderr_print():
    source = read_source(COPIES["raillog.py"]) + (
        '\nimport sys\nprint("BTB_ALERT x/y UNEXPECTED: z", file=sys.stderr)\n'
    )
    assert check_marker_prints_flush(source) == []


def test_flush_guard_goes_red_when_there_is_no_marker_print():
    assert check_marker_prints_flush('REPO = "grant-helpdesk"\n\ndef alert():\n    pass\n') != []


def test_repo_guard_goes_red_when_repo_reads_the_environment():
    mutated = read_source(COPIES["raillog.py"]).replace(
        'REPO = "grant-helpdesk"', 'REPO = os.environ["REPO"]'
    )
    assert check_repo_is_literal(mutated) != []


def test_repo_guard_goes_red_when_repo_is_missing():
    assert check_repo_is_literal("CODES = set()\n") != []


def test_equality_guard_goes_red_on_one_changed_line_of_code():
    original = read_source(COPIES["jobs/raillog.py"])
    mutated = original.replace('code = "UNEXPECTED"', 'code = "STALE"')
    assert mutated != original
    assert check_copies_equal(original, mutated) != []


def test_equality_guard_ignores_a_changed_comment_and_docstring():
    original = read_source(COPIES["jobs/raillog.py"])
    changed = original.replace("# flush=True", "# a different comment, flush=True", 1)
    changed = changed.replace("Log one structured ERROR line", "Write one ERROR line", 1)
    assert changed != original
    assert check_copies_equal(original, changed) == []
