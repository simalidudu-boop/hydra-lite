
"""
╔══════════════════════════════════════════════════╗
║                                                  ║
║            HYDRA LITE v1.0                       ║
║            Zimbabwe Edition                      ║
║                                                  ║
║            $20 → Freedom                         ║
║                                                  ║
║            Built for GitHub Actions              ║
║            Runs every 15 minutes                 ║
║            Zero cost infrastructure              ║
║                                                  ║
╚══════════════════════════════════════════════════╝
"""

import ccxt
import time
import traceback
from datetime import datetime, timezone, timedelta

from config import (
    BYBIT_API_KEY, BYBIT_API_SECRET, PAIRS,
    DEFAULT_LEVERAGE, MAX_POSITIONS,
    STOP_LOSS_ATR_MULTIPLIER, ATR_PERIOD,
    TP1_CLOSE_PERCENT, TP2_CLOSE_PERCENT,
)
from state_manager import (
    load_state, save_state, reset_daily_stats,
    reset_weekly_stats, record_trade,
)
from signals import generate_signal, calculate_atr
from risk_manager import (
    calculate_position_size, calculate_levels,
    check_drawdown_adjustment, check_circuit_breakers,
    check_correlation_guard,
)
from discord_alerts import (
    alert_trade_opened, alert_tp_hit, alert_sl_hit,
    alert_breakeven_moved, alert_circuit_breaker,
    alert_daily_summary, alert_bot_started,
    alert_heartbeat, send_discord,
)


def create_exchange():
    """Initialize Bybit connection"""
    exchange = ccxt.bybit({
        "apiKey": BYBIT_API_KEY,
        "secret": BYBIT_API_SECRET,
        "sandbox": False,
        "options": {
            "defaultType": "swap",
            "adjustForTimeDifference": True,
        },
    })
    return exchange


