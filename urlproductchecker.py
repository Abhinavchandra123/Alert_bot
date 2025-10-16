# monitor_products_batched.py
import os
import time
import random
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from requests.exceptions import ProxyError, ConnectTimeout, ReadTimeout, RequestException

# ==============================
# TELEGRAM SETUP
# ==============================
BOT_TOKEN = "8449824077:AAHlJqCVQiSRlTm8--VxfK-crjNMSVlwXsU"
CHAT_ID = "-1003062286470"       # Main alert channel/group
LOG_CHAT_ID = "-1003026899918"   # Log group/channel
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

TELEGRAM_MAX_CHARS = 4000  # keep margin under 4096

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

        if resp.status_code == 200:
            return True

        # Handle 429: Too Many Requests
        retry_after = None
        try:
            j = resp.json()
            if isinstance(j, dict):
                retry_after = j.get("parameters", {}).get("retry_after")
        except Exception:
            pass

        if resp.status_code == 429:
            if retry_after is None:
                retry_after = 5
            print(f"⚠️ Telegram 429. retry_after={retry_after}s. Sleeping...")
            time.sleep(int(retry_after) + 1)
            continue

        print(f"❌ Telegram send failed (status {resp.status_code}): {resp.text}")
        return False

    return False


def send_telegram_batch(messages, to_log=False):
    """
    Send a list of messages to Telegram as one or more batched messages.
    - messages: list[str]
    - to_log: choose LOG_CHAT_ID when True, else CHAT_ID
    """
    if not messages:
        return
    chat_id = LOG_CHAT_ID if to_log else CHAT_ID

    # join with separator but respect Telegram char limit
    out_chunks = []
    current = []
    current_len = 0
    for m in messages:
        part = (m or "").strip()
        if not part:
            continue
        part_with_sep = part + "\n\n"
        if current_len + len(part_with_sep) > TELEGRAM_MAX_CHARS:
            out_chunks.append("".join(current).strip())
            current = [part_with_sep]
            current_len = len(part_with_sep)
        else:
            current.append(part_with_sep)
            current_len += len(part_with_sep)
    if current:
        out_chunks.append("".join(current).strip())

    for chunk in out_chunks:
        success = _send_telegram_text(chunk, chat_id)
        if not success:
            print("⚠️ Failed to send a Telegram chunk after retries.")

# ==============================
# CONFIG
# ==============================
product_links = [
    "https://www.very.co.uk/pokemon-pokemon-tcg-mega-evolution-elite-trainer-box-gardevoir/1601213546.prd",
    "https://www.very.co.uk/pokemon-tcg-mega-evolution-booster-display-full-cdu/1601213547.prd",
    "https://www.very.co.uk/pokemon-tcg-scarlet-violet-105-white-flare-elite-trainer-box-reshiram/1601182744.prd",
    "https://very.co.uk/1601182741.prd",
    "https://very.co.uk/1601113897.prd",
    "https://very.co.uk/1601182744.prd",
    "https://very.co.uk/1601205287.prd",
    "https://very.co.uk/1601205275.prd",
    "https://very.co.uk/1601205318.prd",
    "https://www.very.co.uk/ucc-match-attax-202526-booster-tins/1601183881.prd",
    "https://www.very.co.uk/mega-pokemon-building-set-charmander-evolution/1600888825.prd",
    "https://www.very.co.uk/nintendo-switch-pokeacutemon-legends-z-a/1601044127.prd",
    "https://www.very.co.uk/nintendo-switch-2-pokeacutemon-legends-z-a/1601044125.prd",
    "https://www.very.co.uk/monopoly-pokemon/1601109926.prd",
    ""
]

# Base headers; UA will be rotated per request
BASE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-GB,en;q=0.9",
    "upgrade-insecure-requests": "1",
    "sec-ch-ua": '"Google Chrome";v="141", "Chromium";v="141", "Not?A_Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "referer": "https://www.google.com/",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.96 Mobile Safari/537.36",
]

# ==============================
# PROXY (env or fallback)
# ==============================
DEFAULT_PROXY = "http://OhovjuoxW47tvp53Cy-res-UK:5N0KkB6uYbP77Pa@gw.thunderproxy.net:5959"
SCRAPER_PROXY = os.environ.get("SCRAPER_PROXY", DEFAULT_PROXY)
proxy_env_list = os.environ.get("SCRAPER_PROXY_LIST")
if proxy_env_list:
    PROXY_POOL = [p.strip() for p in proxy_env_list.split(",") if p.strip()]
else:
    PROXY_POOL = [SCRAPER_PROXY]

def get_proxy_dict(proxy_url):
    return {"http": proxy_url, "https": proxy_url}

# Keep last known status to detect OUT -> IN transitions
last_status = {}

# Try to import winsound on Windows; ignore on Linux
try:
    import winsound
    CAN_BEEP = True
except Exception:
    CAN_BEEP = False


