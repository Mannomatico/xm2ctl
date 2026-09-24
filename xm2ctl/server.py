"""Local web UI and battery monitor for the XM2w 4k.

Run with:  python3 -m xm2ctl.server [--port 8341]

The server only listens on 127.0.0.1. Requests with a foreign Host or Origin
header are rejected (DNS rebinding / cross-site protection), and every write
needs the per-start token that is embedded in the served page. The token is
also written to $XDG_RUNTIME_DIR/xm2ctl/token (readable by the user only) for
the GNOME Shell extension.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import profiles
from .__main__ import save_backup
from .device import ActivityWatch, Device, DeviceError, MouseAsleep
from .keys import MEDIA
from .protocol import (
    CPI_MAX,
    CPI_MIN,
    CPI_STEP,
    DEBOUNCE_MAX_MS,
    FILTER_BUTTONS,
    SPDT_BUTTONS,
    TIMER_MAX,
    TIMER_MIN,
    Config,
)
from .settings import apply_json, config_to_json

HOST = "127.0.0.1"
DEFAULT_PORT = 8341
WEB_ROOT = Path(__file__).parent / "web"
STATIC_FILES = {
    "/app.js": "text/javascript; charset=utf-8",
    "/style.css": "text/css; charset=utf-8",
}
MAX_BODY = 64 * 1024
ACTIVITY_TICK = 10  # seconds between checks for mouse movement
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR")


# --- device service ----------------------------------------------------------

def notify(title: str, body: str) -> None:
    """Show a desktop notification via the freedesktop D-Bus API (no extra packages)."""
    subprocess.run(
        ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
         "--object-path", "/org/freedesktop/Notifications",
         "--method", "org.freedesktop.Notifications.Notify",
         "XM2w 4k", "0", "input-mouse", title, body, "[]", "{}", "10000"],
        check=False, capture_output=True, timeout=5,
    )


class MouseService:
    def __init__(self, low_battery: int, interval: int) -> None:
        self.lock = threading.Lock()  # one hidraw conversation at a time
        self.low_battery = low_battery
        self.interval = interval
        self.battery: int | None = None
        self.connection: str | None = None  # "wired", "wireless" or None if not found
        self.battery_time: float | None = None
        self.warned = False
        self._firmware: dict[tuple[str, int], dict] = {}
        self.settings: dict | None = None  # last settings read from or written to the mouse
        self._last_error: str | None = None
        self.activity = ActivityWatch()
        # Shorter of the power saving and deep sleep timers in seconds (None = both off);
        # until the config was read once, assume the shortest possible timer.
        self.idle_limit: float | None = 60.0
        self.asleep = False  # the last battery check was skipped because the mouse slept
        self.blocked_at: float | None = None  # a command failed; wait for new movement

    def _open(self) -> Device:
        """Open the device, refusing to talk to a mouse that may be asleep.

        Over the receiver, a command for a mouse in power saving or deep sleep can block
        the receiver until it is replugged, so only talk while the mouse is in use.
        """
        dev = Device()
        if not dev.is_wired:
            awake = self.activity.awake(self.idle_limit)
            if self.blocked_at is not None:
                if (self.activity.moved_at or 0) > self.blocked_at:
                    self.blocked_at = None
                else:
                    awake = False
            if not awake:
                dev.close()
                raise MouseAsleep()
        return dev

    @contextlib.contextmanager
    def _talk(self, dev: Device):
        """Use an open device; after a failed command, wait for new movement before retrying."""
        try:
            with dev:
                yield dev
        except DeviceError:
            if not dev.is_wired:
                self.blocked_at = time.monotonic()
            raise

    def _session(self):
        return self._talk(self._open())

    def _remember(self, cfg: Config) -> dict:
        self.settings = config_to_json(cfg)
        timers = [self.settings[name] for name in ("power_saving", "deep_sleep")]
        limits = [timer["minutes"] * 60.0 for timer in timers if timer["enabled"]]
        self.idle_limit = min(limits) if limits else None
        return self.settings

    def _log_device(self, error: Exception | None) -> None:
        """Log device errors to the journal, once per change instead of every poll."""
        message = None if error is None else f"{type(error).__name__}: {error}"
        if message != self._last_error:
            print(f"device: {message or 'available again'}", file=sys.stderr, flush=True)
            self._last_error = message

    def _record_battery(self, percent: int, dev: Device) -> None:
        self.battery = percent
        self.connection = "wired" if dev.is_wired else "wireless"
        self.battery_time = time.time()
        if percent <= self.low_battery and not self.warned:
            notify("Mouse battery low", f"XM2w 4k is at {percent} %. Plug in the cable to charge.")
            self.warned = True
        elif percent > self.low_battery + 5:
            self.warned = False

    def _firmware_info(self, dev: Device) -> dict:
        key = (str(dev.path), dev.product_id)
        if key not in self._firmware:
            self._firmware[key] = {"mouse": dev.mouse_firmware(), "dongle": dev.dongle_firmware()}
        return self._firmware[key]

    def state(self) -> dict:
        with self.lock:
            try:
                with self._session() as dev:
                    battery = dev.battery_percent()
                    self._record_battery(battery, dev)
                    self._log_device(None)
                    return {
                        "connected": True,
                        "connection": "wired" if dev.is_wired else "wireless",
                        "firmware": self._firmware_info(dev),
                        "battery": battery,
                        "keyboard_fix": dev.keyboard_fix,
                        "settings": self._read_settings(dev),
                    }
            except MouseAsleep as exc:
                self._log_device(exc)
                return {"connected": False, "asleep": True, "error": str(exc)}
            except (DeviceError, OSError) as exc:
                self._log_device(exc)
                self._firmware.clear()
                self.settings = None
                return {"connected": False, "error": str(exc)}

    def _read_settings(self, dev: Device) -> dict:
        return self._remember(dev.read_config())

    def battery_status(self) -> dict:
        """Cached battery state for the panel indicator; never talks to the mouse."""
        age = None if self.battery_time is None else round(time.time() - self.battery_time)
        last = self.activity.last_activity
        return {
            "idle": None if last is None else round(time.monotonic() - last),
            "connected": self.connection is not None,
            "connection": self.connection,
            "battery": self.battery,
            "age": age,
            "low": self.battery is not None and self.battery <= self.low_battery,
        }

    def apply(self, data: dict) -> dict:
        with self.lock:
            with self._session() as dev:
                old = dev.read_config()
                new = old.copy()
                apply_json(new, data, dev.is_wired)
                if new.diff(old):
                    save_backup(old)
                    dev.write_config(old, new)
                self._remember(new)
        return self.state()

    def profiles(self) -> dict:
        """Saved profiles and the one matching the cached mouse settings (never reads the mouse)."""
        stored = profiles.load_all()
        wired = self.connection == "wired"
        active = None
        if self.settings is not None:
            active = next((name for name, settings in stored.items()
                           if profiles.matches(settings, self.settings, wired)), None)
        return {"profiles": [{"name": name, "settings": settings} for name, settings in stored.items()],
                "active": active}

    def apply_profile(self, name: str) -> dict:
        settings = profiles.load(name)
        with self.lock:
            with self._session() as dev:
                old = dev.read_config()
                new = old.copy()
                notes = profiles.apply(new, settings, dev.is_wired)
                if new.diff(old):
                    save_backup(old)
                    dev.write_config(old, new)
                self._remember(new)
        return {**self.profiles(), "notes": notes}

    def save_profile(self, name: str, settings: dict) -> dict:
        """Validate settings against the current config and store them; nothing is written."""
        name = profiles.check_name(name)
        with self.lock:
            with self._session() as dev:
                cfg = dev.read_config()
        apply_json(cfg, settings, wired=False)
        profiles.save(name, config_to_json(cfg))
        return self.profiles()

    def delete_profile(self, name: str) -> dict:
        profiles.delete(name)
        return self.profiles()

    def check_battery(self) -> None:
        with self.lock:
            try:
                dev = self._open()
            except MouseAsleep as exc:
                self._log_device(exc)  # keep the last known battery value
                self.asleep = True
                return
            except (DeviceError, OSError) as exc:
                self._log_device(exc)
                self.connection = None  # receiver or cable unplugged
                self.settings = None
                return
            self.asleep = False
            try:
                with self._talk(dev):
                    self._record_battery(dev.battery_percent(), dev)
                    if self.settings is None:  # once per connection, for the active profile
                        self._read_settings(dev)
                self._log_device(None)
            except (DeviceError, OSError) as exc:
                self._log_device(exc)  # out of range: keep the last known battery value

    def monitor(self) -> None:
        last_poll = None
        while True:
            # Look for movement often, so the time of the last activity stays accurate.
            with self.lock:
                self.activity.check()
                woke = self.asleep and self.activity.awake(self.idle_limit)
            # Until the mouse was found (for example before the udev permissions are set
            # after login), retry every tick; that only reads sysfs.
            retry = self.connection is None and not self.asleep
            if woke or retry or last_poll is None or time.monotonic() - last_poll >= self.interval:
                last_poll = time.monotonic()
                self.check_battery()
            time.sleep(ACTIVITY_TICK)


# --- HTTP --------------------------------------------------------------------

def make_handler(service: MouseService, token: str, port: int):
    allowed_hosts = {f"{HOST}:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{host}" for host in allowed_hosts}
    limits = {
        "cpi_min": CPI_MIN, "cpi_max": CPI_MAX, "cpi_step": CPI_STEP,
        "debounce_max": DEBOUNCE_MAX_MS, "timer_min": TIMER_MIN, "timer_max": TIMER_MAX,
        "spdt_buttons": list(SPDT_BUTTONS), "filter_buttons": list(FILTER_BUTTONS),
        "media": list(MEDIA),
    }
    post_routes = {
        "/api/settings": lambda data: {**service.apply(data), "limits": limits},
        "/api/profiles/save": lambda data: service.save_profile(data["name"], data["settings"]),
        "/api/profiles/delete": lambda data: service.delete_profile(data["name"]),
        "/api/profiles/apply": lambda data: service.apply_profile(data["name"]),
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "xm2ctl"

        def log_message(self, *_args) -> None:
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _trusted(self) -> bool:
            if self.headers.get("Host") not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in allowed_origins

        def do_GET(self) -> None:
            if not self._trusted():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            if self.path == "/":
                html = (WEB_ROOT / "index.html").read_text().replace("{{TOKEN}}", token)
                return self._send(HTTPStatus.OK, html.encode(), "text/html; charset=utf-8")
            if self.path in STATIC_FILES:
                body = (WEB_ROOT / self.path.lstrip("/")).read_bytes()
                return self._send(HTTPStatus.OK, body, STATIC_FILES[self.path])
            if self.path == "/api/battery":
                return self._json(HTTPStatus.OK, service.battery_status())
            if self.path == "/api/state":
                return self._json(HTTPStatus.OK, {**service.state(), "limits": limits})
            if self.path == "/api/profiles":
                return self._json(HTTPStatus.OK, service.profiles())
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            route = post_routes.get(self.path)
            if (not self._trusted() or route is None
                    or not secrets.compare_digest(self.headers.get("X-XM2-Token", ""), token)
                    or self.headers.get("Content-Type") != "application/json"):
                return self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid request size"})
            try:
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("expected a JSON object")
                result = route(data)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except (DeviceError, OSError) as exc:
                return self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            self._json(HTTPStatus.OK, result)

    return Handler


def write_token(token: str) -> None:
    """Store the write token for the GNOME Shell extension, readable by the user only."""
    if not RUNTIME_DIR:
        return
    directory = Path(RUNTIME_DIR) / "xm2ctl"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / "token"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(token)
    os.chmod(path, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(prog="xm2ctl.server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--low-battery", type=int, default=20, help="warn at or below this percentage")
    parser.add_argument("--interval", type=int, default=120, help="battery check interval in seconds")
    args = parser.parse_args()

    service = MouseService(args.low_battery, args.interval)
    threading.Thread(target=service.monitor, daemon=True).start()
    token = secrets.token_urlsafe(32)
    write_token(token)
    httpd = ThreadingHTTPServer((HOST, args.port), make_handler(service, token, args.port))

    def stop(_signum, _frame) -> None:
        # Let a running conversation with the mouse finish; an interrupted command can
        # leave the receiver stuck until it is replugged.
        service.lock.acquire(timeout=20)
        os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    print(f"xm2ctl web UI on http://{HOST}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
