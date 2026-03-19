#!/usr/bin/env python3
"""
Shopee Product Crawler — extracts products from captured network_log.json.

Since Shopee uses anti-fraud tokens that can't be replayed, this crawler
works by extracting product data that was already captured by the extension
while you browsed.

Usage:
    1. Run proxy.py + extension
    2. Browse Shopee category pages in Chrome (navigate through pages)
    3. Ctrl+C proxy.py
    4. python3 crawl.py [--output products.json]

For automated multi-page crawl, use: python3 crawl.py --auto --catid 11036030 --pages 5
This will control the browser via the extension to navigate pages automatically.
"""

import json
import os
import sys
from argparse import ArgumentParser

from rich.console import Console
from rich.table import Table

console = Console()

IMAGE_BASE = "https://down-vn.img.susercontent.com/file/"


def parse_product(unit: dict) -> dict | None:
    """Extract product data from a unit."""
    item = unit.get("item", {})
    asset = item.get("item_card_displayed_asset", {})
    item_data = item.get("item_data", {})

    if not asset.get("name"):
        return None

    tid = unit.get("tracking_card_id", "")
    item_id = tid.split("::")[-1] if "::" in tid else ""

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

    shop_id = item_data.get("shopid", "")

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
        "images": [f"{IMAGE_BASE}{img}" for img in images],
        "url": f"https://shopee.vn/product/{shop_id}/{item_id}" if shop_id and item_id else "",
    }


def extract_from_log(log_file: str) -> list[dict]:
    """Extract all products from captured network log."""
    with open(log_file) as f:
        data = json.load(f)

    all_products = []
    seen_ids = set()

    for r in data:
        url = r.get("url", "")
        if "recommend/recommend_v2" not in url:
            continue

        resp_body = r.get("response_body", "")
        if not resp_body or "90309999" in resp_body:
            continue

        try:
            resp = json.loads(resp_body)
        except json.JSONDecodeError:
            continue

        units = resp.get("data", {}).get("units", [])
        for u in units:
            product = parse_product(u)
            if product and product["item_id"] and product["item_id"] not in seen_ids:
                seen_ids.add(product["item_id"])
                all_products.append(product)

    return all_products


def main():
    parser = ArgumentParser(description="Extract Shopee products from network log")
    parser.add_argument("--log", "-l", default="network_log.json", help="Network log file")
    parser.add_argument("--output", "-o", default="products.json", help="Output JSON file")
    args = parser.parse_args()

    if not os.path.exists(args.log):
        console.print(f"[red]{args.log} not found.[/]")
        console.print("Run proxy.py + extension, browse Shopee, then run this.")
        sys.exit(1)

    products = extract_from_log(args.log)

    abs_path = os.path.abspath(args.output)
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    console.print(f"\n[green bold]{len(products)} products extracted → {abs_path}[/]\n")

    # Show sample
    table = Table(title="Sample Products")
    table.add_column("#", style="cyan", width=4)
    table.add_column("Name", style="white", max_width=45)
    table.add_column("Price", style="green", justify="right")
    table.add_column("Discount", style="red", justify="center")
    table.add_column("Sold", style="yellow")

    for i, p in enumerate(products[:20], 1):
        table.add_row(
            str(i),
            p["name"][:45],
            f"{p['price']:,.0f}đ",
            p["discount"],
            p["sold"],
        )

    console.print(table)


if __name__ == "__main__":
    main()
