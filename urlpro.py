import os
import time
import random
import logging
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

import requests  # used only for Telegram sends

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("monitor-selenium")

# ---------------------------
# Telegram config (from env)
# ---------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8449824077:AAHlJqCVQiSRlTm8--VxfK-crjNMSVlwXsU")
CHAT_ID = os.environ.get("CHAT_ID", "-1003062286470")
LOG_CHAT_ID = os.environ.get("LOG_CHAT_ID", "-1003026899918")
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
TELEGRAM_MAX_CHARS = 4000

def _send_telegram_text(text, chat_id, max_retries=3, timeout=8):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    for attempt in range(1, max_retries+1):
        try:
            resp = requests.post(TELEGRAM_URL, data=payload, timeout=timeout)
        except Exception as e:
            log.warning("Telegram send exception attempt %s: %s", attempt, e)
            time.sleep(1 * attempt)
            continue

        if resp.status_code == 200:
            return True

        if resp.status_code == 429:
            # try to parse retry_after
            try:
                j = resp.json()
                retry_after = j.get("parameters", {}).get("retry_after", 5)
            except Exception:
                retry_after = 5
            log.warning("Telegram 429, retry_after=%s", retry_after)
            time.sleep(int(retry_after) + 1)
            continue

        log.error("Telegram send failed (status %s): %s", resp.status_code, resp.text)
        return False

    return False

def send_telegram_batch(messages, to_log=False):
    if not messages:
        return
    chat_id = LOG_CHAT_ID if to_log else CHAT_ID
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
            log.warning("Failed to send a Telegram chunk after retries.")

# ---------------------------
# Monitor configuration
# ---------------------------
# Put your product URLs here (or load from a file/env)
product_links = [
    "https://www.very.co.uk/pokemon-pokemon-tcg-mega-evolution-elite-trainer-box-gardevoir/1601213546.prd",
    "https://www.very.co.uk/pokemon-tcg-mega-evolution-booster-display-full-cdu/1601213547.prd",
    "https://www.very.co.uk/pokemon-tcg-scarlet-violet-105-white-flare-elite-trainer-box-reshiram/1601182744.prd",
    # ... add more
]

# user agents (we will pick one at driver start)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Mobile Safari/537.36",
]

# Proxy support via env (single proxy) or comma-separated list
DEFAULT_PROXY = os.environ.get("DEFAULT_PROXY", "")
proxy_env_list = os.environ.get("SCRAPER_PROXY_LIST")
if proxy_env_list:
    PROXY_POOL = [p.strip() for p in proxy_env_list.split(",") if p.strip()]
elif DEFAULT_PROXY:
    PROXY_POOL = [DEFAULT_PROXY]
else:
    PROXY_POOL = []

# last status to detect transitions
last_status = {}

# ---------------------------
# Selenium helper
# ---------------------------
def make_chrome_options(user_agent: str = None, proxy: Optional[str] = None):
    opts = Options()
    # headless best practice for modern chrome
    # opts.add_argument("--headless=new")  # try new headless mode
    # opts.add_argument("--no-sandbox")
    # opts.add_argument("--disable-gpu")
    # opts.add_argument("--disable-dev-shm-usage")
    # opts.add_argument("--window-size=1200,800")
    # less logging
    opts.add_argument("--log-level=3")
    # avoid images (optional) to save bandwidth - uncomment if desired
    # prefs = {"profile.managed_default_content_settings.images": 2}
    # opts.add_experimental_option("prefs", prefs)
    if user_agent:
        opts.add_argument(f"--user-agent={user_agent}")
    # Proxy format might be http://user:pass@host:port or host:port
    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")
    return opts

