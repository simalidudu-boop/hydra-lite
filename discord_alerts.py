
"""
HYDRA LITE — Discord Alert System
Real-time notifications to your Discord channel
"""

import requests
from datetime import datetime, timezone
from config import DISCORD_WEBHOOK


def send_discord(content, username="HYDRA LITE 🐍"):
    """Send a message to Discord webhook"""
    if not DISCORD_WEBHOOK:
        print("⚠️ No Discord webhook configured")
        return

    try:
        data = {
            "content": content,
            "username": username,
        }
        response = requests.post(
            DISCORD_WEBHOOK,
            json=data,
            timeout=10
        )
        if response.status_code not in [200, 204]:
            print(f"⚠️ Discord error: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Discord send failed: {e}")


def alert_trade_opened(pair, side, entry, size, leverage,
                       tp1, tp2, tp3, sl, risk_pct,
                       risk_usd, confluence, signals, balance):
    """Alert when a new trade is opened"""

    side_emoji = "🟢 LONG" if side == "long" else "🔴 SHORT"
    signal_display = ""
    for name, passed in signals.items():
        signal_display += f"{'✅' if passed else '⬜'} {name}\n"

    msg = f"""
