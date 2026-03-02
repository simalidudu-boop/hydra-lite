
"""
HYDRA LITE — Signal Generator
The brain that finds trading opportunities
"""

import numpy as np
from config import (
    TREND_EMA_PERIOD, TRIGGER_RSI_PERIOD,
    TRIGGER_RSI_LONG_MIN, TRIGGER_RSI_LONG_MAX,
    TRIGGER_RSI_SHORT_MIN, TRIGGER_RSI_SHORT_MAX,
    TRIGGER_VOLUME_MULTIPLIER, ATR_PERIOD,
    FUNDING_RATE_THRESHOLD, ENTRY_EMA_PERIOD,
)


def calculate_ema(closes, period):
    """Calculate Exponential Moving Average"""
    if len(closes) < period:
        return None

    multiplier = 2 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    return ema


def calculate_rsi(closes, period=14):
    """Calculate Relative Strength Index"""
    if len(closes) < period + 1:
        return None

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_atr(highs, lows, closes, period=14):
    """Calculate Average True Range"""
    if len(closes) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    return np.mean(true_ranges[-period:])


def find_support_resistance(highs, lows, closes, lookback=50):
    """Find key support and resistance levels"""
    if len(closes) < lookback:
        lookback = len(closes)

    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]

    # Find swing highs (resistance)
    resistances = []
    for i in range(2, len(recent_highs) - 2):
        if (recent_highs[i] > recent_highs[i-1] and
            recent_highs[i] > recent_highs[i-2] and
            recent_highs[i] > recent_highs[i+1] and
            recent_highs[i] > recent_highs[i+2]):
            resistances.append(recent_highs[i])

    # Find swing lows (support)
    supports = []
    for i in range(2, len(recent_lows) - 2):
        if (recent_lows[i] < recent_lows[i-1] and
            recent_lows[i] < recent_lows[i-2] and
            recent_lows[i] < recent_lows[i+1] and
            recent_lows[i] < recent_lows[i+2]):
            supports.append(recent_lows[i])

    return supports, resistances


def check_trend(closes_4h):
    """
    CHECK 1: TREND ALIGNMENT (4H)
    Returns: 'long', 'short', or 'neutral'
    """
    if closes_4h is None or len(closes_4h) < TREND_EMA_PERIOD + 5:
        return "neutral"

    ema_now = calculate_ema(closes_4h, TREND_EMA_PERIOD)
    ema_prev = calculate_ema(closes_4h[:-3], TREND_EMA_PERIOD)

    if ema_now is None or ema_prev is None:
        return "neutral"

    current_price = closes_4h[-1]

    # Price above rising EMA = uptrend
    if current_price > ema_now and ema_now > ema_prev:
        return "long"
    # Price below falling EMA = downtrend
    elif current_price < ema_now and ema_now < ema_prev:
        return "short"
    else:
        return "neutral"


def check_entry_zone(closes_1h, highs_1h, lows_1h, trend):
    """
    CHECK 2: ENTRY ZONE (1H)
    Is price at a good pullback entry?
    """
    if closes_1h is None or len(closes_1h) < ENTRY_EMA_PERIOD + 5:
        return False

    current_price = closes_1h[-1]
    ema = calculate_ema(closes_1h, ENTRY_EMA_PERIOD)

    if ema is None:
        return False

    # Calculate distance from EMA as percentage
    distance = abs(current_price - ema) / ema

    supports, resistances = find_support_resistance(
        highs_1h, lows_1h, closes_1h
    )

    if trend == "long":
        # For longs: price should be near EMA (pullback)
        # or at support level
        near_ema = current_price > ema and distance < 0.015
        at_support = any(
            abs(current_price - s) / current_price < 0.005
            for s in supports
        )
        return near_ema or at_support

    elif trend == "short":
        # For shorts: price should be near EMA (pullback up)
        # or at resistance level
        near_ema = current_price < ema and distance < 0.015
        at_resistance = any(
            abs(current_price - r) / current_price < 0.005
            for r in resistances
        )
        return near_ema or at_resistance

    return False


