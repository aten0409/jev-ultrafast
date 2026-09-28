"""Loopback-only inspector for the Jev browser agent."""

import atexit
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from browser_harness.admin import daemon_alive
from browser_harness.helpers import cdp

from .agent import Agent
from .questions import MAX_STEPS

ROOT = Path(__file__).parent
PORT = int(os.environ.get("TYPESAFE_DEMO_PORT", "8766"))
ORIGIN = f"http://127.0.0.1:{PORT}"
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
AGENT = None


def start_demo_chrome():
    """Use an isolated Chrome for the Windows inspector, without changing the user's profile."""
    if os.environ.get("JEV_BROWSER_MODE") == "personal":
        return None
    if sys.platform != "win32" or os.environ.get("BU_CDP_URL") or os.environ.get("BU_CDP_WS"):
        return None
    if daemon_alive():
        try:
            cdp("Target.getTargets")
            if "HeadlessChrome" in cdp("Browser.getVersion").get("userAgent", ""):
                os.environ["JEV_DEDICATED_CHROME"] = "1"
            return None
        except (OSError, RuntimeError, TimeoutError):
            pass
    candidates = [
        os.environ.get("BH_CHROME_PATH"),
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"),
        str(
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            / "Google/Chrome/Application/chrome.exe"
        ),
    ]
    chrome = next((path for path in candidates if path and Path(path).is_file()), None)
    if chrome is None:
        return None
    profile = Path.cwd() / "artifacts" / "chrome-demo"
    profile.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [chrome, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
         "--no-first-run", "about:blank"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    active_port = profile / "DevToolsActivePort"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            port, ws_path = active_port.read_text(encoding="utf-8").splitlines()[:2]
            port = int(port)
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                if json.load(response).get("webSocketDebuggerUrl", "").endswith(ws_path):
                    os.environ["BU_CDP_URL"] = f"http://127.0.0.1:{port}"
                    os.environ["JEV_DEDICATED_CHROME"] = "1"
                    return process if process.poll() is None else None
        except (FileNotFoundError, IndexError, OSError, ValueError):
            pass
        if process.poll() is not None:
            break
        time.sleep(0.1)
    if process.poll() is None:
        process.terminate()
    raise RuntimeError("Dedicated Chrome did not expose a DevTools port; see artifacts/chrome-demo")


def stop_demo_chrome(process):
    if process.poll() is None:
        process.terminate()


def response_state():
    state = AGENT.snapshot() if AGENT else {"page": None, "status": "idle", "history": [], "decision": None}
    return {**state, "text_model": os.environ.get("TEXT_MODEL", "deepseek-chat"), "max_steps": MAX_STEPS}


def close_browser():
    global AGENT
    if AGENT:
        AGENT.close()
        AGENT = None


def require_personal_chrome():
    """Let Browser Harness discover the visible Chrome with its patient local handshake."""
    if sys.platform != "win32":
        raise RuntimeError("Personal Chrome mode currently supports Windows only")
    if os.environ.get("BU_CDP_URL") or os.environ.get("BU_CDP_WS"):
        raise RuntimeError("Personal Chrome mode needs local discovery; remove BU_CDP_URL and BU_CDP_WS")
    active = Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data/DevToolsActivePort"
    try:
        port_text, ws_path = active.read_text(encoding="utf-8").splitlines()[:2]
        port = int(port_text)
        if not 0 < port < 65536 or not ws_path.startswith("/devtools/browser/"):
            raise ValueError()
    except (FileNotFoundError, IndexError, OSError, ValueError):
        raise RuntimeError(
            "Enable remote debugging in your Chrome at chrome://inspect/#remote-debugging, "
            "approve Chrome's prompt, then start the task again."
        ) from None


def custom_start_url(raw):
    url = raw.strip() if isinstance(raw, str) else ""
    if not url or len(url) > 2048 or any(character.isspace() for character in url):
        raise ValueError("Enter a full http:// or https:// starting URL")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter a full http:// or https:// starting URL without credentials")
    try:
        parsed.port
    except ValueError:
        raise ValueError("Enter a valid starting URL port") from None
    return url


def command(name, body):
    global AGENT
    if name == "reset":
        scenario = body.get("scenario", "flights")
        if scenario not in {"travel", "research", "flights", "custom"}:
            raise ValueError("Unknown demo scenario")
        goal = body.get("goal", "").strip()
        if not goal or len(goal) > 2000:
            raise ValueError("Enter 1–2,000 characters")
        url = (
            custom_start_url(body.get("url")) if scenario == "custom"
            else "https://www.google.com/travel/flights?hl=en" if scenario == "flights"
            else f"{ORIGIN}/fixture.html?scenario={scenario}"
        )
        if os.environ.get("JEV_BROWSER_MODE") == "personal":
            require_personal_chrome()
        close_browser()
        AGENT = Agent(
            url,
            goal,
            screenshots=True,
            record_dir=Path.cwd() / "artifacts" / "frames" if body.get("record") else None,
        )
        AGENT.state["scenario"] = scenario
    else:
        if AGENT is None:
            raise ValueError("Start a demo first")
        AGENT.command(name, body)
    return response_state()


class Handler(BaseHTTPRequestHandler):
    def send(self, status, content, mime="application/json"):
        content = content if isinstance(content, bytes) else content.encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.headers.get("Host") != f"127.0.0.1:{PORT}":
            return self.send(403, "Forbidden", "text/plain")
        path = urlparse(self.path).path
        if path == "/api/state":
            with LOCK:
                return self.send(200, json.dumps(response_state()))
        if path == "/demo.mp4":
            video = ROOT.parent / "docs" / "demo.mp4"
            if video.exists():
                return self.send(200, video.read_bytes(), "video/mp4")
        files = {
            "/": ("index.html", "text/html"),
            "/app.js": ("app.js", "text/javascript"),
            "/style.css": ("style.css", "text/css"),
            "/fixture.html": ("fixture.html", "text/html"),
        }
        if path not in files:
            return self.send(404, "Not found", "text/plain")
        name, mime = files[path]
        content = (ROOT / "static" / name).read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
        self.send(200, content, mime + "; charset=utf-8")

    def do_POST(self):
        if (
            self.headers.get("Host") != f"127.0.0.1:{PORT}"
            or self.headers.get("X-Demo-Token") != TOKEN
            or self.headers.get("Origin") not in (None, ORIGIN)
        ):
            return self.send(403, json.dumps({"error": "Local demo requests only"}))
        if not LOCK.acquire(blocking=False):
            return self.send(409, json.dumps({"error": "A browser step is already running"}))
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 8192:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length))
            result = command(self.path.removeprefix("/api/"), body)
            self.send(200, json.dumps(result))
        except (ValueError, RuntimeError, TimeoutError) as error:
            self.send(400, json.dumps({"error": str(error)}))
        except Exception:
            self.send(500, json.dumps({"error": "Local demo failed; no automatic retry. Reset to recover."}))
        finally:
            LOCK.release()

    def log_message(self, *_args):
        pass


def main():
    chrome = start_demo_chrome()
    if chrome is not None:
        atexit.register(stop_demo_chrome, chrome)
    atexit.register(close_browser)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Jev Ultrafast: {ORIGIN}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
