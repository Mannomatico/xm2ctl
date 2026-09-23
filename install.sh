#!/bin/sh
# Install xm2ctl for the current user: package, web UI service, launcher, udev rule.
set -eu
cd "$(dirname "$0")"

mkdir -p ~/.local/share/xm2ctl ~/.config/systemd/user ~/.local/share/applications
rm -rf ~/.local/share/xm2ctl/xm2ctl
cp -r xm2ctl ~/.local/share/xm2ctl/
cp packaging/xm2ctl.service ~/.config/systemd/user/
cp packaging/xm2ctl.desktop ~/.local/share/applications/

if ! cmp -s packaging/70-endgamegear.rules /etc/udev/rules.d/70-endgamegear.rules; then
    sudo cp packaging/70-endgamegear.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules
    sudo udevadm trigger
fi

# GNOME top bar battery indicator
EXT_UUID=xm2ctl@mannomatico.github.io
if command -v gnome-shell >/dev/null 2>&1; then
    EXT_DIR=~/.local/share/gnome-shell/extensions/$EXT_UUID
    rm -rf "$EXT_DIR"
    mkdir -p "$EXT_DIR"
    cp gnome-extension/$EXT_UUID/* "$EXT_DIR/"
    # Make sure the running GNOME version is listed, otherwise the extension is refused.
    SHELL_MAJOR=$(gnome-shell --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')
    python3 - "$EXT_DIR/metadata.json" "$SHELL_MAJOR" <<'PY'
import json, sys
path, major = sys.argv[1], sys.argv[2]
meta = json.load(open(path))
if major not in meta["shell-version"]:
    meta["shell-version"].append(major)
json.dump(meta, open(path, "w"), indent=2)
PY
    if [ "$(gsettings get org.gnome.shell disable-user-extensions 2>/dev/null)" = "true" ]; then
        echo "Note: user extensions are disabled in GNOME. Enable them with:"
        echo "  gsettings set org.gnome.shell disable-user-extensions false"
    fi
    gnome-extensions enable "$EXT_UUID" 2>/dev/null \
        || echo "Log out and back in, then run: gnome-extensions enable $EXT_UUID"
fi

systemctl --user daemon-reload
systemctl --user enable xm2ctl.service
systemctl --user restart xm2ctl.service
echo "Done. Open http://127.0.0.1:8341 or start 'XM2w 4k' from the app grid."
