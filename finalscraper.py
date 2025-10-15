import random
import requests
from bs4 import BeautifulSoup
import csv
import time
import os
from urllib.parse import quote
from datetime import datetime

# ==============================
# CONFIG
# ==============================
KEYWORDS = [
    "Black Bolt & White Flare Booster Bundle",
    "Mega Evolution Booster Box",
    "Mega Evolution Elite Trainer Box",
    "Mega Evolution 3 Pack Blister",
    "Prismatic Evolutions Premium Figure Collection",
    "Prismatic Booster Bundle",
    "Mega Evolutions Mini tins",
    "Surging Sparks booster",
    "Prismatic Evolutions booster",
    "Journey Together booster",
    "Surging Sparks Elite Trainer Box",
    
]

BASE_URL = "https://www.very.co.uk/search/"
HEADERS = {
    "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
}

CSV_FILE = "very_products.csv"

# Telegram Bot Config
BOT_TOKEN = "8449824077:AAHlJqCVQiSRlTm8--VxfK-crjNMSVlwXsU"
CHAT_ID = "-1003062286470"  # Alerts group
LOG_CHAT_ID = "-1003026899918"  # Logs group
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


# ==============================
# FUNCTIONS
# ==============================
def send_telegram_alert(message, to_log=False):
    """Send message to Telegram group (main alert or log group)."""
    target_chat = LOG_CHAT_ID if to_log else CHAT_ID
    payload = {"chat_id": target_chat, "text": message}
    try:
        response = requests.post(TELEGRAM_URL, data=payload, timeout=5)
        if response.status_code != 200:
            print(f"❌ Telegram send failed ({'LOG' if to_log else 'ALERT'}): {response.text}")
    except Exception as e:
        print(f"⚠️ Telegram error ({'LOG' if to_log else 'ALERT'}): {e}")


def fetch_products(keyword, retries=3, delay_range=(2, 5)):
    """Fetch product data from Very.co.uk for given keyword, with retries and safety checks."""
    url = BASE_URL + quote(keyword)
    products = {}

    for attempt in range(1, retries + 1):
        try:
            print(f"🌐 Fetching ({attempt}/{retries}): {keyword}")
            response = requests.get(url, headers=HEADERS, timeout=10)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            text_lower = response.text.lower()
            if "captcha" in text_lower or "are you human" in text_lower:
                raise Exception("Blocked by CAPTCHA")

            soup = BeautifulSoup(response.text, "html.parser")
            all_cards = soup.select("a._productCard__link_gvf85_7, a[data-testid*='product-card']")

            if not all_cards:
                print(f"⚠️ No products found for {keyword} (Attempt {attempt})")
                time.sleep(random.uniform(*delay_range))
                continue

            for card in all_cards:
                href = card.get("href")
                if not href:
                    continue
                link = "https://www.very.co.uk" + href
                titletag = card.find("h3")
                pricetag = card.find("h4", {"data-testid": "fuse-product-card__price__basic"})
                title = titletag.text.strip() if titletag else "N/A"
                price = pricetag.text.strip() if pricetag else "N/A"

                products[link] = {
                    "keyword": keyword,
                    "title": title,
                    "price": price,
                    "url": link,
                    "status": "In Stock",
                }

            if products:
                break

        except Exception as e:
            err_msg = f"⚠️ Error ({keyword}) attempt {attempt}: {e} url:{url}"
            print(err_msg)
            send_telegram_alert(err_msg, to_log=True)
            time.sleep(random.uniform(*delay_range))

    if not products:
        msg = f"❌ Failed to fetch data for {keyword} after {retries} retries."
        print(msg)
        send_telegram_alert(msg, to_log=True)

    return products


def load_previous_data():
    """Load product data from CSV if exists."""
    if not os.path.exists(CSV_FILE):
        return {}
    data = {}
    with open(CSV_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row["url"]] = row
    return data


def save_to_csv(data):
    """Save product data to CSV."""
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["keyword", "title", "price", "url", "status"])
        writer.writeheader()
        for url, info in data.items():
            writer.writerow(info)


def monitor_products():
    """Main loop for monitoring product availability"""
    print("🛍️ Monitoring Very.co.uk for multiple keywords ...\n")
    send_telegram_alert("🟢 Monitoring started for Very.co.uk tracker.", to_log=True)

    previous_data = load_previous_data()

    while True:
        current_data = {}

        for keyword in KEYWORDS:
            try:
                keyword_products = fetch_products(keyword)
                current_data.update(keyword_products)
                send_telegram_alert(f"📦 {keyword}: {len(keyword_products)} products found", to_log=True)
            except Exception as e:
                msg = f"⚠️ Error fetching keyword '{keyword}': {e}"
                print(msg)
                send_telegram_alert(msg, to_log=True)

        # Detect new or changed statuses
        for url, info in current_data.items():
            if url not in previous_data:
                msg = f"🆕 [{info['keyword']}] New product:\n{info['title']} ({info['price']})\n{info['url']}"
                send_telegram_alert(msg)
            elif previous_data[url]["status"] == "Out of Stock":
                msg = f"✅ [{info['keyword']}] Back in stock:\n{info['title']} ({info['price']})\n{info['url']}"
                send_telegram_alert(msg)

            current_data[url]["status"] = "In Stock"

        # Detect out of stock
        for url, info in previous_data.items():
            # Only alert if it was previously in stock and now missing
            if url not in current_data and info["status"] == "In Stock":
                msg = f"❌ [{info['keyword']}] Out of stock:\n{info['title']}\n{info['url']}"
                send_telegram_alert(msg)
                info["status"] = "Out of Stock"
                current_data[url] = info  # keep it in file to avoid repeated alerts

        if not current_data:
            send_telegram_alert("⚠️ No valid data fetched this round (possible block or network issue).", to_log=True)
            time.sleep(15)
            continue

        save_to_csv(current_data)
        previous_data = current_data

        round_log = f"🕒 Checked {len(KEYWORDS)} keywords | {len(current_data)} total products tracked"
        print(round_log)
        send_telegram_alert(round_log, to_log=True)

        time.sleep(60)


# ==============================
# ENTRY POINT
# ==============================
if __name__ == "__main__":
    monitor_products()
