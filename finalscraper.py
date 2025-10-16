# finalscraper.py
import random
import requests
from bs4 import BeautifulSoup
import csv
import time
import os
from urllib.parse import quote
from datetime import datetime
from requests.exceptions import ProxyError, ConnectTimeout, ReadTimeout, RequestException

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
CSV_FILE = "very_products.csv"

# Original basic headers (we will rotate UA and tweak per-request headers)
HEADERS = {
    "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "upgrade-insecure-requests": "1",
    # user-agent replaced per-request
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                  " (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
}

# Telegram Bot Config (left as in your original script)
BOT_TOKEN = "8449824077:AAHlJqCVQiSRlTm8--VxfK-crjNMSVlwXsU"
CHAT_ID = "-1003062286470"  # Alerts group
LOG_CHAT_ID = "-1003026899918"  # Logs group
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# ---------- Proxy configuration ----------
# Recommended: set SCRAPER_PROXY as an environment variable on your server
# e.g. export SCRAPER_PROXY="http://user:pass@host:port"
DEFAULT_PROXY = "http://OhovjuoxW47tvp53Cy-res-UK:5N0KkB6uYbP77Pa@gw.thunderproxy.net:5959"
SCRAPER_PROXY = os.environ.get("SCRAPER_PROXY", DEFAULT_PROXY)

# Support multiple proxies if you later want to use a pool (comma-separated env var)
# Example: "http://user:pass@host1:port,http://user:pass@host2:port"
proxy_env_list = os.environ.get("SCRAPER_PROXY_LIST")
if proxy_env_list:
    PROXY_POOL = [p.strip() for p in proxy_env_list.split(",") if p.strip()]
else:
    PROXY_POOL = [SCRAPER_PROXY]

def get_proxy_dict(proxy_url):
    return {"http": proxy_url, "https": proxy_url}

# ---------- User-Agent rotation ----------
USER_AGENTS = [
    # A small curated UA set; extend if needed
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.96 Mobile Safari/537.36",
]

# ==============================
# FUNCTIONS
# ==============================

def send_telegram_alert(message, to_log=False):
    """Send message to Telegram group (main alert or log group)."""
    target_chat = LOG_CHAT_ID if to_log else CHAT_ID
    payload = {"chat_id": target_chat, "text": message}
    try:
        response = requests.post(TELEGRAM_URL, data=payload, timeout=6)
        if response.status_code != 200:
            print(f"❌ Telegram send failed ({'LOG' if to_log else 'ALERT'}): {response.text}")
    except Exception as e:
        print(f"⚠️ Telegram error ({'LOG' if to_log else 'ALERT'}): {e}")


