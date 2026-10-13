#!/bin/bash
# Adds two icons to the Pi desktop (and the app menu):
#   WASP Control         - starts the app fullscreen
#   Update WASP Control  - downloads the latest version from GitHub
#
#   bash ~/GKL_Wasp/tools/install_desktop.sh               # icons only
#   bash ~/GKL_Wasp/tools/install_desktop.sh --autostart   # also start the app at login
#
# Safe to run again; the updater re-runs it after every update.

set -e
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[ -n "$DESKTOP_DIR" ] || DESKTOP_DIR="$HOME/Desktop"
MENU_DIR="$HOME/.local/share/applications"
QUIET=0
AUTOSTART=0
for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=1 ;;
        --autostart) AUTOSTART=1 ;;
    esac
done
say() { [ "$QUIET" = 1 ] || echo "$@"; }

mkdir -p "$DESKTOP_DIR" "$MENU_DIR"
chmod +x "$APP_DIR/tools/update.sh" "$APP_DIR/wasp_control.py"

write_entry() {  # file name comment exec icon terminal
    cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=$4
Path=$APP_DIR
Icon=$APP_DIR/assets/$5
Terminal=$6
Categories=Utility;
EOF
    chmod +x "$1"
    # GNOME-style desktops won't launch untrusted .desktop files; harmless elsewhere.
    gio set "$1" metadata::trusted true 2>/dev/null || true
}

for dir in "$DESKTOP_DIR" "$MENU_DIR"; do
    write_entry "$dir/wasp-control.desktop" "WASP Control" \
        "Extruder + feeder touchscreen controller" \
        "python3 $APP_DIR/wasp_control.py --fullscreen" wasp-control.png false
    write_entry "$dir/wasp-update.desktop" "Update WASP Control" \
        "Download the latest WASP Control from GitHub" \
        "bash $APP_DIR/tools/update.sh" wasp-update.png true
done
say "Icons added to $DESKTOP_DIR and the app menu."

# Raspberry Pi OS file manager asks "Execute / Execute in terminal?" every time
# a desktop icon is opened. Turn that prompt off so one tap opens the app.
LIBFM="$HOME/.config/libfm/libfm.conf"
if [ -f "$LIBFM" ]; then
    if grep -q '^quick_exec=' "$LIBFM"; then
        sed -i 's/^quick_exec=.*/quick_exec=1/' "$LIBFM"
    elif grep -q '^\[config\]' "$LIBFM"; then
        sed -i '/^\[config\]/a quick_exec=1' "$LIBFM"
    fi
fi

if [ "$AUTOSTART" = 1 ]; then
    mkdir -p "$HOME/.config/autostart"
    cp "$MENU_DIR/wasp-control.desktop" "$HOME/.config/autostart/wasp-control.desktop"
    say "WASP Control will also start automatically at login."
fi
