"""
Управление ботом через Telegram команды.

Поддерживаемые команды:
  /status  — текущее состояние (позиция, P&L, режим)
  /close   — закрыть текущую позицию рыночным ордером
  /pause   — остановить открытие новых сделок (пауза)
  /resume  — возобновить торговлю после паузы
  /report  — краткий отчёт за текущий день
  /help    — список команд

АРХИТЕКТУРА:
  - Polling через long-poll GET /getUpdates (не webhook, проще для Windows)
  - Фоновый asyncio.Task обновляется каждые 2 секунды
  - Команды влияют на PersistentState напрямую (через shared reference)
  - /close вызывает тот же _close_trade что и position_tracker

БЕЗОПАСНОСТЬ:
  - Принимаем команды ТОЛЬКО от TELEGRAM_CHAT_ID из .env
  - Неизвестный chat_id → игнорируем + логируем
"""
import asyncio, logging, time
import config
from state import PersistentState, RuntimeState

_last_update_id: int = 0

async def run_telegram_command_loop(ps: PersistentState, rs: RuntimeState,
                                    stop_event: asyncio.Event) -> None:
    """Фоновая задача: polling Telegram updates каждые 2 секунды."""
    if not config.TELEGRAM_COMMANDS_ENABLED:
        return
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    logging.info("Telegram commands: активированы. Команды: /status /close /pause /resume /report /help")
    while not stop_event.is_set():
        try:
            await _poll_once(ps, rs)
        except Exception as e:
            logging.warning(f"telegram_commands poll: {e}")
        await asyncio.sleep(2.0)

async def _poll_once(ps: PersistentState, rs: RuntimeState) -> None:
    global _last_update_id
    from data.rest_client import get_session
    sess  = await get_session()
    url   = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 1, "allowed_updates": '["message"]'}
    if _last_update_id > 0:
        params["offset"] = _last_update_id + 1
    async with sess.get(url, params=params, timeout=None) as r:
        if r.status != 200: return
        data = await r.json()
    for upd in data.get("result", []):
        _last_update_id = int(upd["update_id"])
        msg = upd.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != str(config.TELEGRAM_CHAT_ID):
            logging.warning(f"telegram_commands: неизвестный chat_id={chat_id}, игнорируем")
            continue
        text = msg.get("text", "").strip().lower()
        await _handle_command(text, ps, rs)

async def _handle_command(cmd: str, ps: PersistentState, rs: RuntimeState) -> None:
    from monitor.notifier import _send
    if cmd == "/status":
        pos = ps.position
        if pos:
            mark = rs.micro.mark_price
            unreal = ((mark - pos.avg_fill_price) * pos.qty_remaining
                      * (1 if pos.direction == "LONG" else -1))
            await _send(
                f"📊 <b>Статус</b>\n"
                f"Позиция: <b>{pos.direction}</b> @ {pos.avg_fill_price:.2f}\n"
                f"Кол-во: {pos.qty_remaining:.4f} BTC\n"
                f"Стоп: {pos.stop_price:.2f}"
                + (" (BE)" if pos.tp1_filled else "") + "\n"
                f"Нереал P&L: {unreal:+.2f}$\n"
                f"Реал P&L: {pos.realized_pnl_usd:+.2f}$"
            )
        else:
            await _send(
                f"📊 <b>Статус</b>\n"
                f"Позиции нет\n"
                f"Дневной P&L: {ps.daily_pnl_usd:+.2f}$\n"
                f"Баланс: {ps.available_balance:.2f}$\n"
                f"Режим рынка: {rs.context.regime}"
            )
    elif cmd == "/close":
        if not ps.position:
            await _send("ℹ️ Нет открытой позиции для закрытия")
            return
        await _send("⚡ Закрываю позицию рыночным ордером...")
        try:
            from execution.position_tracker import _close_trade
            await _close_trade("MANUAL_CLOSE", rs.micro.mark_price,
                               ps.position.qty_remaining, ps, rs)
            await _send("✅ Позиция закрыта вручную")
        except Exception as e:
            await _send(f"❌ Ошибка закрытия: {e}")
    elif cmd == "/pause":
        ps.pause_until = time.time() + 4 * 3600  # пауза 4 часа
        import state as _state; _state.save(ps)
        await _send("⏸ <b>Пауза 4 часа</b>. Новые сделки не будут открываться.\n/resume для отмены")
    elif cmd == "/resume":
        ps.pause_until = 0.0
        import state as _state; _state.save(ps)
        await _send("▶️ <b>Торговля возобновлена</b>")
    elif cmd == "/report":
        await _send(
            f"📈 <b>Отчёт за сегодня</b>\n"
            f"Сделок: {ps.trades_today} (W:{ps.wins_today} / L:{ps.losses_today})\n"
            f"P&L: {ps.daily_pnl_usd:+.2f}$ ({ps.daily_pnl_pct*100:+.2f}%)\n"
            f"Баланс: {ps.available_balance:.2f}$\n"
            f"Просадка: {ps.equity_drawdown_pct*100:.2f}%\n"
            f"Fear&Greed: {rs.sentiment.value if rs.sentiment.available else 'N/A'}"
        )
    elif cmd == "/help":
        await _send(
            "🤖 <b>APEX BOT команды</b>\n\n"
            "/status — текущее состояние\n"
            "/close — закрыть позицию\n"
            "/pause — пауза 4 часа\n"
            "/resume — возобновить\n"
            "/report — дневной отчёт\n"
            "/help — эта справка"
        )
    else:
        await _send(f"❓ Неизвестная команда: {cmd}\nНапиши /help")

