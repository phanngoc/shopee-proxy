#!/usr/bin/env python3
"""
Shopee Network Proxy - Chrome Extension + Local Server

Uses a Chrome extension to capture network requests (invisible to Shopee anti-bot)
and sends them to this local server for logging.

Usage:
    1. Open Chrome normally (no special flags needed!)
    2. Load extension: chrome://extensions → Developer mode → Load unpacked → select ./extension/
    3. Run: python3 proxy.py
    4. Browse Shopee — all API requests are captured
    5. Ctrl+C to stop

The extension uses chrome.webRequest API which is undetectable by websites.
"""

import asyncio
import json
import os
import signal
import sys
from argparse import ArgumentParser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

from rich.console import Console
from rich.panel import Panel

# ─── Config ────────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT = "network_log.json"
DEFAULT_PORT = 9234
PREVIEW_LEN = 150

console = Console()

# ─── State ─────────────────────────────────────────────────────────────────────
captured: list[dict] = []
output_file = DEFAULT_OUTPUT
counter = 0


def save_log():
    if not captured:
        return
    tmp = output_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(captured, f, ensure_ascii=False, indent=2)
    os.replace(tmp, output_file)


def json_preview(text: str, max_len: int) -> str:
    try:
        data = json.loads(text)
        s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        s = text
    return s[:max_len] + "..." if len(s) > max_len else s


def build_curl(method: str, url: str, headers: list[dict], body: str | None) -> str:
    parts = [f"curl -X {method}", f"  '{url}'"]
    skip = {":authority", ":method", ":path", ":scheme"}
    if headers:
        for h in headers:
            name = h.get("name", "")
            value = h.get("value", "")
            if name.lower() in skip:
                continue
            v_escaped = value.replace("'", "'\\''")
            parts.append(f"  -H '{name}: {v_escaped}'")
    if body and method in ("POST", "PUT", "PATCH"):
        display = body if len(body) <= 2000 else body[:2000] + "..."
        display = display.replace("'", "'\\''")
        parts.append(f"  --data-raw '{display}'")
    return " \\\n".join(parts)


def status_style(code: int) -> str:
    if 200 <= code < 300:
        return "green"
    if 300 <= code < 400:
        return "yellow"
    return "red"


class CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global counter

        if self.path != "/capture":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b"ok")

        try:
            data = json.loads(body)
        except Exception:
            return

        counter += 1
        resp_body = data.get("responseBody", "")
        req_headers = data.get("requestHeaders", {})
        cookies = data.get("cookies", "")

        # Build curl from dict headers (injector sends dict, not list)
        curl_parts = [f"curl -X {data.get('method', 'GET')}", f"  '{data.get('url', '')}'"]
        if isinstance(req_headers, dict):
            for k, v in req_headers.items():
                v_escaped = str(v).replace("'", "'\\''")
                curl_parts.append(f"  -H '{k}: {v_escaped}'")
        req_body = data.get("requestBody")
        if req_body and data.get("method") in ("POST", "PUT", "PATCH"):
            display = req_body if len(req_body) <= 2000 else req_body[:2000] + "..."
            display = display.replace("'", "'\\''")
            curl_parts.append(f"  --data-raw '{display}'")

        entry = {
            "number": counter,
            "timestamp": data.get("timestamp", datetime.now().isoformat()),
            "method": data.get("method", ""),
            "url": data.get("url", ""),
            "request_headers": req_headers,
            "request_body": req_body,
            "response_status": data.get("responseStatus", 0),
            "response_body": resp_body,
            "cookies": cookies,
            "curl_command": " \\\n".join(curl_parts),
        }
        captured.append(entry)
        save_log()

        # Display
        url = entry["url"]
        st = status_style(entry["response_status"])
        url_display = url.split("?")[0] if len(url) > 100 else url
        preview = json_preview(resp_body, PREVIEW_LEN)

        console.print(
            f"  [cyan]#{counter:>3}[/] "
            f"[bold]{entry['method']:>4}[/] "
            f"[{st}]{entry['response_status']}[/{st}] "
            f"[white]{url_display}[/]"
        )
        console.print(f"       [dim]→ {preview}[/]")

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs


def main(out_file: str, port: int):
    global output_file
    output_file = os.path.abspath(out_file)

    signal.signal(signal.SIGTERM, lambda *_: (save_log(), sys.exit(0)))

    ext_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extension")

    console.print(Panel.fit(
        f"[bold cyan]Shopee Network Proxy[/]\n"
        f"Output:    [green]{output_file}[/]\n"
        f"Server:    [green]http://localhost:{port}[/]\n"
        f"Extension: [green]{ext_path}[/]\n\n"
        f"[yellow]Setup (one time):[/]\n"
        f"  1. Open [bold]chrome://extensions[/]\n"
        f"  2. Enable [bold]Developer mode[/] (top right)\n"
        f"  3. Click [bold]Load unpacked[/] → select extension/ folder\n"
        f"  4. Browse Shopee normally!",
        border_style="cyan",
    ))

    server = HTTPServer(("localhost", port), CaptureHandler)
    console.print(f"\n[green bold]Server listening on port {port}[/] — waiting for requests...\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        save_log()
        console.print(f"\n[green]Saved {len(captured)} requests → {output_file}[/]")
        server.server_close()


def parse_args():
    parser = ArgumentParser(description="Shopee Network Proxy — extension-based capture")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT, help="Output JSON")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help="Local server port")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        main(args.output, args.port)
    except (KeyboardInterrupt, SystemExit):
        save_log()
        console.print(f"\n[bold]Done. {len(captured)} requests saved.[/]")
