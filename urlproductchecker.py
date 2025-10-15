import requests
from bs4 import BeautifulSoup
import time
import winsound  # For Windows sound alert
from datetime import datetime  # For timestamps

# ==============================
# TELEGRAM SETUP
# ==============================
BOT_TOKEN = "8449824077:AAHlJqCVQiSRlTm8--VxfK-crjNMSVlwXsU"
CHAT_ID = "-1003062286470"       # Main alert channel/group
LOG_CHAT_ID = "-1003026899918"   # Log group/channel
TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

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

HEADERS = {
    "authority": "www.very.co.uk",
    "method": "GET",
    "scheme": "https",
    "cache-control": "max-age=0",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Google Chrome";v="141", "Chromium";v="141", "Not?A_Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
}

last_status = {}


# ==============================
# FUNCTIONS
# ==============================
def check_in_stock(url):
    """Check if product is in stock."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            msg = f"⚠️ Failed to fetch {url} (Status {response.status_code})"
            print(msg)
            send_telegram_alert(msg, to_log=True)
            return False

        soup = BeautifulSoup(response.text, "html.parser")

        # Product title usually means the page loaded successfully
        title = soup.find("span", {"data-testid": "product_title"})
        return bool(title)

    except requests.RequestException as e:
        msg = f"⚠️ Request error for {url}: {e}"
        print(msg)
        send_telegram_alert(msg, to_log=True)
        return False


# ==============================
# MONITOR LOOP
# ==============================
print("🔄 Monitoring products every 60 seconds... Press Ctrl + C to stop.\n")
send_telegram_alert("🟢 Product monitor started successfully.", to_log=True)

while True:
    try:
        total_in_stock = 0
        total_out = 0

        for link in product_links:
            if not link.strip():
                continue  # Skip empty lines

            in_stock = check_in_stock(link)
            prev_status = last_status.get(link)
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Alert only on transition from OUT → IN
            if in_stock and prev_status is False:
                product_name = link.split('/')[-2].replace('-', ' ').title()
                message = f"🚨 IN STOCK ALERT: {product_name}\n🕒 Time: {current_time}\n🔗 {link}"
                print(message)
                winsound.Beep(1000, 800)
                send_telegram_alert(message)

            elif in_stock:
                print(f"✅ In stock ({current_time}): {link}")
                total_in_stock += 1
            else:
                print(f"❌ Out of stock ({current_time}): {link}")
                total_out += 1

            last_status[link] = in_stock
            time.sleep(2)

        # --- Log summary to Telegram every loop ---
        summary = f"🕒 {datetime.now().strftime('%H:%M:%S')} | Checked {len(product_links)} products\n✅ In Stock: {total_in_stock}\n❌ Out of Stock: {total_out}"
        print(f"\n{summary}\n")
        send_telegram_alert(summary, to_log=True)

        print("⏳ Waiting 10 seconds before next check...\n")
        time.sleep(60)

    except Exception as e:
        err = f"💥 Unexpected error in main loop: {e}"
        print(err)
        send_telegram_alert(err, to_log=True)
        time.sleep(10)