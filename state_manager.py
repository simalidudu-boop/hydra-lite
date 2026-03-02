"""
HYDRA LITE — State Manager
The bot's memory between GitHub Actions runs
"""

import json
import os
from datetime import datetime, timezone


DEFAULT_STATE = {
    "account_balance": 20.0,
    "peak_balance": 20.0,
    "open_positions": [],
    "trade_history": [],
    "daily_pnl": 0.0,
    "daily_trades": 0,
    "daily_wins": 0,
    "daily_losses_count": 0,
    "weekly_pnl": 0.0,
    "consecutive_losses": 0,
    "circuit_breaker_until": None,
    "aggression_level": 1.0,
    "last_run": None,
    "last_daily_reset": None,
    "last_weekly_reset": None,
    "total_trades": 0,
    "total_wins": 0,
    "total_pnl": 0.0,
    "best_trade": 0.0,
    "worst_trade": 0.0,
    "indicator_cache": {},
    "bot_version": "1.0.0",
    "started_at": None,
}

STATE_FILE = "state.json"


def load_state():
    """Load bot state from file"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                state = json.load(f)

            # Ensure all keys exist (handles upgrades)
            for key, value in DEFAULT_STATE.items():
                if key not in state:
                    state[key] = value

            return state
    except (json.JSONDecodeError, Exception) as e:
        print(f"⚠️ State file corrupted, starting fresh: {e}")

    # First run or corrupted state
    state = DEFAULT_STATE.copy()
    state["started_at"] = datetime.now(timezone.utc).isoformat()
    return state


def save_state(state):
    """Save bot state to file"""
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def reset_daily_stats(state):
    """Reset daily counters"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if state.get("last_daily_reset") != today:
        state["daily_pnl"] = 0.0
        state["daily_trades"] = 0
        state["daily_wins"] = 0
        state["daily_losses_count"] = 0
        state["last_daily_reset"] = today

    return state


def reset_weekly_stats(state):
    """Reset weekly counters on Monday"""
    now = datetime.now(timezone.utc)
    week_key = now.strftime("%Y-W%W")

    if state.get("last_weekly_reset") != week_key:
        state["weekly_pnl"] = 0.0
        state["last_weekly_reset"] = week_key

    return state


def record_trade(state, trade_result):
    """Record a completed trade"""
    pnl = trade_result["pnl"]

    state["total_trades"] += 1
    state["daily_trades"] += 1
    state["total_pnl"] += pnl
    state["daily_pnl"] += pnl
    state["weekly_pnl"] += pnl
    state["account_balance"] += pnl

    if pnl > 0:
        state["total_wins"] += 1
        state["daily_wins"] += 1
        state["consecutive_losses"] = 0
        if pnl > state["best_trade"]:
            state["best_trade"] = pnl
    else:
        state["daily_losses_count"] += 1
        state["consecutive_losses"] += 1
        if pnl < state["worst_trade"]:
            state["worst_trade"] = pnl

    # Update peak balance
    if state["account_balance"] > state["peak_balance"]:
        state["peak_balance"] = state["account_balance"]

    # Keep last 100 trades in history
    state["trade_history"].append({
        "pair": trade_result["pair"],
        "side": trade_result["side"],
        "pnl": round(pnl, 4),
        "entry": trade_result["entry"],
        "exit": trade_result["exit"],
        "closed_at": datetime.now(timezone.utc).isoformat(),
    })
    state["trade_history"] = state["trade_history"][-100:]

    return state
