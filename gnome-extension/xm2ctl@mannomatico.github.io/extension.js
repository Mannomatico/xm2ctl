// SPDX-License-Identifier: MIT
// Top bar battery indicator and profile switcher for the Endgame Gear XM2w 4k,
// fed by the local xm2ctl service.

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
// Written by the service on every start, readable by the user only.
const TOKEN_PATH = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'xm2ctl', 'token']);

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
        this._profileSection = new PopupMenu.PopupMenuSection();
        this._indicator.menu.addMenuItem(this._profileSection);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._indicator.menu.addAction('Open mouse settings', () => {
            Gio.AppInfo.launch_default_for_uri(SERVICE_URL, null);
        });

        this._indicator.menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._refreshProfiles();
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
        this._profileSection = null;
    }

    // Sends a request and calls done(status code, parsed JSON or null). Never called after disable.
    _request(method, path, body, done) {
        const message = Soup.Message.new(method, `${SERVICE_URL}${path}`);
        if (body) {
            const token = this._readToken();
            if (token)
                message.request_headers.append('X-XM2-Token', token);
            message.set_request_body_from_bytes('application/json',
                new GLib.Bytes(new TextEncoder().encode(JSON.stringify(body))));
        }
        this._session.send_and_read_async(message, GLib.PRIORITY_DEFAULT, this._cancellable,
            (session, result) => {
                let data = null;
                try {
                    const bytes = session.send_and_read_finish(result);
                    data = JSON.parse(new TextDecoder().decode(bytes.get_data()));
                } catch (error) {
                    if (error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        return;
                }
                done(message.get_status(), data);
            });
    }

    _readToken() {
        try {
            const [, contents] = GLib.file_get_contents(TOKEN_PATH);
            return new TextDecoder().decode(contents).trim();
        } catch {
            return null;
        }
    }

    _refresh() {
        this._request('GET', '/api/battery', null, (code, status) => {
            this._show(code === Soup.Status.OK ? status : null);
        });
    }

    _refreshProfiles() {
        this._request('GET', '/api/profiles', null, (code, data) => {
            this._showProfiles(code === Soup.Status.OK ? data : null);
        });
    }

    _showProfiles(data) {
        if (!this._profileSection)
            return;
        this._profileSection.removeAll();
        if (!data || !data.profiles.length)
            return;

        this._profileSection.addMenuItem(new PopupMenu.PopupSeparatorMenuItem('Profiles'));
        for (const {name} of data.profiles) {
            const item = new PopupMenu.PopupMenuItem(name);
            item.setOrnament(name === data.active ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
            item.connect('activate', () => this._applyProfile(name));
            this._profileSection.addMenuItem(item);
        }
    }

    _applyProfile(name) {
        this._request('POST', '/api/profiles/apply', {name}, (code, data) => {
            if (code !== Soup.Status.OK) {
                const reason = data?.error ?? 'The xm2ctl service did not respond.';
                Main.notify('XM2w 4k', `Profile ${name} not applied: ${reason}`);
                return;
            }
            const notes = data.notes?.length ? `\n${data.notes.join('\n')}` : '';
            Main.notify('XM2w 4k', `Profile ${name} is active.${notes}`);
            this._showProfiles(data);
        });
    }

    _show(status) {
        if (!this._indicator)
            return;

        // Hide the indicator while the service is down or no mouse is connected.
        if (!status || !status.connected || status.battery === null) {
            this._indicator.visible = false;
            this._indicator.menu.close();
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
