// SPDX-License-Identifier: MIT
// Top bar battery indicator for the Endgame Gear XM2w 4k, fed by the local xm2ctl service.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Soup from 'gi://Soup';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const SERVICE_URL = 'http://127.0.0.1:8341';
const REFRESH_SECONDS = 30;

export default class Xm2ctlBatteryExtension extends Extension {
    enable() {
        this._session = new Soup.Session({timeout: 5});
        this._cancellable = new Gio.Cancellable();

        this._indicator = new PanelMenu.Button(0.0, this.metadata.name, false);
        const box = new St.BoxLayout();
        this._icon = new St.Icon({
            icon_name: 'input-mouse-symbolic',
            style_class: 'system-status-icon',
        });
        this._label = new St.Label({
            text: '',
            style_class: 'xm2ctl-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._icon);
        box.add_child(this._label);
        this._indicator.add_child(box);

        this._statusItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._indicator.menu.addMenuItem(this._statusItem);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._indicator.menu.addAction('Open mouse settings', () => {
            Gio.AppInfo.launch_default_for_uri(SERVICE_URL, null);
        });

        this._indicator.visible = false;
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        this._refresh();
        this._timeoutId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, REFRESH_SECONDS, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        if (this._timeoutId) {
            GLib.source_remove(this._timeoutId);
            this._timeoutId = null;
        }
        this._cancellable?.cancel();
        this._cancellable = null;
        this._session?.abort();
        this._session = null;
        this._indicator?.destroy();
        this._indicator = null;
        this._icon = null;
        this._label = null;
        this._statusItem = null;
    }

    _refresh() {
        const message = Soup.Message.new('GET', `${SERVICE_URL}/api/battery`);
        this._session.send_and_read_async(message, GLib.PRIORITY_DEFAULT, this._cancellable,
            (session, result) => {
                let status = null;
                try {
                    const bytes = session.send_and_read_finish(result);
                    if (message.get_status() === Soup.Status.OK)
                        status = JSON.parse(new TextDecoder().decode(bytes.get_data()));
                } catch (error) {
                    if (error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        return;
                }
                this._show(status);
            });
    }

    _show(status) {
        if (!this._indicator)
            return;

        // Hide the indicator while the service is down or no mouse is connected.
        if (!status || !status.connected || status.battery === null) {
            this._indicator.visible = false;
            return;
        }

        const wired = status.connection === 'wired';
        this._indicator.visible = true;
        this._label.text = `${status.battery} %`;
        if (status.low && !wired)
            this._label.add_style_class_name('xm2ctl-low');
        else
            this._label.remove_style_class_name('xm2ctl-low');

        const via = wired ? 'Charging over cable' : 'Wireless';
        this._statusItem.label.text = `XM2w 4k: ${status.battery} %, ${via}`;
    }
}
