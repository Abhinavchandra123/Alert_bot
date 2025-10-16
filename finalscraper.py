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
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                  " (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
}

# Telegram Bot Config
BOT_TOKEN = "8449824077:AAHlJqCVQiSRlTm8--VxfK-crjNMSVlwXsU"
CHAT_ID = "-1003062286470"  # Alerts group
LOG_CHAT_ID = "-1003026899918"  # Logs group
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# ---------- Proxy configuration ----------
DEFAULT_PROXY = "http://OhovjuoxW47tvp53Cy-res-UK:5N0KkB6uYbP77Pa@gw.thunderproxy.net:5959"
SCRAPER_PROXY = os.environ.get("SCRAPER_PROXY", DEFAULT_PROXY)
proxy_env_list = os.environ.get("SCRAPER_PROXY_LIST")
if proxy_env_list:
    PROXY_POOL = [p.strip() for p in proxy_env_list.split(",") if p.strip()]
else:
    PROXY_POOL = [SCRAPER_PROXY]

def get_proxy_dict(proxy_url):
    return {"http": proxy_url, "https": proxy_url}

# ---------- User-Agent rotation ----------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.96 Mobile Safari/537.36",
]

# Telegram message size limit
TELEGRAM_MAX_CHARS = 4000  # keep margin under 4096

# ==============================
# TELEGRAM HELPERS (BATCHED)
# ==============================
def _send_telegram_text(text, chat_id, max_retries=3, timeout=8):
    """Low-level single send with retry and 429 handling. Returns True if success."""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(TELEGRAM_URL, data=payload, timeout=timeout)
        except (ConnectTimeout, ReadTimeout) as e:
            print(f"⚠️ Telegram network timeout attempt {attempt}: {e}")
            time.sleep(1 * attempt)
            continue
        except Exception as e:
            print(f"⚠️ Telegram send exception attempt {attempt}: {e}")
            time.sleep(1 * attempt)
            continue

        # If Telegram returns 200, all good
        if resp.status_code == 200:
            return True

        # Handle 429: Too Many Requests
        try:
            j = resp.json()
        except Exception:
            j = {}

        if resp.status_code == 429:
            retry_after = None
            if isinstance(j, dict):
                retry_after = j.get("parameters", {}).get("retry_after")
            if retry_after is None:
                retry_after = 5  # fallback
            print(f"⚠️ Telegram 429 rate limit. retry_after={retry_after}s. Sleeping...")
            time.sleep(int(retry_after) + 1)
            continue

        # For other non-200 statuses, log and break
        print(f"❌ Telegram send failed (status {resp.status_code}): {resp.text}")
        # don't retry on 400-series other than 429
        return False

    return False


def send_telegram_batch(messages, to_log=False):
    """
    Send a list of messages to Telegram as one or more batched messages.
    - messages: list[str]
    - to_log: boolean chooses LOG_CHAT_ID when True, CHAT_ID when False
    """
    if not messages:
        return

    chat_id = LOG_CHAT_ID if to_log else CHAT_ID

    # join messages with separator, but keep under TELEGRAM_MAX_CHARS,
    # otherwise split into multiple sends.
    out = []
    current = []
    current_len = 0
    for m in messages:
        part = m.strip()
        if not part:
            continue
        # add a separator between items
        part_with_sep = part + "\n\n"
        if current_len + len(part_with_sep) > TELEGRAM_MAX_CHARS:
            # flush current
            out.append("".join(current).strip())
            current = [part_with_sep]
            current_len = len(part_with_sep)
        else:
            current.append(part_with_sep)
            current_len += len(part_with_sep)
    if current:
        out.append("".join(current).strip())

    # Send each chunk with retry/respect for rate limits
    for chunk in out:
        # wrap in code block or basic formatting as needed; using HTML safe minimal markup
        # replace any HTML-sensitive chars if necessary (here we send plain text with parse_mode HTML)
        safe_chunk = chunk
        success = _send_telegram_text(safe_chunk, chat_id)
        if not success:
            print("⚠️ Failed to send a Telegram chunk after retries.")