def check_trigger(closes_15m, volumes_15m, trend):
    """
    CHECK 3: TRIGGER (15min)
    RSI + Volume confirmation
    """
    if (closes_15m is None or volumes_15m is None or
            len(closes_15m) < TRIGGER_RSI_PERIOD + 5):
        return False

    rsi = calculate_rsi(closes_15m, TRIGGER_RSI_PERIOD)
    if rsi is None:
        return False

    # Volume check
    current_vol = volumes_15m[-1]
    avg_vol = np.mean(volumes_15m[-20:])
    volume_surge = current_vol > (avg_vol * TRIGGER_VOLUME_MULTIPLIER)

    if trend == "long":
        rsi_ok = TRIGGER_RSI_LONG_MIN <= rsi <= TRIGGER_RSI_LONG_MAX
        return rsi_ok and volume_surge

    elif trend == "short":
        rsi_ok = TRIGGER_RSI_SHORT_MIN <= rsi <= TRIGGER_RSI_SHORT_MAX
        return rsi_ok and volume_surge

    return False


def check_risk(state, config_max_positions, config_max_heat,
               config_daily_limit):
    """
    CHECK 4: RISK MANAGEMENT
    Can we take a new trade?
    """
    from datetime import datetime, timezone

    # Check circuit breaker
    if state.get("circuit_breaker_until"):
        cb_until = datetime.fromisoformat(state["circuit_breaker_until"])
        if datetime.now(timezone.utc) < cb_until:
            return False, "Circuit breaker active"

    # Check max positions
    open_count = len(state.get("open_positions", []))
    if open_count >= config_max_positions:
        return False, f"Max positions ({config_max_positions}) reached"

    # Check daily loss limit
    if state.get("daily_pnl", 0) < 0:
        balance = state.get("account_balance", 20)
        daily_loss_pct = abs(state["daily_pnl"]) / balance
        if daily_loss_pct >= config_daily_limit:
            return False, "Daily loss limit reached"

    # Check consecutive losses
    if state.get("consecutive_losses", 0) >= 4:
        return False, "Too many consecutive losses"

    return True, "OK"


def check_funding_rate(funding_rate, trend):
    """
    CHECK 5: FUNDING RATE EDGE
    Is funding rate favoring our direction?
    """
    if funding_rate is None:
        return True  # If we can't get funding, skip this check

    if trend == "long":
        # Negative funding = market pays us to be long
        return funding_rate <= FUNDING_RATE_THRESHOLD

    elif trend == "short":
        # Positive funding = market pays us to be short
        return funding_rate >= -FUNDING_RATE_THRESHOLD

    return True


def generate_signal(pair, closes_4h, closes_1h, highs_1h,
                    lows_1h, closes_15m, volumes_15m,
                    highs_15m, lows_15m, funding_rate, state):
    """
    MASTER SIGNAL GENERATOR
    Combines all 5 checks into a trading signal
    """

    result = {
        "pair": pair,
        "action": "none",
        "direction": "neutral",
        "confluence": 0,
        "signals": {},
        "atr": None,
        "current_price": None,
    }

    if closes_15m is None or len(closes_15m) < 2:
        return result

    result["current_price"] = closes_15m[-1]

    # CHECK 1: Trend
    trend = check_trend(closes_4h)
    result["signals"]["Trend"] = trend != "neutral"
    result["direction"] = trend

    if trend == "neutral":
        return result  # No trend = no trade

    # CHECK 2: Entry Zone
    entry_zone = check_entry_zone(
        closes_1h, highs_1h, lows_1h, trend
    )
    result["signals"]["Entry Zone"] = entry_zone

    # CHECK 3: Trigger
    trigger = check_trigger(closes_15m, volumes_15m, trend)
    result["signals"]["Trigger"] = trigger

    # CHECK 4: Risk
    from config import (MAX_POSITIONS, MAX_PORTFOLIO_HEAT,
                        DAILY_LOSS_LIMIT)
    risk_ok, risk_reason = check_risk(
        state, MAX_POSITIONS, MAX_PORTFOLIO_HEAT,
        DAILY_LOSS_LIMIT
    )
    result["signals"]["Risk OK"] = risk_ok

    # CHECK 5: Funding
    funding_ok = check_funding_rate(funding_rate, trend)
    result["signals"]["Funding"] = funding_ok

    # Count confluence
    confluence = sum(1 for v in result["signals"].values() if v)
    result["confluence"] = confluence

    # Calculate ATR for position sizing
    atr = calculate_atr(highs_15m, lows_15m, closes_15m,
                        ATR_PERIOD)
    result["atr"] = atr

    # DECISION: Need 4 out of 5 to enter
    if confluence >= 4 and risk_ok:
        result["action"] = "enter"

    return result
