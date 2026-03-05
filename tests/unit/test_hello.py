"""Unit tests for hello.py."""

import subprocess
import sys


def test_hello_output(capsys):
    """hello.py prints 'hello world' to stdout."""
    import importlib.util
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        exec(open("hello.py").read())
    assert f.getvalue().strip() == "hello world"


def test_hello_script_exit_code():
    """hello.py exits with code 0."""
    result = subprocess.run(
        [sys.executable, "hello.py"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert result.returncode == 0


def test_hello_script_stdout():
    """hello.py outputs exactly 'hello world\\n'."""
    result = subprocess.run(
        [sys.executable, "hello.py"],
        capture_output=True,
        text=True,
    )
    assert result.stdout == "hello world\n"
    assert result.stderr == ""
