"""Local web UI and battery monitor for the XM2w 4k.

Run with:  python3 -m xm2ctl.server [--port 8341]

The server only listens on 127.0.0.1. Requests with a foreign Host or Origin
header are rejected (DNS rebinding / cross-site protection), and every write
needs the per-start token that is embedded in the served page.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import profiles
from .__main__ import save_backup
from .device import Device, DeviceError
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
                with Device() as dev:
                    battery = dev.battery_percent()
                    self._record_battery(battery, dev)
                    return {
                        "connected": True,
                        "connection": "wired" if dev.is_wired else "wireless",
                        "firmware": self._firmware_info(dev),
                        "battery": battery,
                        "keyboard_fix": dev.keyboard_fix,
                        "settings": config_to_json(dev.read_config()),
                    }
            except (DeviceError, OSError) as exc:
                self._firmware.clear()
                return {"connected": False, "error": str(exc)}

    def battery_status(self) -> dict:
        """Cached battery state for the panel indicator; never talks to the mouse."""
        age = None if self.battery_time is None else round(time.time() - self.battery_time)
        return {
            "connected": self.connection is not None,
            "connection": self.connection,
            "battery": self.battery,
            "age": age,
            "low": self.battery is not None and self.battery <= self.low_battery,
        }

    def apply(self, data: dict) -> dict:
        with self.lock:
            with Device() as dev:
                old = dev.read_config()
                new = old.copy()
                apply_json(new, data, dev.is_wired)
                if new.diff(old):
                    save_backup(old)
                    dev.write_config(old, new)
        return self.state()

    @staticmethod
    def profiles() -> dict:
        return {"profiles": [{"name": name, "settings": settings}
                             for name, settings in profiles.load_all().items()]}

    def save_profile(self, name: str, settings: dict) -> dict:
        """Validate settings against the current config and store them; nothing is written."""
        name = profiles.check_name(name)
        with self.lock:
            with Device() as dev:
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
                dev = Device()
            except (DeviceError, OSError):
                self.connection = None  # receiver or cable unplugged
                return
            try:
                with dev:
                    self._record_battery(dev.battery_percent(), dev)
            except (DeviceError, OSError):
                pass  # mouse asleep: keep the last known value

    def monitor(self) -> None:
        while True:
            self.check_battery()
            time.sleep(self.interval)


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="xm2ctl.server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--low-battery", type=int, default=20, help="warn at or below this percentage")
    parser.add_argument("--interval", type=int, default=120, help="battery check interval in seconds")
    args = parser.parse_args()

    service = MouseService(args.low_battery, args.interval)
    threading.Thread(target=service.monitor, daemon=True).start()
    token = secrets.token_urlsafe(32)
    httpd = ThreadingHTTPServer((HOST, args.port), make_handler(service, token, args.port))
    print(f"xm2ctl web UI on http://{HOST}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
