import os
from dotenv import load_dotenv
from curl_cffi import requests
import asyncio
import datetime
import logging

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

TELEGRAM_API_KEY = os.getenv("TELEGRAM_API_KEY")
USER_IDS = [
    int(uid) for uid in os.getenv("TELEGRAM_USER_IDS", "").split(",") if uid.strip()
]
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

# In-memory state for watched tokens
WATCHED_TOKENS = {}  # key: token_id, value: dict with start_time, notified, contract_address_sent, monitoring_started


def ensure_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def format_human_datetime(dt):
    return dt.strftime("%Y-%m-%d %H:%M UTC")


# --- Telegram notification function ---
def send_telegram_message(user_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_API_KEY}/sendMessage"
    data = {"chat_id": user_id, "text": text}
    try:
        resp = requests.post(url, data=data)
        resp.raise_for_status()
        logger.info(f"Sent Telegram message to {user_id}: {text}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message to {user_id}: {e}")


# --- Poll the API for upcoming tokens every 3 hours ---
async def poll_upcoming_tokens():
    while True:
        try:
            logger.info("Polling for upcoming tokens...")
            response = requests.get(
                "https://hot-data.politicalpump.com/tokens?is_upcoming=true&page=1&page_size=50&sort_order=asc&sort_by=start_time",
                headers={"User-Agent": USER_AGENT},
            )
            tokens = response.json().get("items", [])
            now = datetime.datetime.now(datetime.UTC)
            logger.info(f"Found {len(tokens)} upcoming tokens.")
            for token in tokens:
                token_id = token["_id"]
                start_time = ensure_utc(
                    datetime.datetime.fromisoformat(token["start_time"])
                )
                if token_id not in WATCHED_TOKENS and start_time > now:
                    WATCHED_TOKENS[token_id] = {
                        "start_time": start_time,
                        "notified": False,
                        "contract_address_sent": False,
                        "monitoring_started": False,
                        "name": token.get("name", "?"),
                        "symbol": token.get("symbol", "?"),
                    }
                    logger.info(
                        f"Added token {token.get('name', '?')} ({token.get('symbol', '?')}) to watch queue for {format_human_datetime(start_time)}."
                    )
                    # Notify users about new token being watched
                    for uid in USER_IDS:
                        send_telegram_message(
                            uid,
                            f"Watching token {token.get('name', '?')} ({token.get('symbol', '?')}) for release at {format_human_datetime(start_time)}",
                        )
        except Exception as e:
            logger.error(f"Error polling upcoming tokens: {e}")
        await asyncio.sleep(3 * 60 * 60)  # 3 hours


# --- Monitor a specific token for contract address release ---
async def monitor_token_release(token_id, token_info):
    now = datetime.datetime.now(datetime.UTC)
    wait_seconds = (token_info["start_time"] - now).total_seconds() - 60
    if wait_seconds > 0:
        logger.info(
            f"Token {token_info['name']} ({token_info['symbol']}) monitoring will start in {wait_seconds:.1f} seconds."
        )
        await asyncio.sleep(wait_seconds)
    logger.info(
        f"Started frequent monitoring for token {token_info['name']} ({token_info['symbol']})..."
    )
    # Poll every 2 seconds until contract_address is found
    while not token_info["contract_address_sent"]:
        try:
            response = requests.get(
                "https://hot-data.politicalpump.com/tokens?page=1&page_size=50&sort_order=asc&sort_by=start_time",
                headers={"User-Agent": USER_AGENT},
            )
            tokens = response.json().get("items", [])
            for token in tokens:
                if token["_id"] == token_id and token.get("contract_address"):
                    contract_address = token["contract_address"]
                    if (
                        contract_address
                        and isinstance(contract_address, str)
                        and contract_address.strip()
                    ):
                        logger.info(
                            f"Token {token.get('name', '?')} released! Contract address: {contract_address}"
                        )
                        for uid in USER_IDS:
                            send_telegram_message(
                                uid,
                                f"🚨 TOKEN RELEASED! 🚨\nName: {token.get('name', '?')} ({token.get('symbol', '?')})\nContract Address: \n```\n{contract_address}\n```\nRelease Time: {format_human_datetime(token_info['start_time'])}",
                            )
                        token_info["contract_address_sent"] = True
                        break
        except Exception as e:
            logger.error(f"Error monitoring token {token_id}: {e}")
        await asyncio.sleep(2)


# --- Main async loop ---
async def main():
    logger.info("Starting main event loop.")
    # Start the periodic polling task
    asyncio.create_task(poll_upcoming_tokens())
    while True:
        now = datetime.datetime.now(datetime.UTC)
        # Start monitoring tasks for tokens whose start_time is near and not yet being monitored
        for token_id, info in list(WATCHED_TOKENS.items()):
            if (
                not info.get("monitoring_started")
                and (info["start_time"] - now).total_seconds() < 3600  # 1 hour before
            ):
                info["monitoring_started"] = True
                logger.info(
                    f"Scheduling monitoring for token {info['name']} ({info['symbol']}) at {format_human_datetime(info['start_time'])}."
                )
                asyncio.create_task(monitor_token_release(token_id, info))
        await asyncio.sleep(30)


if __name__ == "__main__":
    logger.info("Bot started.")
    asyncio.run(main())