def fetch_products(keyword, retries=6, delay_range=(1, 2), backoff_factor=1.1):
    url = BASE_URL + quote(keyword)
    products = {}
    session = requests.Session()
    session.headers.update({
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-encoding": "gzip, deflate, br",
    })

    last_error = None  # store last error to report if all retries fail

    for attempt in range(1, retries + 1):
        chosen_proxy = random.choice(PROXY_POOL) if PROXY_POOL else None
        proxies = get_proxy_dict(chosen_proxy) if chosen_proxy else None

        ua = random.choice(USER_AGENTS)
        headers = HEADERS.copy()
        headers["user-agent"] = ua
        headers["accept-language"] = random.choice(["en-GB,en;q=0.9", "en-US,en;q=0.9", "en;q=0.8"])
        headers["referer"] = "https://www.google.com/"

        try:
            print(f"🌐 Fetching ({attempt}/{retries}) for keyword: {keyword} | UA: {ua.split(' ')[0]} | Proxy: {chosen_proxy or 'none'}")
            response = session.get(url, headers=headers, proxies=proxies, timeout=15)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            text_lower = response.text.lower()
            if ("captcha" in text_lower) or ("are you human" in text_lower) or ("verify you are a human" in text_lower):
                raise Exception("Blocked by CAPTCHA/anti-bot challenge")

            soup = BeautifulSoup(response.text, "html.parser")
            all_cards = soup.select("a._productCard__link_gvf85_7, a[data-testid*='product-card'], a[href*='/product/'], a[data-testid*='productCard']")

            # If parsing failed, retry
            if not all_cards:
                print(f"⚠️ No product cards found for '{keyword}' (Attempt {attempt})")
                sleep_time = random.uniform(*delay_range) * (backoff_factor ** (attempt - 1))
                time.sleep(sleep_time)
                continue

            # Extract products
            for card in all_cards:
                href = card.get("href")
                if not href:
                    continue
                link = href if href.startswith("http") else "https://www.very.co.uk" + href
                titletag = card.find("h3")
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

            # ✅ Success → exit retry loop
            if products:
                return products

        except (ProxyError, ConnectTimeout, ReadTimeout) as e:
            last_error = f"⚠️ Proxy/Timeout error ({keyword}) attempt {attempt}: {e} url:{url} proxy:{chosen_proxy}"
            print(last_error)

        except RequestException as e:
            last_error = f"⚠️ Requests exception ({keyword}) attempt {attempt}: {e} url:{url}"
            print(last_error)

        except Exception as e:
            last_error = f"⚠️ Error ({keyword}) attempt {attempt}: {e} url:{url}"
            print(last_error)

        # ✅ Only reach here if an error occurred
        sleep_time = random.uniform(*delay_range) * (backoff_factor ** (attempt - 1))
        time.sleep(sleep_time)

    # After all retries, if still empty:
    print(f"❌ Failed to fetch data for {keyword} after {retries} retries.")
    if last_error:
        print(f"Last error: {last_error}")

    return products  # empty dict if fail


def load_previous_data():
    if not os.path.exists(CSV_FILE):
        return {}
    data = {}
    with open(CSV_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row["url"]] = row
    return data


def save_to_csv(data):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["keyword", "title", "price", "url", "status"])
        writer.writeheader()
        for url, info in data.items():
            writer.writerow(info)


def monitor_products():
    """Main loop for monitoring product availability - batches telegram messages."""
    print("🛍️ Monitoring Very.co.uk for multiple keywords ...\n")

    previous_data = load_previous_data()

    while True:
        start_time = datetime.utcnow()
        loop_logs = []    # will be sent to LOG_CHAT_ID
        loop_alerts = []  # will be sent to ALERT CHAT_ID

        current_data = {}

        # For each keyword, attempt fetch and collect logs & alerts (but don't send immediately)
        for keyword in KEYWORDS:
            # small randomized delay to reduce pattern
            time.sleep(random.uniform(0.8, 1.8))
            try:
                keyword_products = fetch_products(keyword)
                current_data.update(keyword_products)
                loop_logs.append(f"📦 {keyword}: {len(keyword_products)} products found")
            except Exception as e:
                # Capture the error text and continue; don't spam Telegram immediately
                err_text = f"⚠️ Error fetching '{keyword}': {str(e)}"
                print(err_text)
                loop_logs.append(err_text)
                # continue to next keyword
                continue

        # Analyze results and build alerts
        # New or back-in-stock
        for url, info in current_data.items():
            if url not in previous_data:
                loop_alerts.append(f"🆕 [{info['keyword']}] New product: {info['title']} ({info['price']})\n{info['url']}")
            elif previous_data[url]["status"] == "Out of Stock":
                loop_alerts.append(f"✅ [{info['keyword']}] Back in stock: {info['title']} ({info['price']})\n{info['url']}")
            current_data[url]["status"] = "In Stock"

        # Out of stock detection
        for url, info in previous_data.items():
            if url not in current_data and info["status"] == "In Stock":
                loop_alerts.append(f"❌ [{info['keyword']}] Out of stock: {info['title']}\n{info['url']}")
                info["status"] = "Out of Stock"
                current_data[url] = info  # keep it so CSV retains history

        # If no data fetched this loop, add a log entry
        if not current_data:
            loop_logs.append("⚠️ No valid data fetched this round (possible block or network issue).")

        # Save CSV and update previous_data
        save_to_csv(current_data)
        previous_data = current_data

        # Add a summary log (timing and counts)
        round_log = f"🕒 Round finished | Keywords: {len(KEYWORDS)} | Tracked products: {len(current_data)} | Duration: {(datetime.utcnow() - start_time).seconds}s"
        loop_logs.insert(0, round_log)

        # Send batched messages to Telegram (logs and alerts separately)
        # Send logs to LOG_CHAT_ID
        if loop_logs:
            # limit verbose logs if too many
            if len(loop_logs) > 50:
                loop_logs = loop_logs[:50] + [f"...and {len(loop_logs)-50} more log lines omitted."]
            send_telegram_batch(loop_logs, to_log=True)

        # Send alerts to Alerts chat (stacked)
        if loop_alerts:
            # dedupe alerts (optional)
            deduped_alerts = []
            seen = set()
            for a in loop_alerts:
                if a not in seen:
                    deduped_alerts.append(a)
                    seen.add(a)
            send_telegram_batch(deduped_alerts, to_log=False)

        # Delay before next full loop - keep reasonable
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
        # Try to send fatal error to logs (use direct minimal send)
        try:
            send_telegram_batch([f"🔴 Fatal error in scraper: {e}"], to_log=True)
        except Exception:
            pass
