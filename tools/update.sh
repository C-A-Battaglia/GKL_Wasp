#!/bin/bash
# Downloads the latest WASP Control from GitHub. Run by the
# "Update WASP Control" desktop icon. Saved profiles live in
# ~/.wasp_control and are not touched.

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR" || exit 1

version() { sed -n 's/^__version__ = "\(.*\)"/\1/p' wasp/__init__.py; }
finish() { echo; read -rp "Press Enter to close this window." _; exit "$1"; }

echo "WASP Control updater"
echo "--------------------"
OLD_REV="$(git rev-parse --short HEAD)"
OLD_VER="$(version)"
echo "Installed: v$OLD_VER ($OLD_REV)"
echo

# A pinned release (git checkout v2.0.0) leaves no branch to update; go back to main.
git checkout -q main 2>/dev/null

if ! git pull --ff-only; then
    echo
    echo "UPDATE FAILED - nothing was changed."
    echo " - Check the Pi is connected to Wi-Fi."
    echo " - If files in $APP_DIR were edited by hand, 'git status' lists them."
    finish 1
fi

NEW_REV="$(git rev-parse --short HEAD)"
echo
if [ "$OLD_REV" = "$NEW_REV" ]; then
    echo "Already up to date: v$OLD_VER"
else
    echo "Updated v$OLD_VER -> v$(version)"
    echo
    echo "Changes:"
    git log --no-merges --format='  - %s' "$OLD_REV..$NEW_REV"
fi

bash "$APP_DIR/tools/install_desktop.sh" --quiet

if pgrep -f "wasp_control.py" >/dev/null; then
    echo
    echo "WASP Control is still running the old version."
    echo "Quit it (Setup > QUIT APP) and reopen it from the desktop icon."
fi
finish 0
