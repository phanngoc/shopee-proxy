# Shopee Product Proxy

Capture Shopee product data by browsing normally. A Chrome extension intercepts API responses and streams them to a local server that auto-extracts products into SQLite.

**No bot detection** — uses your real browser session with all cookies/tokens intact.

## How it works

```
Chrome Extension (intercept fetch/XHR)
    → window.postMessage
    → content script (bridge.js)
    → chrome.runtime.sendMessage
    → background.js
    → POST http://localhost:9234/capture
    → proxy.py auto-parses recommend_v2 responses
    → SQLite database (products.db)
```

## Quick Start

### 1. Install

```bash
pip install rich
```

### 2. Load Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** → select the `extension/` folder

### 3. Run

```bash
python3 proxy.py
```

### 4. Browse Shopee

Navigate to any category page on [shopee.vn](https://shopee.vn), e.g.:
- [Điện Thoại & Phụ Kiện](https://shopee.vn/%C4%90i%E1%BB%87n-Tho%E1%BA%A1i-Ph%E1%BB%A5-Ki%E1%BB%87n-cat.11036030)
- [Máy Tính & Laptop](https://shopee.vn/M%C3%A1y-T%C3%ADnh-Laptop-cat.11035954)

Scroll through pages — products are automatically saved to `products.db`.

### 5. Query Data

```bash
sqlite3 products.db "SELECT name, price, sold FROM products LIMIT 10"
```

Or in Python:

```python
import sqlite3
conn = sqlite3.connect("products.db")
products = conn.execute("SELECT * FROM products ORDER BY captured_at DESC LIMIT 20").fetchall()
```

## CLI Options

```
python3 proxy.py --db mydata.db --port 8080
```

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `products.db` | SQLite database path |
| `--port` | `9234` | Local server port |

## Database Schema

| Column | Type | Description |
|--------|------|-------------|
| `item_id` | TEXT (PK) | Shopee item ID |
| `shop_id` | TEXT | Shop ID |
| `name` | TEXT | Product name |
| `price` | REAL | Current price (VND) |
| `original_price` | REAL | Price before discount |
| `discount` | TEXT | e.g. "-30%" |
| `sold` | TEXT | e.g. "Đã bán 40k+" |
| `seller_type` | TEXT | e.g. "PREFERRED_PLUS", "MALL" |
| `image` | TEXT | Main image URL |
| `images` | TEXT | JSON array of image URLs |
| `url` | TEXT | Product page URL |
| `category_id` | TEXT | Shopee category ID |
| `captured_at` | TEXT | ISO timestamp |

## Standalone Extractor

Extract products from a previously captured `network_log.json`:

```bash
python3 crawl.py --log network_log.json --output products.json
```

## Project Structure

```
├── proxy.py              # Main server — receives data, saves to SQLite
├── crawl.py              # Standalone extractor from JSON logs
├── extension/
│   ├── manifest.json     # Chrome extension manifest (MV3)
│   ├── background.js     # Forwards captured data to local server
│   ├── bridge.js         # ISOLATED world → chrome.runtime bridge
│   └── injector.js       # MAIN world fetch/XHR interceptor
├── requirements.txt
└── README.md
```