def fetch_products(keyword, retries=3, delay_range=(2, 5), backoff_factor=1.5):
    """
    Fetch product data from Very.co.uk for a given keyword.
    Uses: Session(), rotating UA, optional rotating residential proxies, retries & backoff.
    """
    url = BASE_URL + quote(keyword)
    products = {}
    session = requests.Session()

    # persist a couple of sensible headers on session
    session.headers.update({
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-encoding": "gzip, deflate, br",
    })

    attempt = 0
    while attempt < retries:
        attempt += 1
        # choose a proxy from the pool at random
        chosen_proxy = random.choice(PROXY_POOL) if PROXY_POOL else None
        proxies = get_proxy_dict(chosen_proxy) if chosen_proxy else None

        # rotate user-agent
        ua = random.choice(USER_AGENTS)
        headers = HEADERS.copy()
        headers["user-agent"] = ua
        # small randomized header tweaks to make fingerprint less uniform
        headers["accept-language"] = random.choice(["en-GB,en;q=0.9", "en-US,en;q=0.9", "en;q=0.8"])
        headers["referer"] = "https://www.google.com/"

        try:
            print(f"🌐 Fetching ({attempt}/{retries}) for keyword: {keyword} | UA: {ua.split(' ')[0]} | Proxy: {chosen_proxy or 'none'}")
            response = session.get(url, headers=headers, proxies=proxies, timeout=15)

            # check HTTP status
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            text_lower = response.text.lower()
            # basic checks for anti-bot signals
            if ("captcha" in text_lower) or ("are you human" in text_lower) or ("verify you are a human" in text_lower):
                raise Exception("Blocked by CAPTCHA/anti-bot challenge")

            soup = BeautifulSoup(response.text, "html.parser")
            # product card selectors - keep your original selectors but detect multiple common patterns
            all_cards = soup.select("a._productCard__link_gvf85_7, a[data-testid*='product-card'], a[href*='/product/'], a[data-testid*='productCard']")

            if not all_cards:
                # If the page contains visible script placeholders or minimal HTML, it's possible the site uses JS rendering
                # Print a short snippet for debugging (but don't log huge HTML)
                snippet = response.text[:800].lower()
                print(f"⚠️ No product cards found for '{keyword}' (Attempt {attempt}). Snippet preview: {snippet[:300]}...")
                # wait then retry (maybe proxy/headers)
                sleep_time = random.uniform(*delay_range) * (backoff_factor ** (attempt - 1))
                time.sleep(sleep_time)
                continue

            for card in all_cards:
                href = card.get("href")
                if not href:
                    continue
                # some hrefs might already be absolute
                link = href if href.startswith("http") else "https://www.very.co.uk" + href
                titletag = card.find("h3")
                # price tag detection common patterns
                pricetag = (card.find("h4", {"data-testid": "fuse-product-card__price__basic"}) or
                            card.find("span", {"data-testid": "product-price"}) or
                            card.select_one(".price, .product-price"))
                title = titletag.text.strip() if titletag else (card.get("aria-label") or "N/A")
                price = pricetag.text.strip() if pricetag else "N/A"

                products[link] = {
                    "keyword": keyword,
                    "title": title,
                    "price": price,
                    "url": link,
                    "status": "In Stock",
                }

            # success - break out
            if products:
                break

        except (ProxyError, ConnectTimeout, ReadTimeout) as e:
            err_msg = f"⚠️ Proxy/Timeout error ({keyword}) attempt {attempt}: {e} url:{url} proxy:{chosen_proxy}"
            print(err_msg)
            send_telegram_alert(err_msg, to_log=True)
            sleep_time = random.uniform(*delay_range) * (backoff_factor ** (attempt - 1))
            time.sleep(sleep_time)

        except RequestException as e:
            err_msg = f"⚠️ Requests exception ({keyword}) attempt {attempt}: {e} url:{url}"
            print(err_msg)
            send_telegram_alert(err_msg, to_log=True)
            sleep_time = random.uniform(*delay_range) * (backoff_factor ** (attempt - 1))
            time.sleep(sleep_time)

        except Exception as e:
            err_msg = f"⚠️ Error ({keyword}) attempt {attempt}: {e} url:{url}"
            print(err_msg)
            send_telegram_alert(err_msg, to_log=True)
            # if it's a bot block / captcha, consider waiting longer
            if "captcha" in str(e).lower() or "blocked" in str(e).lower():
                time.sleep(10 * attempt)
            else:
                sleep_time = random.uniform(*delay_range) * (backoff_factor ** (attempt - 1))
                time.sleep(sleep_time)

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
                # randomize small sleep between keywords to reduce fingerprinting
                time.sleep(random.uniform(0.8, 2.0))
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
            # wait longer before retrying the whole round if nothing fetched
            time.sleep(30)
            continue

        save_to_csv(current_data)
        previous_data = current_data

        round_log = f"🕒 Checked {len(KEYWORDS)} keywords | {len(current_data)} total products tracked"
        print(round_log)
        send_telegram_alert(round_log, to_log=True)

        # main loop delay - keep this reasonable to avoid hammering the site
        time.sleep(60)


# ==============================
# ENTRY POINT
# ==============================
if __name__ == "__main__":
    try:
        monitor_products()
    except KeyboardInterrupt:
        print("Stopped by user (KeyboardInterrupt).")
    except Exception as e:
        print(f"Fatal error in monitor_products: {e}")
        send_telegram_alert(f"🔴 Fatal error in scraper: {e}", to_log=True)
