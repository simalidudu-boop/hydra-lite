
"""
HYDRA LITE — Configuration
Zimbabwe Edition
Built for $20 seed capital on GitHub Actions
"""

import os

# ═══════════════════════════════════════════
# EXCHANGE CONFIGURATION
# ═══════════════════════════════════════════
EXCHANGE = "bybit"
BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")

# ═══════════════════════════════════════════
# DISCORD CONFIGURATION  
# ═══════════════════════════════════════════
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")

# ═══════════════════════════════════════════
# TRADING PAIRS
# ═══════════════════════════════════════════
PAIRS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "LINK/USDT:USDT",
    "AVAX/USDT:USDT",
]

# ═══════════════════════════════════════════
# RISK PARAMETERS — CONTROLLED AGGRESSIVE
# ═══════════════════════════════════════════
RISK_PER_TRADE = 0.015          # 1.5% of account per trade
MAX_POSITIONS = 3               # Maximum simultaneous positions
MAX_PORTFOLIO_HEAT = 0.045      # 4.5% total risk at any time
DEFAULT_LEVERAGE = 5            # 5x leverage
MAX_LEVERAGE = 5                # Hard cap

# ═══════════════════════════════════════════
# CIRCUIT BREAKERS — SURVIVAL SYSTEM
# ═══════════════════════════════════════════
DAILY_LOSS_LIMIT = 0.04         # 4% daily loss → stop trading
DAILY_LOSS_PAUSE_HOURS = 12     # Pause duration after daily limit
WEEKLY_LOSS_LIMIT = 0.10        # 10% weekly loss → reduce size
DRAWDOWN_REDUCE_THRESHOLD = 0.08  # 8% drawdown → cut size 40%
DRAWDOWN_PAUSE_THRESHOLD = 0.12   # 12% drawdown → pause 48hrs
MAX_CONSECUTIVE_LOSSES = 4      # 4 losses in a row → pause 6hrs

# ═══════════════════════════════════════════
# STRATEGY PARAMETERS
# ═══════════════════════════════════════════
# Trend Detection (4H)
TREND_EMA_PERIOD = 21
TREND_TIMEFRAME = "4h"

# Entry Zone (1H)  
ENTRY_EMA_PERIOD = 21
ENTRY_TIMEFRAME = "1h"
ENTRY_LOOKBACK_CANDLES = 50

# Trigger (15min)
TRIGGER_TIMEFRAME = "15m"
TRIGGER_RSI_PERIOD = 14
TRIGGER_RSI_LONG_MIN = 35
TRIGGER_RSI_LONG_MAX = 50
TRIGGER_RSI_SHORT_MIN = 50
TRIGGER_RSI_SHORT_MAX = 65
TRIGGER_VOLUME_MULTIPLIER = 1.5

# ═══════════════════════════════════════════
# TAKE PROFIT & STOP LOSS (ATR-based)
# ═══════════════════════════════════════════
ATR_PERIOD = 14
STOP_LOSS_ATR_MULTIPLIER = 1.2      # SL at 1.2x ATR
TAKE_PROFIT_1_ATR_MULTIPLIER = 1.5  # TP1 at 1.5x ATR
TAKE_PROFIT_2_ATR_MULTIPLIER = 2.5  # TP2 at 2.5x ATR
TAKE_PROFIT_3_ATR_MULTIPLIER = 4.0  # TP3 at 4.0x ATR

# Position closing percentages at each TP
TP1_CLOSE_PERCENT = 0.40  # Close 40% at TP1
TP2_CLOSE_PERCENT = 0.35  # Close 35% at TP2
TP3_CLOSE_PERCENT = 0.25  # Close remaining 25% at TP3

# ═══════════════════════════════════════════
# FUNDING RATE EDGE
# ═══════════════════════════════════════════
FUNDING_RATE_THRESHOLD = 0.0005  # 0.05% funding = significant

# ═══════════════════════════════════════════
# MINIMUM ORDER SIZES (Bybit minimums)
# ═══════════════════════════════════════════
MIN_ORDER_SIZES = {
    "BTC/USDT:USDT": 0.001,
    "ETH/USDT:USDT": 0.01,
    "SOL/USDT:USDT": 0.1,
    "LINK/USDT:USDT": 0.1,
    "AVAX/USDT:USDT": 0.1,
}
