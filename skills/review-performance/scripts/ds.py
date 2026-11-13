#!/usr/bin/env python3
"""Run the devskills runtime bundled with this skill: python3 scripts/ds.py <command> [options].

Canonical copy: tools/ds_shim.py. `python3 agent-skills.py sync` copies it into every
skills/*/scripts/ds.py; a test checks the copies stay identical. The syntax stays
compatible with old interpreters so it can print a clear message (or re-launch a
newer Python) instead of failing with a SyntaxError inside a project virtualenv.

Interpreter choice: DEVSKILLS_PYTHON, else the skills' own interpreter recorded at
install time (scripts/_runtime/PYTHON, usually ~/.devskills/venv), else the repo's
.venv for a source checkout, else the interpreter that started this script. The
skills therefore keep their optional packages (Playwright, Pillow, pypdf) even when
an agent runs them inside a project whose own virtualenv is active.
"""
import os
import shutil
import sys

MIN_PYTHON = (3, 11)
HERE = os.path.dirname(os.path.realpath(__file__))


def find_runtime():
    """Vendored runtime (installed skill) or <repo>/src (source checkout / symlinked install)."""
    vendored = os.path.join(HERE, "_runtime")
    if os.path.isfile(os.path.join(vendored, "devskills", "__init__.py")):
        return vendored
    current = HERE
    for _ in range(6):
        current = os.path.dirname(current)
        candidate = os.path.join(current, "src")
        if os.path.isfile(os.path.join(candidate, "devskills", "__init__.py")):
            return candidate
    return None


def venv_python(venv_dir):
    for relative in (os.path.join("bin", "python"), os.path.join("Scripts", "python.exe")):
        candidate = os.path.join(venv_dir, relative)
        if os.path.isfile(candidate):
            return candidate
    return None


def preferred_python(runtime):
    """The interpreter the skills should use, or None to keep the current one."""
    configured = os.environ.get("DEVSKILLS_PYTHON")
    if configured:
        return configured
    recorded = os.path.join(HERE, "_runtime", "PYTHON")
    if os.path.isfile(recorded):
        with open(recorded) as handle:
            candidate = handle.read().strip()
        # A path recorded on another machine (project install committed to git) is simply skipped.
        return candidate if candidate and os.path.isfile(candidate) else None
    if runtime and os.path.basename(runtime) == "src":
        return venv_python(os.path.join(os.path.dirname(runtime), ".venv"))
    return None


def relaunch(interpreter):
    os.environ["DEVSKILLS_RELAUNCHED"] = "1"  # never relaunch twice
    os.execv(interpreter, [interpreter, os.path.realpath(__file__)] + sys.argv[1:])


RUNTIME = find_runtime()
if not os.environ.get("DEVSKILLS_RELAUNCHED"):
    PREFERRED = preferred_python(RUNTIME)
    # Compare unresolved paths: a venv's python is a symlink to the base interpreter but a different environment.
    if PREFERRED and os.path.abspath(PREFERRED) != os.path.abspath(sys.executable):
        relaunch(PREFERRED)
    if sys.version_info[:2] < MIN_PYTHON:
        names = ("python3.15", "python3.14", "python3.13", "python3.12", "python3.11")
        for candidate in (shutil.which(name) for name in names):
            if candidate and os.path.realpath(candidate) != os.path.realpath(sys.executable):
                relaunch(candidate)

if sys.version_info[:2] < MIN_PYTHON:
    sys.stderr.write("devskills needs Python >= %d.%d (found %s at %s). Set DEVSKILLS_PYTHON to a newer python3.\n"
                     % (MIN_PYTHON[0], MIN_PYTHON[1], sys.version.split()[0], sys.executable))
    sys.exit(4)
if RUNTIME is None:
    sys.stderr.write("devskills runtime not found next to %s; reinstall the skills (python3 agent-skills.py install)\n" % HERE)
    sys.exit(4)
sys.path.insert(0, RUNTIME)

from devskills.cli import main  # noqa: E402  (import after sys.path setup)

sys.exit(main())
