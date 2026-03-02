
"""
HYDRA LITE — Risk Manager
The guardian that keeps you alive
"""

from config import (
    RISK_PER_TRADE, DEFAULT_LEVERAGE, MAX_LEVERAGE,
    STOP_LOSS_ATR_MULTIPLIER, TAKE_PROFIT_1_ATR_MULTIPLIER,
    TAKE_PROFIT_2_ATR_MULTIPLIER, TAKE_PROFIT_3_ATR_MULTIPLIER,
    TP1_CLOSE_PERCENT, TP2_CLOSE_PERCENT, TP3_CLOSE_PERCENT,
    DRAWDOWN_REDUCE_THRESHOLD, DAILY_LOSS_LIMIT,
    DAILY_LOSS_PAUSE_HOURS, DRAWDOWN_PAUSE_THRESHOLD,
    MAX_CONSECUTIVE_LOSSES, MIN_ORDER_SIZES,
)
from datetime import datetime, timedelta, timezone


def calculate_position_size(balance, atr, current_price,
                           pair, state):
    """
    Calculate position size based on:
    - Account balance
    - ATR (volatility)
    - Risk per trade (1.5%)
    - Aggression level (adjusts dynamically)
    """

    aggression = state.get("aggression_level", 1.0)
    adjusted_risk = RISK_PER_TRADE * aggression

    # Dollar risk per trade
    risk_dollars = balance * adjusted_risk

    # Stop loss distance (in price)
    sl_distance = atr * STOP_LOSS_ATR_MULTIPLIER

    if sl_distance <= 0:
        return None

    # Position size (in base currency units)
    # risk_dollars = position_size * sl_distance
    position_size = risk_dollars / sl_distance

    # Apply leverage
    leverage = min(DEFAULT_LEVERAGE, MAX_LEVERAGE)
    notional_value = position_size * current_price
    required_margin = notional_value / leverage

    # Check if we can afford this position
    if required_margin > balance * 0.3:
        # Cap at 30% of balance as margin
        required_margin = balance * 0.3
        notional_value = required_margin * leverage
        position_size = notional_value / current_price

    # Check minimum order size
    min_size = MIN_ORDER_SIZES.get(pair, 0.001)
    if position_size < min_size:
        # Check if we can afford minimum size
        min_margin = (min_size * current_price) / leverage
        if min_margin > balance * 0.3:
            return None  # Can't afford minimum order
        position_size = min_size

    return {
        "size": round(position_size, 6),
        "leverage": leverage,
        "margin_required": round(required_margin, 4),
        "risk_dollars": round(risk_dollars, 4),
        "risk_percent": round(adjusted_risk * 100, 2),
    }


def calculate_levels(current_price, atr, direction):
    """
    Calculate SL and TP levels based on ATR
    """
    sl_distance = atr * STOP_LOSS_ATR_MULTIPLIER
    tp1_distance = atr * TAKE_PROFIT_1_ATR_MULTIPLIER
    tp2_distance = atr * TAKE_PROFIT_2_ATR_MULTIPLIER
    tp3_distance = atr * TAKE_PROFIT_3_ATR_MULTIPLIER

    if direction == "long":
        sl = current_price - sl_distance
        tp1 = current_price + tp1_distance
        tp2 = current_price + tp2_distance
        tp3 = current_price + tp3_distance
    else:  # short
        sl = current_price + sl_distance
        tp1 = current_price - tp1_distance
        tp2 = current_price - tp2_distance
        tp3 = current_price - tp3_distance

    return {
        "sl": round(sl, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "tp3": round(tp3, 2),
        "sl_distance": round(sl_distance, 2),
    }


def check_drawdown_adjustment(state):
    """
    Adjust aggression based on drawdown
    Returns updated aggression level
    """
    balance = state.get("account_balance", 20)
    peak = state.get("peak_balance", 20)

    if peak <= 0:
        return 1.0

    drawdown = (peak - balance) / peak

    if drawdown >= DRAWDOWN_PAUSE_THRESHOLD:
        # 12%+ drawdown → pause trading
        pause_until = (datetime.now(timezone.utc) +
                      timedelta(hours=48))
        state["circuit_breaker_until"] = pause_until.isoformat()
        return 0.0

    elif drawdown >= DRAWDOWN_REDUCE_THRESHOLD:
        # 8%+ drawdown → reduce aggression by 40%
        return 0.6

    elif drawdown >= 0.05:
        # 5%+ drawdown → reduce aggression by 20%
        return 0.8

    elif drawdown <= 0.02 and balance > peak * 0.98:
        # Near peak → full aggression
        return 1.0

    return state.get("aggression_level", 1.0)


def check_circuit_breakers(state):
    """
    Check all circuit breaker conditions
    Returns: (should_trade, reason)
    """
    now = datetime.now(timezone.utc)

    # Check existing circuit breaker
    if state.get("circuit_breaker_until"):
        cb_until = datetime.fromisoformat(
            state["circuit_breaker_until"]
        )
        if now < cb_until:
            remaining = (cb_until - now).total_seconds() / 3600
            return False, f"Paused for {remaining:.1f} more hours"
        else:
            state["circuit_breaker_until"] = None

    balance = state.get("account_balance", 20)

    # Daily loss circuit breaker
    if state.get("daily_pnl", 0) < 0:
        daily_loss_pct = abs(state["daily_pnl"]) / balance
        if daily_loss_pct >= DAILY_LOSS_LIMIT:
            pause_until = now + timedelta(
                hours=DAILY_LOSS_PAUSE_HOURS
            )
            state["circuit_breaker_until"] = (
                pause_until.isoformat()
            )
            return False, f"Daily loss {daily_loss_pct:.1%} exceeded {DAILY_LOSS_LIMIT:.1%}"

    # Consecutive losses circuit breaker
    if state.get("consecutive_losses", 0) >= MAX_CONSECUTIVE_LOSSES:
        pause_until = now + timedelta(hours=6)
        state["circuit_breaker_until"] = pause_until.isoformat()
        state["consecutive_losses"] = 0
        return False, f"{MAX_CONSECUTIVE_LOSSES} consecutive losses"

    return True, "OK"


def check_correlation_guard(pair, direction, open_positions):
    """
    Prevent over-exposure to correlated moves
    BTC and ETH move together ~80% of the time
    """
    correlated_pairs = {
        "BTC/USDT:USDT": ["ETH/USDT:USDT"],
        "ETH/USDT:USDT": ["BTC/USDT:USDT"],
        "SOL/USDT:USDT": ["ETH/USDT:USDT"],
        "AVAX/USDT:USDT": ["SOL/USDT:USDT"],
        "LINK/USDT:USDT": [],
    }

    related = correlated_pairs.get(pair, [])

    for pos in open_positions:
        if pos["pair"] in related and pos["side"] == direction:
            return False, (f"Correlated with open "
                         f"{pos['pair']} {pos['side']}")

    return True, "OK"