# ==============================
# HTTP helper with session/UA/proxy/retries
# ==============================
def fetch_page(url, retries=4, backoff=1.5, timeout=15):
    """
    Fetch a page with a session, rotating UA and proxy, with retry/backoff.
    Returns response.text or raises.
    """
    session = requests.Session()
    session.headers.update(BASE_HEADERS)

    for attempt in range(1, retries + 1):
        ua = random.choice(USER_AGENTS)
        headers = dict(session.headers)
        headers["user-agent"] = ua
        headers["accept-language"] = random.choice(["en-GB,en;q=0.9", "en-US,en;q=0.9", "en;q=0.8"])

        chosen_proxy = random.choice(PROXY_POOL) if PROXY_POOL else None
        proxies = get_proxy_dict(chosen_proxy) if chosen_proxy else None

        try:
            print(f"🌐 GET ({attempt}/{retries}) {url} | UA: {ua.split(' ')[0]} | Proxy: {chosen_proxy or 'none'}")
            resp = session.get(url, headers=headers, proxies=proxies, timeout=timeout)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")

            # crude anti-bot check
            low = resp.text.lower()
            if "captcha" in low or "are you human" in low or "verify you are a human" in low:
                raise Exception("Blocked by CAPTCHA/anti-bot")

            return resp.text

        except (ProxyError, ConnectTimeout, ReadTimeout) as e:
            print(f"⚠️ Proxy/Timeout: {e}")
        except RequestException as e:
            print(f"⚠️ Requests error: {e}")
        except Exception as e:
            print(f"⚠️ Error: {e}")

        # backoff before retry
        time.sleep((backoff ** (attempt - 1)) * random.uniform(1.2, 2.0))

    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


# ==============================
# CHECK FUNCTION
# ==============================
def check_in_stock(url):
    """Return True if the product page looks 'in stock' (basic heuristic)."""
    try:
        html = fetch_page(url, retries=2, backoff=1.5, timeout=15)
        soup = BeautifulSoup(html, "html.parser")
        title = soup.find("span", {"data-testid": "product_title"})
        return bool(title)
    except Exception as e:
        print(f"⚠️ Request error for {url}: {e}")
        # We'll collect this in loop logs instead of sending immediately
        return None  # None = could not determine (treated as out/not in stock for alerting)


# ==============================
# MONITOR LOOP (BATCHED TELEGRAM)
# ==============================
print("🔄 Monitoring products every 60 seconds... Press Ctrl + C to stop.\n")
# Initial log (batched)
send_telegram_batch(["🟢 Product monitor started successfully."], to_log=True)

while True:
    loop_start = datetime.utcnow()
    loop_logs = []
    loop_alerts = []

    total_in_stock = 0
    total_out = 0

    for link in product_links:
        if not (link or "").strip():
            continue

        in_stock = check_in_stock(link)
        prev_status = last_status.get(link)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # None -> treat as out for counting, but log error
        if in_stock is None:
            loop_logs.append(f"⚠️ Error checking: {link}")
            total_out += 1
            last_status[link] = False
            time.sleep(1.5)
            continue

        if in_stock:
            total_in_stock += 1
            # Alert only on OUT -> IN transition
            if prev_status is False:
                # Try to extract a readable name
                try:
                    name_part = link.rstrip("/").split("/")[-2]
                    product_name = name_part.replace('-', ' ').title()
                except Exception:
                    product_name = link

                alert_msg = f"🚨 IN STOCK: {product_name}\n🕒 {now_str}\n🔗 {link}"
                print(alert_msg)
                if CAN_BEEP:
                    try:
                        winsound.Beep(1000, 800)
                    except Exception:
                        pass
                loop_alerts.append(alert_msg)
            else:
                print(f"✅ In stock ({now_str}): {link}")
        else:
            total_out += 1
            print(f"❌ Out of stock ({now_str}): {link}")

        last_status[link] = bool(in_stock)
        time.sleep(1.5)

    # Summary log for this loop
    summary = f"🕒 {datetime.now().strftime('%H:%M:%S')} | Checked {len([u for u in product_links if u.strip()])} products\n✅ In Stock: {total_in_stock}\n❌ Out of Stock: {total_out}"
    print(f"\n{summary}\n")
    loop_logs.insert(0, summary)  # put summary at top

    # SEND BATCHED MESSAGES
    if loop_logs:
        # cap extremely long logs
        if len(loop_logs) > 50:
            loop_logs = loop_logs[:50] + [f"...and {len(loop_logs)-50} more log lines omitted."]
        send_telegram_batch(loop_logs, to_log=True)

    if loop_alerts:
        # dedupe alerts
        deduped = []
        seen = set()
        for a in loop_alerts:
            if a not in seen:
                seen.add(a)
                deduped.append(a)
        send_telegram_batch(deduped, to_log=False)

    # pacing between loops
    dur = (datetime.utcnow() - loop_start).seconds
    print(f"⏳ Waiting 60 seconds before next check... (Loop duration {dur}s)\n")
    time.sleep(60)
