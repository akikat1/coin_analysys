"""
Telegram command loop via long polling.
"""

from __future__ import annotations

import asyncio
import logging
import time

import config
from state import PersistentState, RuntimeState

_last_update_id: int = 0


async def run_telegram_command_loop(
    ps: PersistentState,
    rs: RuntimeState,
    stop_event: asyncio.Event,
) -> None:
    if not config.TELEGRAM_COMMANDS_ENABLED:
        return
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        return

    logging.info(
        "Telegram commands enabled: /status /close /pause /resume /report /reset /help"
    )

    while not stop_event.is_set():
        try:
            await _poll_once(ps, rs)
        except Exception as e:
            logging.warning("telegram_commands poll: %s: %s", type(e).__name__, e)
        await asyncio.sleep(2.0)


async def _poll_once(ps: PersistentState, rs: RuntimeState) -> None:
    global _last_update_id

    from data.rest_client import get_session

    sess = await get_session()
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 1, "allowed_updates": '["message"]'}
    if _last_update_id > 0:
        params["offset"] = _last_update_id + 1

    async with sess.get(url, params=params, timeout=None) as r:
        if r.status != 200:
            return
        data = await r.json(content_type=None)

    for upd in data.get("result", []):
        _last_update_id = int(upd["update_id"])
        msg = upd.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != str(config.TELEGRAM_CHAT_ID):
            logging.warning("telegram_commands: unknown chat_id=%s", chat_id)
            continue

        text = msg.get("text", "").strip().lower()
        await _handle_command(text, ps, rs)


async def _handle_command(cmd: str, ps: PersistentState, rs: RuntimeState) -> None:
    from monitor.notifier import _send

    if cmd == "/status":
        pos = ps.position
        if pos:
            mark = rs.micro.mark_price
            unreal = (mark - pos.avg_fill_price) * pos.qty_remaining * (1 if pos.direction == "LONG" else -1)
            await _send(
                "📊 <b>Status</b>\n"
                f"Position: <b>{pos.direction}</b> @ {pos.avg_fill_price:.2f}\n"
                f"Qty: {pos.qty_remaining:.4f} BTC\n"
                f"Stop: {pos.stop_price:.2f}" + (" (BE)" if pos.tp1_filled else "") + "\n"
                f"Unreal P&L: {unreal:+.2f}$\n"
                f"Real P&L: {pos.realized_pnl_usd:+.2f}$"
            )
        else:
            await _send(
                "📊 <b>Status</b>\n"
                "No open position\n"
                f"Daily P&L: {ps.daily_pnl_usd:+.2f}$\n"
                f"Balance: {ps.available_balance:.2f}$\n"
                f"Market regime: {rs.context.regime}"
            )
        return

    if cmd == "/close":
        if not ps.position:
            await _send("ℹ️ No open position to close")
            return
        await _send("⚡ Closing position via market order...")
        try:
            from execution.position_tracker import _close_trade

            await _close_trade("MANUAL_CLOSE", rs.micro.mark_price, ps.position.qty_remaining, ps, rs)
            await _send("✅ Position closed")
        except Exception as e:
            await _send(f"❌ Close error: {type(e).__name__}: {e}")
        return

    if cmd == "/pause":
        ps.pause_until = time.time() + 4 * 3600
        import state as _state

        _state.save(ps)
        await _send("⏸ Trading paused for 4 hours. Use /resume to continue")
        return

    if cmd == "/resume":
        ps.pause_until = 0.0
        import state as _state

        _state.save(ps)
        await _send("▶️ Trading resumed")
        return

    if cmd == "/report":
        await _send(
            "📈 <b>Daily report</b>\n"
            f"Trades: {ps.trades_today} (W:{ps.wins_today} / L:{ps.losses_today})\n"
            f"P&L: {ps.daily_pnl_usd:+.2f}$ ({ps.daily_pnl_pct * 100:+.2f}%)\n"
            f"Balance: {ps.available_balance:.2f}$\n"
            f"Drawdown: {ps.equity_drawdown_pct * 100:.2f}%\n"
            f"Fear&Greed: {rs.sentiment.value if rs.sentiment.available else 'N/A'}"
        )
        return

    if cmd == "/reset":
        try:
            from data.rest_client import _request

            live = await _request(
                "GET",
                "/fapi/v2/positionRisk",
                {"symbol": config.SYMBOL},
                signed=True,
                weight=5,
            )
            live_qty = 0.0
            if isinstance(live, list):
                row = next((x for x in live if x.get("symbol") == config.SYMBOL), None)
                if row:
                    live_qty = abs(float(row.get("positionAmt", 0) or 0))

            if live_qty > 0:
                await _send(
                    f"⚠️ Exchange still has open position ({live_qty:.6f} BTC). Close it first with /close"
                )
                return

            ps.position = None
            import state as _state

            _state.save(ps)
            await _send("✅ state reset: position=None")
        except Exception as e:
            await _send(f"❌ /reset error: {type(e).__name__}: {e}")
        return

    if cmd == "/help":
        await _send(
            "🤖 <b>APEX BOT commands</b>\n\n"
            "/status - current status\n"
            "/close - close current position\n"
            "/pause - pause entries for 4h\n"
            "/resume - resume trading\n"
            "/report - daily report\n"
            "/reset - reset local state (only if exchange position is zero)\n"
            "/help - show commands"
        )
        return

    await _send(f"❓ Unknown command: {cmd}\nUse /help")