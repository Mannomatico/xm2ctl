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

systemctl --user daemon-reload
systemctl --user enable xm2ctl.service
systemctl --user restart xm2ctl.service
echo "Done. Open http://127.0.0.1:8341 or start 'XM2w 4k' from the app grid."
