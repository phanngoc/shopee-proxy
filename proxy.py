#!/usr/bin/env python3
"""
Shopee Product Proxy — auto-capture & extract products to SQLite.

Chrome extension intercepts API requests while you browse Shopee normally.
Products from recommend_v2 and search_items are auto-parsed into SQLite.

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
from urllib.parse import urlparse, parse_qs

from rich.console import Console
from rich.panel import Panel

# ─── Config ────────────────────────────────────────────────────────────────────
DEFAULT_DB = "products.db"
DEFAULT_PORT = 9234
IMAGE_BASE = "https://down-vn.img.susercontent.com/file/"

# APIs that contain product listings
PRODUCT_APIS = ["recommend/recommend_v2", "search/search_items"]

console = Console()

# ─── State ─────────────────────────────────────────────────────────────────────
db_conn: sqlite3.Connection | None = None
product_count = 0
counter = 0


# ─── Database ──────────────────────────────────────────────────────────────────

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


def insert_products(products: list[dict], cat_id: str) -> int:
    """Insert products into DB, return count of new inserts."""
    global product_count
    now = datetime.now().isoformat()
    new_count = 0

    for p in products:
        try:
            before = db_conn.total_changes
            db_conn.execute(
                """INSERT OR IGNORE INTO products
                   (item_id, shop_id, name, price, original_price, discount,
                    sold, seller_type, image, images, url, category_id, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["item_id"], p["shop_id"], p["name"], p["price"],
                 p["original_price"], p["discount"], p["sold"],
                 p["seller_type"], p["image"], p["images"], p["url"],
                 cat_id, now),
            )
            if db_conn.total_changes > before:
                new_count += 1
        except Exception:
            pass

    db_conn.commit()
    product_count += new_count
    return new_count


# ─── Parsers ───────────────────────────────────────────────────────────────────

def parse_recommend_product(unit: dict) -> dict | None:
    """Parse product from recommend_v2 response unit."""
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
    strikethrough = asset.get("display_price", {}).get("strikethrough_price", 0) or 0

    discount_tag = asset.get("discount_tag")
    sold_count = asset.get("sold_count")
    seller = asset.get("seller_flag")
    image = asset.get("image", "")
    images = asset.get("images", [])

    return {
        "item_id": item_id,
        "shop_id": str(item_data.get("shopid", "")),
        "name": asset.get("name", ""),
        "price": price_raw / 100000,
        "original_price": strikethrough / 100000 if strikethrough else None,
        "discount": discount_tag.get("discount_text", "") if discount_tag else "",
        "sold": sold_count.get("text", "") if sold_count else "",
        "seller_type": seller.get("name", "") if seller else "",
        "image": f"{IMAGE_BASE}{image}" if image else "",
        "images": json.dumps([f"{IMAGE_BASE}{i}" for i in images]),
        "url": f"https://shopee.vn/product/{item_data.get('shopid','')}/{item_id}",
    }


def parse_search_product(item: dict) -> dict | None:
    """Parse product from search_items response item."""
    item_basic = item.get("item_basic") or item
    item_id = str(item_basic.get("itemid", ""))
    shop_id = str(item_basic.get("shopid", ""))

    if not item_id or not item_basic.get("name"):
        return None

    price = item_basic.get("price", 0) / 100000
    price_before = item_basic.get("price_before_discount", 0) / 100000
    image = item_basic.get("image", "")
    images = item_basic.get("images", [])
    sold = item_basic.get("sold", 0)
    historical_sold = item_basic.get("historical_sold", 0)
    discount = item_basic.get("raw_discount", 0)
    shop_rating = item_basic.get("shopee_verified")
    seller_type = ""
    if item_basic.get("is_official_shop"):
        seller_type = "MALL"
    elif item_basic.get("shopee_verified"):
        seller_type = "PREFERRED"

    # sold text
    if historical_sold >= 1000:
        sold_text = f"Đã bán {historical_sold // 1000}k+"
    elif historical_sold > 0:
        sold_text = f"Đã bán {historical_sold}"
    else:
        sold_text = ""

    return {
        "item_id": item_id,
        "shop_id": shop_id,
        "name": item_basic.get("name", ""),
        "price": price,
        "original_price": price_before if price_before > price else None,
        "discount": f"-{discount}%" if discount else "",
        "sold": sold_text,
        "seller_type": seller_type,
        "image": f"{IMAGE_BASE}{image}" if image else "",
        "images": json.dumps([f"{IMAGE_BASE}{i}" for i in images]),
        "url": f"https://shopee.vn/product/{shop_id}/{item_id}",
    }


# ─── Response processors ──────────────────────────────────────────────────────

def process_response(url: str, resp_body: str, req_body: str | None) -> tuple[int, int]:
    """Process API response, return (new_count, total_in_response)."""
    if not resp_body or "90309999" in resp_body:
        return 0, 0

    try:
        resp = json.loads(resp_body)
    except json.JSONDecodeError:
        return 0, 0

    products = []
    cat_id = ""

    if "recommend/recommend_v2" in url:
        units = resp.get("data", {}).get("units", [])
        for u in units:
            p = parse_recommend_product(u)
            if p:
                products.append(p)
        # Category from request body
        if req_body:
            try:
                cat_id = str(json.loads(req_body).get("catid", ""))
            except Exception:
                pass

    elif "search/search_items" in url:
        items = resp.get("items") or resp.get("data", {}).get("items", [])
        for item in items:
            p = parse_search_product(item)
            if p:
                products.append(p)
        # Category from URL params
        try:
            qs = parse_qs(urlparse(url).query)
            cat_id = qs.get("match_id", [""])[0]
        except Exception:
            pass

    if not products:
        return 0, 0

    new = insert_products(products, cat_id)
    return new, len(products)


# ─── HTTP Server ───────────────────────────────────────────────────────────────

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
        url = data.get("url", "")
        method = data.get("method", "")
        status = data.get("responseStatus", 0)
        resp_body = data.get("responseBody", "")
        req_body = data.get("requestBody")

        # Only show shopee API calls
        if "shopee.vn/api" in url:
            st = status_style(status)
            url_short = url.split("shopee.vn")[-1].split("?")[0] if "shopee.vn" in url else url

            console.print(
                f"  [cyan]#{counter:>3}[/] "
                f"[bold]{method:>4}[/] "
                f"[{st}]{status}[/{st}] "
                f"[white]{url_short}[/]"
            )

        # Check if this is a product API
        is_product_api = any(api in url for api in PRODUCT_APIS)

        if is_product_api and status == 200:
            if "90309999" in (resp_body or ""):
                console.print(f"       [red]BLOCKED (anti-bot)[/]")
            elif not resp_body:
                console.print(f"       [yellow]empty response[/]")
            else:
                new, total_resp = process_response(url, resp_body, req_body)
                total_db = db_conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
                dupes = total_resp - new
                console.print(
                    f"       [green bold]＋{new} new[/] "
                    f"[dim]({dupes} dupes, {total_resp} parsed, {total_db} in DB)[/]"
                )

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


# ─── Main ──────────────────────────────────────────────────────────────────────

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
        f"Captures: [yellow]recommend_v2 + search_items[/]\n\n"
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
