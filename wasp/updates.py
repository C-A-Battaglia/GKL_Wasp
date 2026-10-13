"""
Checks GitHub for a newer version. Never installs anything: installing is
left to the "Update WASP Control" desktop icon (tools/update.sh), so code
only changes on the machine when the operator chooses.

check() blocks for up to a few seconds, so the GUI runs it on a thread.
"""

import os
import re
import subprocess
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_EVERY_S = 6 * 3600   # re-check if the app is left open all day

# Result statuses
CHECKING = "checking"
AVAILABLE = "available"
CURRENT = "current"
OFFLINE = "offline"          # git works but GitHub couldn't be reached
UNAVAILABLE = "unavailable"  # not a git checkout / git missing


def _version_from(source):
    m = re.search(r'^__version__ = "([^"]+)"', source, re.M)
    return m.group(1) if m else "?"


def check(app_dir=APP_DIR, timeout=20):
    """Return {"status", "behind", "remote_version", "checked"}."""
    # Never prompt for a password or SSH passphrase; just fail quietly.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0",
               GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10")

    def git(*args):
        return subprocess.run(["git", "-C", app_dir, *args], capture_output=True, text=True,
                              timeout=timeout, env=env, check=True).stdout.strip()

    result = {"status": UNAVAILABLE, "behind": 0, "remote_version": None, "checked": time.time()}
    try:
        git("rev-parse", "--git-dir")
    except (OSError, subprocess.SubprocessError):
        return result
    try:
        git("fetch", "--quiet", "origin", "main")
        behind = int(git("rev-list", "--count", "HEAD..origin/main"))
        remote_version = _version_from(git("show", "origin/main:wasp/__init__.py"))
    except (OSError, subprocess.SubprocessError, ValueError):
        result["status"] = OFFLINE
        return result
    result.update(status=AVAILABLE if behind else CURRENT, behind=behind,
                  remote_version=remote_version)
    return result