def fetch_candles(exchange, pair, timeframe, limit=100):
    """Fetch OHLCV candle data"""
    try:
        candles = exchange.fetch_ohlcv(
            pair, timeframe, limit=limit
        )
        if not candles or len(candles) < 10:
            return None, None, None, None, None

        opens = [c[1] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        closes = [c[4] for c in candles]
        volumes = [c[5] for c in candles]

        return opens, highs, lows, closes, volumes
    except Exception as e:
        print(f"⚠️ Error fetching {pair} {timeframe}: {e}")
        return None, None, None, None, None


def get_funding_rate(exchange, pair):
    """Get current funding rate"""
    try:
        ticker = exchange.fetch_ticker(pair)
        info = ticker.get("info", {})

        # Bybit funding rate location
        funding = info.get("fundingRate")
        if funding:
            return float(funding)
        return None
    except Exception:
        return None


def get_account_balance(exchange):
    """Get USDT balance from Bybit"""
    try:
        balance = exchange.fetch_balance({"type": "swap"})
        usdt = balance.get("USDT", {})
        total = usdt.get("total", 0)
        free = usdt.get("free", 0)
        return float(total), float(free)
    except Exception as e:
        print(f"⚠️ Error fetching balance: {e}")
        return None, None


def get_open_positions(exchange):
    """Get all open positions from Bybit"""
    try:
        positions = exchange.fetch_positions()
        active = []
        for pos in positions:
            if pos and float(pos.get("contracts", 0)) > 0:
                active.append({
                    "pair": pos["symbol"],
                    "side": pos["side"],
                    "size": float(pos["contracts"]),
                    "entry": float(pos["entryPrice"]),
                    "unrealized_pnl": float(
                        pos.get("unrealizedPnl", 0)
                    ),
                    "leverage": float(
                        pos.get("leverage", DEFAULT_LEVERAGE)
                    ),
                })
        return active
    except Exception as e:
        print(f"⚠️ Error fetching positions: {e}")
        return []


def set_leverage(exchange, pair, leverage):
    """Set leverage for a pair"""
    try:
        exchange.set_leverage(leverage, pair)
    except Exception:
        pass  # Leverage might already be set


def place_entry_order(exchange, pair, side, size,
                      leverage, sl, tp1):
    """
    Place entry order with server-side stop loss.
    The stop loss lives on Bybit's servers,
    protecting you even if GitHub Actions stops.
    """
    try:
        # Set leverage first
        set_leverage(exchange, pair, leverage)

        # Place market entry order
        order_side = "buy" if side == "long" else "sell"
        entry_order = exchange.create_market_order(
            pair,
            order_side,
            size,
            params={
                "stopLoss": {
                    "triggerPrice": str(sl),
                    "type": "market",
                },
                "takeProfit": {
                    "triggerPrice": str(tp1),
                    "type": "market",
                },
            }
        )

        return entry_order
    except Exception as e:
        print(f"❌ Order failed for {pair}: {e}")
        return None


def close_partial_position(exchange, pair, side,
                           size_to_close):
    """Close a portion of an open position"""
    try:
        close_side = "sell" if side == "long" else "buy"
        order = exchange.create_market_order(
            pair,
            close_side,
            size_to_close,
            params={"reduceOnly": True}
        )
        return order
    except Exception as e:
        print(f"⚠️ Partial close failed for {pair}: {e}")
        return None


def update_stop_loss(exchange, pair, side, new_sl):
    """Move stop loss (e.g., to breakeven)"""
    try:
        # Cancel existing SL and place new one
        exchange.set_stop_loss(
            pair,
            new_sl,
            params={"type": "market"}
        )
        return True
    except Exception:
        # Alternative method for Bybit
        try:
            sl_side = "sell" if side == "long" else "buy"
            exchange.create_order(
                pair,
                "market",
                sl_side,
                0,  # Size 0 = close position
                None,
                params={
                    "triggerPrice": str(new_sl),
                    "reduceOnly": True,
                    "triggerDirection": (
                        2 if side == "long" else 1
                    ),
                }
            )
            return True
        except Exception as e:
            print(f"⚠️ SL update failed for {pair}: {e}")
            return False


def manage_open_positions(exchange, state):
    """
    Check and manage all open positions.
    Handle TP hits, SL moves, etc.
    """
    if not state.get("open_positions"):
        return state

    positions_to_remove = []

    for i, pos in enumerate(state["open_positions"]):
        pair = pos["pair"]

        try:
            # Get current price
            ticker = exchange.fetch_ticker(pair)
            current_price = float(ticker["last"])

            side = pos["side"]
            entry = pos["entry"]
            tp1 = pos.get("tp1")
            tp2 = pos.get("tp2")
            tp3 = pos.get("tp3")
            sl = pos.get("sl")
            original_size = pos.get("original_size", pos["size"])

            # Calculate current P&L
            if side == "long":
                pnl_pct = (current_price - entry) / entry
            else:
                pnl_pct = (entry - current_price) / entry

            pnl_pct *= pos.get("leverage", DEFAULT_LEVERAGE)

            # ══════════════════════════════════════
            # CHECK TP1
            # ══════════════════════════════════════
            if (not pos.get("tp1_hit") and tp1 and
                ((side == "long" and current_price >= tp1) or
                 (side == "short" and current_price <= tp1))):

                close_size = round(
                    original_size * TP1_CLOSE_PERCENT, 6
                )
                if close_size > 0:
                    order = close_partial_position(
                        exchange, pair, side, close_size
                    )
                    if order:
                        profit = (abs(tp1 - entry) / entry *
                                 close_size * entry *
                                 pos.get("leverage",
                                        DEFAULT_LEVERAGE))
                        pos["tp1_hit"] = True
                        pos["size"] = round(
                            pos["size"] - close_size, 6
                        )

                        state["account_balance"] += profit
                        alert_tp_hit(
                            pair, 1, TP1_CLOSE_PERCENT,
                            profit,
                            1 - TP1_CLOSE_PERCENT,
                            state["account_balance"]
                        )

                        # Move SL to breakeven
                        if update_stop_loss(
                            exchange, pair, side, entry
                        ):
                            pos["sl"] = entry
                            alert_breakeven_moved(pair)

            # ══════════════════════════════════════
            # CHECK TP2
            # ══════════════════════════════════════
            if (pos.get("tp1_hit") and
                not pos.get("tp2_hit") and tp2 and
                ((side == "long" and current_price >= tp2) or
                 (side == "short" and current_price <= tp2))):

                close_size = round(
                    original_size * TP2_CLOSE_PERCENT, 6
                )
                close_size = min(close_size, pos["size"])
                if close_size > 0:
                    order = close_partial_position(
                        exchange, pair, side, close_size
                    )
                    if order:
                        profit = (abs(tp2 - entry) / entry *
                                 close_size * entry *
                                 pos.get("leverage",
                                        DEFAULT_LEVERAGE))
                        pos["tp2_hit"] = True
                        pos["size"] = round(
                            pos["size"] - close_size, 6
                        )

                        state["account_balance"] += profit
                        alert_tp_hit(
                            pair, 2, TP2_CLOSE_PERCENT,
                            profit,
                            TP3_CLOSE_PERCENT
                            if pos["size"] > 0 else 0,
                            state["account_balance"]
                        )

            # ══════════════════════════════════════
            # CHECK TP3
            # ══════════════════════════════════════
            if (pos.get("tp2_hit") and tp3 and
                ((side == "long" and current_price >= tp3) or
                 (side == "short" and current_price <= tp3))):

                close_size = pos["size"]
                if close_size > 0:
                    order = close_partial_position(
                        exchange, pair, side, close_size
                    )
                    if order:
                        profit = (abs(tp3 - entry) / entry *
                                 close_size * entry *
                                 pos.get("leverage",
                                        DEFAULT_LEVERAGE))

                        state = record_trade(state, {
                            "pair": pair,
                            "side": side,
                            "pnl": profit,
                            "entry": entry,
                            "exit": current_price,
                        })

                        alert_tp_hit(
                            pair, 3, 1.0, profit,
                            0, state["account_balance"]
                        )
                        positions_to_remove.append(i)

            # ══════════════════════════════════════
            # CHECK IF SL WAS HIT (by Bybit server)
            # ══════════════════════════════════════
            if ((side == "long" and current_price <= sl) or
                (side == "short" and current_price >= sl)):

                # Position likely already closed by
                # server-side SL
                loss = -(abs(sl - entry) / entry *
                        pos["size"] * entry *
                        pos.get("leverage", DEFAULT_LEVERAGE))

                state = record_trade(state, {
                    "pair": pair,
                    "side": side,
                    "pnl": loss,
                    "entry": entry,
                    "exit": sl,
                })

                alert_sl_hit(
                    pair, loss, state["account_balance"]
                )
                positions_to_remove.append(i)

            # ══════════════════════════════════════
            # CHECK IF POSITION STILL EXISTS ON EXCHANGE
            # ══════════════════════════════════════
            if pos["size"] <= 0:
                positions_to_remove.append(i)

        except Exception as e:
            print(f"⚠️ Error managing {pair}: {e}")
            continue

    # Remove closed positions
    for i in sorted(set(positions_to_remove), reverse=True):
        if i < len(state["open_positions"]):
            state["open_positions"].pop(i)

    return state


def scan_for_entries(exchange, state):
    """
    Scan all pairs for entry signals.
    The heart of the bot.
    """
    can_trade, reason = check_circuit_breakers(state)
    if not can_trade:
        print(f"⏸️ Trading paused: {reason}")
        return state

    # Update aggression based on drawdown
    state["aggression_level"] = check_drawdown_adjustment(state)

    if state["aggression_level"] == 0:
        alert_circuit_breaker(
            "Drawdown threshold exceeded",
            48,
            state["account_balance"]
        )
        return state

    open_count = len(state.get("open_positions", []))
    if open_count >= MAX_POSITIONS:
        print(f"📊 Max positions ({MAX_POSITIONS}) reached. "
              f"Managing existing trades.")
        return state

    for pair in PAIRS:
        # Skip if already have position in this pair
        if any(p["pair"] == pair
               for p in state.get("open_positions", [])):
            continue

        try:
            print(f"🔍 Scanning {pair}...")

            # Fetch data for all timeframes
            _, h_4h, l_4h, c_4h, _ = fetch_candles(
                exchange, pair, "4h", 50
            )
            _, h_1h, l_1h, c_1h, _ = fetch_candles(
                exchange, pair, "1h", 60
            )
            _, h_15m, l_15m, c_15m, v_15m = fetch_candles(
                exchange, pair, "15m", 50
            )

            # Get funding rate
            funding = get_funding_rate(exchange, pair)

            # Generate signal
            signal = generate_signal(
                pair, c_4h, c_1h, h_1h, l_1h,
                c_15m, v_15m, h_15m, l_15m,
                funding, state
            )

            if signal["action"] == "enter":
                print(f"🎯 SIGNAL DETECTED: {pair} "
                      f"{signal['direction']} "
                      f"(confluence: {signal['confluence']}/5)")

                # Correlation check
                corr_ok, corr_reason = check_correlation_guard(
                    pair,
                    signal["direction"],
                    state.get("open_positions", [])
                )

                if not corr_ok:
                    print(f"⚠️ Skipping {pair}: {corr_reason}")
                    continue

                # Calculate position size
                pos_info = calculate_position_size(
                    state["account_balance"],
                    signal["atr"],
                    signal["current_price"],
                    pair,
                    state
                )

                if pos_info is None:
                    print(f"⚠️ {pair}: Position too small "
                          f"or can't afford")
                    continue

                # Calculate TP/SL levels
                levels = calculate_levels(
                    signal["current_price"],
                    signal["atr"],
                    signal["direction"]
                )

                # PLACE THE TRADE
                order = place_entry_order(
                    exchange,
                    pair,
                    signal["direction"],
                    pos_info["size"],
                    pos_info["leverage"],
                    levels["sl"],
                    levels["tp1"],
                )

                if order:
                    # Record position in state
                    position = {
                        "pair": pair,
                        "side": signal["direction"],
                        "entry": signal["current_price"],
                        "size": pos_info["size"],
                        "original_size": pos_info["size"],
                        "leverage": pos_info["leverage"],
                        "sl": levels["sl"],
                        "tp1": levels["tp1"],
                        "tp2": levels["tp2"],
                        "tp3": levels["tp3"],
                        "tp1_hit": False,
                        "tp2_hit": False,
                        "risk_dollars": pos_info[
                            "risk_dollars"
                        ],
                        "opened_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    }
                    state["open_positions"].append(position)

                    # Send Discord alert
                    alert_trade_opened(
                        pair=pair,
                        side=signal["direction"],
                        entry=signal["current_price"],
                        size=pos_info["size"],
                        leverage=pos_info["leverage"],
                        tp1=levels["tp1"],
                        tp2=levels["tp2"],
                        tp3=levels["tp3"],
                        sl=levels["sl"],
                        risk_pct=pos_info[
                            "risk_percent"
                        ] / 100,
                        risk_usd=pos_info["risk_dollars"],
                        confluence=signal["confluence"],
                        signals=signal["signals"],
                        balance=state["account_balance"],
                    )

                    print(f"✅ TRADE OPENED: {pair} "
                          f"{signal['direction']} "
                          f"@ {signal['current_price']}")

                    open_count += 1
                    if open_count >= MAX_POSITIONS:
                        break

            else:
                print(f"   {pair}: No signal "
                      f"(confluence: "
                      f"{signal['confluence']}/5)")

            # Small delay to avoid rate limits
            time.sleep(0.5)

        except Exception as e:
            print(f"⚠️ Error scanning {pair}: {e}")
            continue

    return state


def sync_with_exchange(exchange, state):
    """
    Sync bot state with actual exchange state.
    Handles cases where Bybit closed positions
    while bot was sleeping.
    """
    try:
        live_positions = get_open_positions(exchange)
        live_pairs = {p["pair"] for p in live_positions}

        # Check for positions closed by exchange
        # (SL/TP hit while bot was offline)
        positions_to_remove = []
        for i, pos in enumerate(
            state.get("open_positions", [])
        ):
            if pos["pair"] not in live_pairs:
                # Position was closed by exchange
                print(f"📋 {pos['pair']} was closed "
                      f"by exchange (SL/TP hit offline)")

                # We don't know exact exit price,
                # estimate from SL
                estimated_pnl = -pos.get(
                    "risk_dollars",
                    state["account_balance"] * 0.015
                )
                state = record_trade(state, {
                    "pair": pos["pair"],
                    "side": pos["side"],
                    "pnl": estimated_pnl,
                    "entry": pos["entry"],
                    "exit": pos["sl"],
                })
                positions_to_remove.append(i)

        for i in sorted(positions_to_remove, reverse=True):
            state["open_positions"].pop(i)

        # Update actual balance from exchange
        total, free = get_account_balance(exchange)
        if total is not None:
            state["account_balance"] = total
            if total > state["peak_balance"]:
                state["peak_balance"] = total

    except Exception as e:
        print(f"⚠️ Sync error: {e}")

    return state


def should_send_daily_summary(state):
    """Check if it's time for daily summary (every 24h)"""
    now = datetime.now(timezone.utc)

    # Send at midnight UTC
    if now.hour == 0 and now.minute < 20:
        last_summary = state.get("last_daily_summary")
        if last_summary:
            last = datetime.fromisoformat(last_summary)
            if (now - last).total_seconds() < 72000:
                return False
        state["last_daily_summary"] = now.isoformat()
        return True
    return False


def should_send_heartbeat(state):
    """Send heartbeat every 4 hours"""
    now = datetime.now(timezone.utc)
    if now.hour % 4 == 0 and now.minute < 20:
        last_hb = state.get("last_heartbeat")
        if last_hb:
            last = datetime.fromisoformat(last_hb)
            if (now - last).total_seconds() < 13000:
                return False
        state["last_heartbeat"] = now.isoformat()
        return True
    return False


# ═══════════════════════════════════════════════════
# MAIN EXECUTION — This runs every 15 minutes
# ═══════════════════════════════════════════════════

def main():
    """
    Main bot loop.
    Called every 15 minutes by GitHub Actions.
    """
    print("=" * 50)
    print("🐍 HYDRA LITE — Waking up...")
    print(f"⏰ {datetime.now(timezone.utc).isoformat()}")
    print("=" * 50)

    # Load state (bot's memory)
    state = load_state()

    # Reset daily/weekly counters if needed
    state = reset_daily_stats(state)
    state = reset_weekly_stats(state)

    # Check if this is first run
    if state.get("started_at") is None:
        state["started_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        alert_bot_started(state["account_balance"])

    # Initialize exchange
    try:
        exchange = create_exchange()
        exchange.load_markets()
        print("✅ Connected to Bybit")
    except Exception as e:
        print(f"❌ Failed to connect to Bybit: {e}")
        send_discord(
            f"```❌ HYDRA ERROR\n"
            f"Cannot connect to Bybit: {e}\n"
            f"Will retry next run.```"
        )
        save_state(state)
        return

    # Sync state with exchange
    state = sync_with_exchange(exchange, state)
    print(f"💰 Balance: ${state['account_balance']:.2f}")
    print(f"📊 Open positions: "
          f"{len(state.get('open_positions', []))}")

    # Manage existing positions
    state = manage_open_positions(exchange, state)

    # Scan for new entries
    state = scan_for_entries(exchange, state)

    # Send daily summary if it's time
    if should_send_daily_summary(state):
        alert_daily_summary(state)

    # Send heartbeat
    if should_send_heartbeat(state):
        alert_heartbeat(
            state["account_balance"],
            len(state.get("open_positions", []))
        )

    # Save state (bot's memory for next run)
    save_state(state)

    print("=" * 50)
    print(f"💰 Balance: ${state['account_balance']:.2f}")
    print(f"📊 Daily P&L: "
          f"${state.get('daily_pnl', 0):+.2f}")
    print(f"📈 Total P&L: "
          f"${state.get('total_pnl', 0):+.2f}")
    print("🐍 HYDRA LITE — Going back to sleep...")
    print("=" * 50)


if __name__ == "__main__":
    main()
