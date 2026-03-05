import logging
import config

async def _send(text: str) -> None:
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID: return
    try:
        from data.rest_client import get_session
        sess = await get_session()
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
        await sess.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "text": text,
                                   "parse_mode": "HTML"})
    except Exception as e:
        logging.warning(f"Telegram: {e}")

async def send_tp_hit(tp_num: int, price: float, pos) -> None:
    emoji = "🟢" if pos.direction == "LONG" else "🔴"
    await _send(f"{emoji} <b>TP{tp_num} достигнут</b>\n"
                f"Цена: {price:.2f}\nПрибыль: {pos.realized_pnl_usd:+.2f}$\n"
                f"Стоп перенесён на безубыток: {pos.avg_fill_price:.2f}")

async def send_trade_closed(reason: str, price: float, pnl, total_net: float, ps) -> None:
    emoji = "✅" if total_net > 0 else "❌"
    await _send(f"{emoji} <b>Сделка закрыта [{reason}]</b>\n"
                f"Цена: {price:.2f}\nNet P&L: {total_net:+.2f}$\n"
                f"Баланс: {ps.available_balance:.2f}$")

async def send_pause_notification(ps) -> None:
    await _send(f"⏸ <b>Пауза 30 минут</b>\n"
                f"{config.MAX_CONSECUTIVE_LOSSES} убытков подряд.\n"
                f"Баланс: {ps.available_balance:.2f}$")

async def send_liquidation_alert(liq_price: float, ps) -> None:
    await _send(f"💥 <b>ЛИКВИДАЦИЯ @ {liq_price:.2f}</b>\n"
                f"Баланс: {ps.available_balance:.2f}$\n"
                f"⚠️ Бот остановлен — требуется ручная проверка!")

async def send_startup(mode: str, balance: float, fear_greed_val: int) -> None:
    emoji_map = {"backtest": "🔬", "paper": "📋", "live": "🚀"}
    emoji = emoji_map.get(mode, "🤖")
    fg_str = str(fear_greed_val) if fear_greed_val >= 0 else "недоступен"
    await _send(f"{emoji} <b>APEX BOT запущен [{mode.upper()}]</b>\n"
                f"Баланс: {balance:.2f}$\nFear&Greed: {fg_str}")

