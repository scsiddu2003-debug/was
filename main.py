# main.py
import os
import csv
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Configuration
TEBEX_URL = os.getenv("TEBEX_URL", "https://big-bang-scripts.tebex.io/")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = OUTPUT_DIR / "products.csv"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")  # optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def fetch_page_html(url: str) -> str:
    logging.info("Launching Playwright and fetching %s", url)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        # set a realistic UA
        page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                  "Chrome/120.0.0.0 Safari/537.36"})
        page.goto(url, wait_until="networkidle", timeout=60000)
        html = page.content()
        browser.close()
    logging.info("Fetched page HTML (%d bytes)", len(html))
    return html


def parse_products(html: str):
    soup = BeautifulSoup(html, "html.parser")
    products = []

    # Tebex stores vary by theme. Try a few selectors commonly used:
    # - package cards usually have classes like 'package-card', 'package', etc.
    # - package name often in '.package-name' or '.package-title'
    # - price often in '.price' or '.package-price'
    # We'll try a few fallbacks.
    # Primary: look for package card containers
    card_selectors = [
        ".package-card", ".package", ".package-list-item", ".package--card"
    ]
    name_selectors = [".package-name", ".package-title", ".name", "h3", "h2"]
    price_selectors = [".price", ".package-price", ".pkg-price", ".price-text"]

    for card_sel in card_selectors:
        cards = soup.select(card_sel)
        if cards:
            for c in cards:
                # name
                name = None
                for ns in name_selectors:
                    el = c.select_one(ns)
                    if el and el.get_text(strip=True):
                        name = el.get_text(strip=True)
                        break
                # price
                price = None
                for ps in price_selectors:
                    el = c.select_one(ps)
                    if el and el.get_text(strip=True):
                        price = el.get_text(strip=True)
                        break
                # link
                link_el = c.select_one("a[href]")
                link = link_el["href"] if link_el else None
                if link and link.startswith("/"):
                    # make absolute
                    link = TEBEX_URL.rstrip("/") + link
                products.append({"name": name or "N/A", "price": price or "N/A", "link": link or "N/A"})
            break

    # If not found with cards, try searching for package names on page
    if not products:
        logging.info("No package cards found; trying fallback selectors for names")
        names = soup.select(".package-name, .package-title, .package")
        for n in names:
            text = n.get_text(strip=True)
            if text:
                products.append({"name": text, "price": "N/A", "link": "N/A"})

    return products


def save_to_csv(items, path: Path):
    logging.info("Saving %d products to %s", len(items), path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "price", "link"])
        writer.writeheader()
        for it in items:
            writer.writerow(it)


def post_to_discord(file_path: Path, webhook_url: str):
    import requests
    logging.info("Posting %s to Discord webhook", file_path)
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f)}
        resp = requests.post(webhook_url, files=files)
    if resp.status_code in (200, 204):
        logging.info("Posted successfully to Discord")
    else:
        logging.warning("Discord responded with %s: %s", resp.status_code, resp.text)


def main():
    logging.info("Starting Tebex scraper for %s", TEBEX_URL)
    html = fetch_page_html(TEBEX_URL)
    products = parse_products(html)
    if not products:
        logging.warning("No products found. HTML saved to output/page.html for inspection.")
        with open(OUTPUT_DIR / "page.html", "w", encoding="utf-8") as f:
            f.write(html)
        return

    save_to_csv(products, CSV_PATH)
    logging.info("Saved CSV with %d products", len(products))

    if DISCORD_WEBHOOK:
        try:
            post_to_discord(CSV_PATH, DISCORD_WEBHOOK)
        except Exception as e:
            logging.exception("Failed to post to Discord: %s", e)


if __name__ == "__main__":
    main()
