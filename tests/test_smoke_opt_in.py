"""
Proves the LIVE_SMOKE=1 opt-in switch from docs/specs/modules/tests.md.

Input: a child `pytest` process started on tests/smoke_test.py, with
LIVE_SMOKE either absent or set to something other than exactly "1", and with
BigQuery's real Client() replaced (via a sitecustomize.py the child loads at
interpreter startup, before anything else imports) by a stand-in that raises.
Output: the child's pytest report (skip/pass/fail counts) and exit code.
Why: the only way to prove "no BigQuery client is created" without risking the
very production write the switch exists to stop is to make that construction
fail loudly if it is ever attempted, in a separate process so this proof can
never itself touch production.
"""

import os
import subprocess
import sys
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_RAISING_CLIENT_SITECUSTOMIZE = textwrap.dedent(
    """
    from google.cloud import bigquery as _bq

    class _RaisingBigQueryClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "BigQuery client constructed with LIVE_SMOKE unset — "
                "this proof must never be able to reach production"
            )

    _bq.Client = _RaisingBigQueryClient
    """
)


def _run_smoke_tests_guarded(tmp_path, env_overrides):
    """
    Input: tmp_path (a pytest tmp dir fixture value) and env_overrides, a dict
    of environment variables to set on top of a clean copy of this process's
    environment (LIVE_SMOKE is always removed first, regardless of
    env_overrides, so no ambient value leaks in from the caller's shell).
    Output: the finished subprocess.CompletedProcess, stdout+stderr already
    combined onto .stdout for easy assertions.
    Why: every case below needs the same "run smoke_test.py as a guarded
    child process" step, so it is written once here.
    """
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(_RAISING_CLIENT_SITECUSTOMIZE)

    env = dict(os.environ)
    env.pop("LIVE_SMOKE", None)
    env.update(env_overrides)
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/smoke_test.py", "-q", "-rs"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result.stdout = result.stdout + result.stderr
    return result


def test_smoke_tests_skip_when_live_smoke_is_unset(tmp_path):
    result = _run_smoke_tests_guarded(tmp_path, {})
    assert result.returncode == 0, result.stdout
    assert "17 skipped" in result.stdout, result.stdout
    assert "passed" not in result.stdout, result.stdout
    assert "failed" not in result.stdout, result.stdout
    assert "error" not in result.stdout.lower(), result.stdout
    assert "LIVE_SMOKE=1" in result.stdout, result.stdout


def test_smoke_tests_skip_when_live_smoke_is_not_exactly_one(tmp_path):
    result = _run_smoke_tests_guarded(tmp_path, {"LIVE_SMOKE": "true"})
    assert result.returncode == 0, result.stdout
    assert "17 skipped" in result.stdout, result.stdout
    assert "passed" not in result.stdout, result.stdout
    assert "failed" not in result.stdout, result.stdout
    assert "error" not in result.stdout.lower(), result.stdout
    assert "LIVE_SMOKE=1" in result.stdout, result.stdout


def test_deploy_sh_sets_live_smoke_for_its_pytest_run():
    deploy_sh = os.path.join(REPO_ROOT, "deploy.sh")
    with open(deploy_sh) as f:
        lines = f.readlines()

    pytest_lines = [line for line in lines if "pytest tests/" in line]
    assert pytest_lines, "deploy.sh has no line running pytest tests/"
    for line in pytest_lines:
        assert "LIVE_SMOKE=1" in line, (
            f"deploy.sh's pytest line is missing LIVE_SMOKE=1: {line!r}"
        )
