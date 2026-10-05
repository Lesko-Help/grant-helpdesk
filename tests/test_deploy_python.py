"""
Proves deploy.sh's own choice of Python for its test step, from
docs/specs/modules/tests.md's live-run R3 and R4.

Input: a copy of deploy.sh, run as a child process from an empty temporary
directory, with a stand-in `gcloud` first on PATH (so this proof can never
ship anything) and PYTHON pointing at a stand-in Python script that only
logs how it was called.
Output: the child's exit code and combined stdout/stderr, whether the
stand-in Python was asked to run `pytest tests/`, and whether the stand-in
`gcloud` was ever invoked.
Why: this never touches BigQuery or Cloud Run, so — unlike the live smoke
test itself — it is safe to run on every commit and every review.
"""

import os
import shutil
import stat
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_FAKE_GCLOUD = """#!/bin/bash
echo called >> "$GCLOUD_CALLED_FILE"
exit 1
"""

# Answers "import pytest" with success (exit 0) so the pytest check passes,
# but logs and fails (exit 1) when asked to run the suite itself — so the
# test can tell deploy.sh actually handed the suite to this stand-in.
_FAKE_PYTHON_WITH_PYTEST = """#!/bin/bash
echo "$@" >> "$PY_CALLS_FILE"
if [ "$1" = "-c" ]; then
    exit 0
fi
exit 1
"""

# Fails every invocation, including the "import pytest" check — stands in
# for a Python that has no pytest installed.
_FAKE_PYTHON_WITHOUT_PYTEST = """#!/bin/bash
echo "$@" >> "$PY_CALLS_FILE"
exit 1
"""


def _write_executable(path, contents):
    """
    Input: a file path and the script text to put there.
    Output: none — the file exists on disk and is executable afterwards.
    Why: every stand-in script below (fake gcloud, fake Python) needs this
    same "write, then chmod +x" step.
    """
    with open(path, "w") as f:
        f.write(contents)
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_deploy_copy(tmp_path, fake_python_script):
    """
    Input: tmp_path (pytest's temp-dir fixture) and the body of the
    stand-in Python script to install as PYTHON.
    Output: the finished subprocess.CompletedProcess (stdout+stderr
    combined onto .stdout), the path the stand-in gcloud writes to if
    called, and the path the stand-in Python logs its arguments to.
    Why: every case below runs the same "copy of deploy.sh, isolated PATH,
    isolated PYTHON" setup, so it is written once here.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    shutil.copy(os.path.join(REPO_ROOT, "deploy.sh"), work_dir / "deploy.sh")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gcloud_called_file = tmp_path / "gcloud_called"
    _write_executable(bin_dir / "gcloud", _FAKE_GCLOUD)

    py_calls_file = tmp_path / "py_calls"
    fake_python = bin_dir / "fake_python"
    _write_executable(fake_python, fake_python_script)

    env = dict(os.environ)
    env.pop("LIVE_SMOKE", None)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["GCLOUD_CALLED_FILE"] = str(gcloud_called_file)
    env["PY_CALLS_FILE"] = str(py_calls_file)
    env["PYTHON"] = str(fake_python)

    result = subprocess.run(
        ["bash", "deploy.sh"],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result.stdout = result.stdout + result.stderr
    return result, gcloud_called_file, py_calls_file


def test_deploy_sh_runs_the_suite_through_the_python_named_by_env_var(tmp_path):
    result, gcloud_called_file, py_calls_file = _run_deploy_copy(
        tmp_path, _FAKE_PYTHON_WITH_PYTEST
    )
    calls = py_calls_file.read_text()
    assert "pytest tests/" in calls, (result.stdout, calls)
    assert result.returncode == 1, result.stdout
    assert not gcloud_called_file.exists(), result.stdout


def test_deploy_sh_checks_for_pytest_before_running_any_test(tmp_path):
    result, gcloud_called_file, py_calls_file = _run_deploy_copy(
        tmp_path, _FAKE_PYTHON_WITHOUT_PYTEST
    )
    assert "fake_python" in result.stdout, result.stdout
    assert "PYTHON=/path/to/python ./deploy.sh" in result.stdout, result.stdout
    calls = py_calls_file.read_text() if py_calls_file.exists() else ""
    assert "pytest tests/" not in calls, (result.stdout, calls)
    assert result.returncode == 1, result.stdout
    assert not gcloud_called_file.exists(), result.stdout


def test_deploy_sh_defaults_to_anaconda_python_when_python_is_unset():
    deploy_sh = os.path.join(REPO_ROOT, "deploy.sh")
    with open(deploy_sh) as f:
        contents = f.read()
    assert "/opt/anaconda3/bin/python3" in contents, contents
