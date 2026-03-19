#!/usr/bin/env python3
"""
Shopee Network Proxy — auto-capture & extract products to SQLite.

Chrome extension intercepts API requests while you browse Shopee normally.
When recommend_v2 responses arrive, products are automatically parsed and
saved to SQLite. Just browse — data appears instantly.

Usage:
    python3 proxy.py [--db products.db] [--port 9234]
"""

import json
import os
import signal
import sqlite3
import sys
from argparse import ArgumentParser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ─── Config ────────────────────────────────────────────────────────────────────
DEFAULT_DB = "products.db"
DEFAULT_PORT = 9234
IMAGE_BASE = "https://down-vn.img.susercontent.com/file/"

console = Console()

# ─── State ─────────────────────────────────────────────────────────────────────
db_conn: sqlite3.Connection | None = None
counter = 0
product_count = 0


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            item_id TEXT PRIMARY KEY,
            shop_id TEXT,
            name TEXT,
            price REAL,
            original_price REAL,
            discount TEXT,
            sold TEXT,
            seller_type TEXT,
            image TEXT,
            images TEXT,
            url TEXT,
            category_id TEXT,
            captured_at TEXT
        )
    """)
    conn.commit()
    return conn


def parse_product(unit: dict) -> dict | None:
    item = unit.get("item", {})
    asset = item.get("item_card_displayed_asset", {})
    item_data = item.get("item_data", {})

    if not asset.get("name"):
        return None

    tid = unit.get("tracking_card_id", "")
    item_id = tid.split("::")[-1] if "::" in tid else ""
    if not item_id:
        return None

    price_raw = asset.get("display_price", {}).get("price", 0)
    price = price_raw / 100000

    strikethrough = asset.get("display_price", {}).get("strikethrough_price", 0) or 0
    original_price = strikethrough / 100000 if strikethrough else None

    discount_tag = asset.get("discount_tag")
    discount = discount_tag.get("discount_text", "") if discount_tag else ""

    sold_count = asset.get("sold_count")
    sold = sold_count.get("text", "") if sold_count else ""

    image = asset.get("image", "")
    images = asset.get("images", [])

    seller = asset.get("seller_flag")
    seller_type = seller.get("name", "") if seller else ""

    shop_id = str(item_data.get("shopid", ""))

    return {
        "item_id": item_id,
        "shop_id": shop_id,
        "name": asset.get("name", ""),
        "price": price,
        "original_price": original_price,
        "discount": discount,
        "sold": sold,
        "seller_type": seller_type,
        "image": f"{IMAGE_BASE}{image}" if image else "",
        "images": json.dumps([f"{IMAGE_BASE}{img}" for img in images]),
        "url": f"https://shopee.vn/product/{shop_id}/{item_id}" if shop_id and item_id else "",
    }


def process_recommend_response(resp_body: str, req_body: str | None) -> int:
    """Parse recommend_v2 response and insert products into DB."""
    global product_count

    if not resp_body or "90309999" in resp_body:
        return 0

    try:
        resp = json.loads(resp_body)
    except json.JSONDecodeError:
        return 0

    units = resp.get("data", {}).get("units", [])
    if not units:
        return 0

    # Extract category ID from request body
    cat_id = ""
    if req_body:
        try:
            cat_id = str(json.loads(req_body).get("catid", ""))
        except Exception:
            pass

    now = datetime.now().isoformat()
    new_count = 0

    for u in units:
        product = parse_product(u)
        if not product:
            continue

        try:
            db_conn.execute(
                """INSERT OR IGNORE INTO products
                   (item_id, shop_id, name, price, original_price, discount,
                    sold, seller_type, image, images, url, category_id, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    product["item_id"], product["shop_id"], product["name"],
                    product["price"], product["original_price"], product["discount"],
                    product["sold"], product["seller_type"], product["image"],
                    product["images"], product["url"], cat_id, now,
                ),
            )
            if db_conn.total_changes > product_count + new_count:
                new_count += 1
        except Exception:
            pass

    db_conn.commit()
    product_count += new_count
    return new_count


def status_style(code: int) -> str:
    if 200 <= code < 300:
        return "green"
    if 300 <= code < 400:
        return "yellow"
    return "red"


def json_preview(text: str, max_len: int = 120) -> str:
    try:
        data = json.loads(text)
        s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        s = text
    return s[:max_len] + "..." if len(s) > max_len else s


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
        url = data.get("url", "")
        method = data.get("method", "")
        status = data.get("responseStatus", 0)
        resp_body = data.get("responseBody", "")
        req_body = data.get("requestBody")

        # Display
        if "shopee.vn/api" in url:
            st = status_style(status)
            url_display = url.split("?")[0] if len(url) > 100 else url
            url_short = url_display.split("shopee.vn")[-1] if "shopee.vn" in url_display else url_display

            console.print(
                f"  [cyan]#{counter:>3}[/] "
                f"[bold]{method:>4}[/] "
                f"[{st}]{status}[/{st}] "
                f"[white]{url_short}[/]"
            )

        # Auto-extract products from recommend_v2
        if "recommend/recommend_v2" in url and status == 200:
            new = process_recommend_response(resp_body, req_body)
            if new > 0:
                total = db_conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
                console.print(
                    f"       [green bold]＋{new} products[/] "
                    f"[dim]({total} total in DB)[/]"
                )

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def show_stats():
    if not db_conn:
        return
    total = db_conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    cats = db_conn.execute("SELECT DISTINCT category_id FROM products WHERE category_id != ''").fetchall()
    console.print(f"\n[green]Database: {total} products across {len(cats)} categories[/]")


def main(db_path: str, port: int):
    global db_conn

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    db_abs = os.path.abspath(db_path)
    db_conn = init_db(db_abs)
    existing = db_conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    ext_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extension")

    console.print(Panel.fit(
        f"[bold cyan]Shopee Product Proxy[/]\n"
        f"Server:   [green]http://localhost:{port}[/]\n"
        f"Database: [green]{db_abs}[/] ({existing} products)\n"
        f"Extension: [green]{ext_path}[/]\n\n"
        f"[yellow]Setup (one time):[/]\n"
        f"  1. [bold]chrome://extensions[/] → Developer mode → Load unpacked\n"
        f"  2. Select [bold]extension/[/] folder\n"
        f"  3. Browse Shopee → products auto-saved to DB!",
        border_style="cyan",
    ))

    server = HTTPServer(("localhost", port), CaptureHandler)
    console.print(f"\n[green bold]Listening...[/] Browse Shopee category pages.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        show_stats()
        if db_conn:
            db_conn.close()
        server.server_close()


def parse_args():
    parser = ArgumentParser(description="Shopee Product Proxy — auto-extract to SQLite")
    parser.add_argument("--db", "-d", default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT, help="Server port")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        main(args.db, args.port)
    except (KeyboardInterrupt, SystemExit):
        show_stats()
        console.print("[bold]Done.[/]")