def fetch_page_selenium(url: str, timeout: int = 20, retries: int = 3, backoff: float = 1.5) -> str:
    """
    Fetch page using Selenium. Returns page_source string or raises RuntimeError.
    Creates a single driver per attempt (clean), which is safer for proxy/UA rotation.
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        ua = random.choice(USER_AGENTS)
        proxy = random.choice(PROXY_POOL) if PROXY_POOL else None
        opts = make_chrome_options(user_agent=ua, proxy=proxy)
        # instantiate driver using webdriver-manager
        driver = None
        try:
            log.info("Selenium GET (%s/%s) %s | UA=%s | Proxy=%s", attempt, retries, url, ua.split(" ")[0], proxy or "none")
            driver = webdriver.Chrome(ChromeDriverManager().install(), options=opts)
            driver.set_page_load_timeout(timeout)
            driver.get(url)
            time.sleep(random.uniform(1.0, 2.5))  # small wait for JS content to settle
            page = driver.page_source
            low = page.lower()
            if "captcha" in low or "are you human" in low or "verify you are a human" in low:
                raise RuntimeError("Blocked by CAPTCHA/anti-bot")
            return page
        except (WebDriverException, TimeoutException, RuntimeError) as e:
            last_exc = e
            log.warning("Attempt %s failed: %s", attempt, e)
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
        time.sleep((backoff ** (attempt - 1)) * random.uniform(1.2, 2.0))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts. Last error: {last_exc}")

# ---------------------------
# In-stock checker (uses bs4 to parse)
# ---------------------------
def check_in_stock(url: str) -> Optional[bool]:
    try:
        html = fetch_page_selenium(url, retries=2, backoff=1.5, timeout=20)
        soup = BeautifulSoup(html, "html.parser")
        # keep same heuristic as your original: check for product title element
        title = soup.find("span", {"data-testid": "product_title"})
        return bool(title)
    except Exception as e:
        log.warning("Error checking %s : %s", url, e)
        return None

# ---------------------------
# Main loop
# ---------------------------
def main_loop(pause_seconds: int = 60):
    log.info("🔄 Monitoring products every %s seconds...", pause_seconds)
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

            if in_stock is None:
                loop_logs.append(f"⚠️ Error checking: {link}")
                total_out += 1
                last_status[link] = False
                time.sleep(1.5)
                continue

            if in_stock:
                total_in_stock += 1
                if prev_status is False:
                    try:
                        name_part = link.rstrip("/").split("/")[-2]
                        product_name = name_part.replace('-', ' ').title()
                    except Exception:
                        product_name = link
                    alert_msg = f"🚨 IN STOCK: {product_name}\n🕒 {now_str}\n🔗 {link}"
                    log.info(alert_msg)
                    loop_alerts.append(alert_msg)
                else:
                    log.info("✅ In stock (%s): %s", now_str, link)
            else:
                total_out += 1
                log.info("❌ Out of stock (%s): %s", now_str, link)

            last_status[link] = bool(in_stock)
            time.sleep(1.5)

        summary = f"🕒 {datetime.now().strftime('%H:%M:%S')} | Checked {len([u for u in product_links if u.strip()])} products\n✅ In Stock: {total_in_stock}\n❌ Out of Stock: {total_out}"
        log.info("\n%s\n", summary)
        loop_logs.insert(0, summary)

        if loop_logs:
            if len(loop_logs) > 50:
                loop_logs = loop_logs[:50] + [f"...and {len(loop_logs)-50} more log lines omitted."]
            send_telegram_batch(loop_logs, to_log=True)

        if loop_alerts:
            deduped = []
            seen = set()
            for a in loop_alerts:
                if a not in seen:
                    seen.add(a)
                    deduped.append(a)
            send_telegram_batch(deduped, to_log=False)

        dur = (datetime.utcnow() - loop_start).seconds
        log.info("⏳ Loop duration %s s. Sleeping %s s...", dur, pause_seconds)
        time.sleep(pause_seconds)


if __name__ == "__main__":
    try:
        main_loop(pause_seconds=int(os.environ.get("LOOP_DELAY", "60")))
    except KeyboardInterrupt:
        log.info("Stopping monitor (KeyboardInterrupt).")
