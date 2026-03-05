"""
APEX Scalping Bot v12 — точка входа.
Режимы: backtest | walkforward | paper | live
Платформы: Windows (основная), Linux, macOS (Python 3.11+)

ВАЖНО: запускать из папки apex_bot\
  cd apex_bot
  python main.py --mode paper
"""
import argparse
import asyncio
import os
import signal
import sys
import time
from datetime import datetime, timezone
from dotenv import dotenv_values

# Для Windows-консоли с cp1251: принудительно UTF-8, чтобы логгер не падал на emoji/символах.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─── Windows asyncio fix (ОБЯЗАТЕЛЬНО до любых asyncio вызовов) ──────────────
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ─── Создать папки ДО настройки логгера (иначе FileNotFoundError) ────────────
os.makedirs("logs", exist_ok=True)
os.makedirs("data" + os.sep + "cache", exist_ok=True)
os.makedirs("reports", exist_ok=True)

import logging
from logging.handlers import RotatingFileHandler
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            os.path.join("logs", "apex_bot.log"),
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        ),
    ]
)

def parse_args():
    p = argparse.ArgumentParser(description="APEX Scalping Bot v12")
    p.add_argument("--mode", choices=["backtest","walkforward","paper","live"], required=True)
    p.add_argument("--days", type=int, default=30, help="Дней для backtest/walkforward")
    return p.parse_args()

async def startup_check(mode: str) -> bool:
    import config
    if not os.path.exists(".env"):
        logging.error("❌ Файл .env не найден!")
        logging.error("   Запусти setup.bat (Windows) и заполни .env своими API ключами.")
        return False
    if mode in ("paper","live"):
        if not config.BINANCE_API_KEY or config.BINANCE_API_KEY == "your_api_key_here":
            logging.error("❌ BINANCE_API_KEY не заполнен в .env")
            logging.error("   Инструкция: README.md → раздел 'Получение API ключей'")
            return False
        if not config.BINANCE_API_SECRET or config.BINANCE_API_SECRET == "your_api_secret_here":
            logging.error("❌ BINANCE_API_SECRET не заполнен в .env")
            return False
        if mode == "live" and not config.TESTNET:
            logging.warning("=" * 60)
            logging.warning("⚠️  ВНИМАНИЕ: TESTNET=false — РЕАЛЬНЫЕ ДЕНЬГИ!")
            logging.warning("   Прошло ли 2+ недели paper-тестирования?")
            logging.warning("   Запуск через 10 секунд... Нажми Ctrl+C для отмены.")
            logging.warning("=" * 60)
            await asyncio.sleep(10)
    return True

def _maybe_reset_daily(ps) -> None:
    """Сбросить дневную статистику если наступил новый день UTC."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if ps.daily_reset_date != today:
        ps.daily_pnl_usd   = 0.0
        ps.daily_pnl_pct   = 0.0
        ps.trades_today    = 0
        ps.wins_today      = 0
        ps.losses_today    = 0
        ps.daily_reset_date = today
        logging.info(f"📅 Новый торговый день: {today} — статистика сброшена")

HOT_RELOAD_FIELDS = ("MIN_CONFIDENCE", "MAX_RISK_PER_TRADE_PCT", "MAX_DAILY_LOSS_PCT")
STOP_TRADING_FILE = "STOP_TRADING"

def _kill_switch_triggered() -> bool:
    return os.path.exists(STOP_TRADING_FILE)

def _apply_hot_reload_subset(env_path: str) -> dict[str, tuple[float, float]]:
    values = dotenv_values(env_path)
    changed: dict[str, tuple[float, float]] = {}
    for field in HOT_RELOAD_FIELDS:
        raw = values.get(field)
        if raw is None or raw == "":
            continue
        try:
            new_val = float(raw)
            old_val = float(getattr(config, field))
        except Exception:
            continue
        if old_val != new_val:
            setattr(config, field, new_val)
            changed[field] = (old_val, new_val)
    return changed

async def run_config_hot_reload_loop(stop_event: asyncio.Event) -> None:
    """Hot reload for a restricted field set."""
    env_path = ".env"
    last_mtime = os.path.getmtime(env_path) if os.path.exists(env_path) else 0.0
    reload_event = asyncio.Event()

    if hasattr(signal, "SIGHUP"):
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGHUP, reload_event.set)
        except Exception:
            pass

    while not stop_event.is_set():
        try:
            if os.path.exists(env_path):
                current_mtime = os.path.getmtime(env_path)
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    changed = _apply_hot_reload_subset(env_path)
                    if changed:
                        patch = ", ".join(
                            f"{k}:{old:.4g}->{new:.4g}" for k, (old, new) in changed.items()
                        )
                        logging.info("HOT RELOAD: applied %s", patch)
            if reload_event.is_set():
                reload_event.clear()
                changed = _apply_hot_reload_subset(env_path)
                if changed:
                    patch = ", ".join(
                        f"{k}:{old:.4g}->{new:.4g}" for k, (old, new) in changed.items()
                    )
                    logging.info("HOT RELOAD (SIGHUP): applied %s", patch)
        except Exception as e:
            logging.warning(f"hot_reload: {e}")
        await asyncio.sleep(2.0)

def _open_report_file(path: str) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')
    except Exception as e:
        logging.warning(f"Не удалось открыть отчёт автоматически: {e}")

def _calc_reconnect_delay(base_delay_sec: int, attempt: int) -> int:
    base = max(1, int(base_delay_sec))
    return min(base * (2 ** max(attempt - 1, 0)), 60)


def _log_ai_startup_status() -> None:
    if not config.AI_ENABLED:
        logging.info("AI advisor: disabled (AI_ENABLED=false)")
        return
    try:
        from strategy.ai_advisor import _build_candidates

        candidates = _build_candidates()
        preview = ", ".join(f"{c.provider}/{c.model}" for c in candidates[:3])
        if len(candidates) > 3:
            preview = f"{preview}, +{len(candidates) - 3} more"
        logging.info(
            "AI advisor: enabled mode=%s provider=%s min_base=%.1f cooldown=%ss fail_open=%s candidates=%s [%s]",
            config.AI_MODE,
            config.AI_PROVIDER,
            config.AI_MIN_BASE_SCORE,
            config.AI_MIN_CALL_INTERVAL_SEC,
            config.AI_FAIL_OPEN,
            len(candidates),
            preview or "none",
        )
        if not candidates:
            logging.warning("AI advisor: enabled but no valid provider/key/model candidates found")
    except Exception as e:
        logging.warning("AI advisor startup check failed: %s", e)

async def run_backtest(days: int) -> None:
    import config
    config.BACKTEST_MODE = True
    from backtest.backtester import run
    from rich.table import Table; from rich.console import Console
    logging.info(f"▶ БЭКТЕСТ {days} дней...")
    r = await run(days)
    t = Table(title=f"Backtest Results ({days} дней)", show_lines=True)
    for col in ["Сделок","W/L","Win%","PF","Sharpe","MaxDD%","Net$"]:
        t.add_column(col)
    t.add_row(str(r.total_trades), f"{r.wins}/{r.losses}",
              f"{r.win_rate*100:.1f}%", f"{r.profit_factor:.2f}",
              f"{r.sharpe_ratio:.2f}", f"{r.max_drawdown_pct*100:.1f}%",
              f"{r.total_net_pnl:+.2f}$")
    Console().print(t)
    if r.total_trades == 0:
        logging.warning("⚠️  Бэктест: 0 сделок.")
        logging.warning("   Попробуй: --days 60, или снизь MIN_CONFIDENCE в config.py до 65.")
    try:
        from monitor import report
        report_path = report.generate("logs/trades_log.csv", r.equity_curve, days, r, trades_override=r.trades)
        logging.info(f"HTML отчёт сохранён: {report_path}")
        _open_report_file(report_path)
    except Exception as e:
        logging.warning(f"HTML report: {e}")

async def run_walkforward(days: int) -> None:
    import config
    config.BACKTEST_MODE = True
    from backtest.walk_forward import run
    reports = await run(total_days=days, window_days=30, step_days=15)
    if reports:
        logging.info(f"Walk-forward: сгенерировано HTML-отчётов: {len(reports)}")
        last_report = reports[-1].get("Report", "")
        if last_report:
            _open_report_file(last_report)

async def run_paper() -> None:
    import config
    config.PAPER_MODE = True
    import state
    from data.collector import CollectorState, preload_candles, run_market_stream, run_keepalive
    from data.rest_client import close as close_rest_session, get_session, sync_server_time
    from data.sentiment import run_sentiment_loop
    from execution import exchange_info
    from execution.position_tracker import maybe_close_deadman_position, maybe_close_expired_position
    from backtest.paper_engine import run_paper_signal_loop
    from monitor.dashboard import run as run_dashboard
    from monitor.notifier import send_startup
    from monitor.telegram_commands import run_telegram_command_loop

    ps = state.load()
    _maybe_reset_daily(ps)
    if ps.position:
        logging.info(f"🔄 ВОССТАНОВЛЕНА ПОЗИЦИЯ: {ps.position.direction} @ {ps.position.entry_price}")

    await sync_server_time()
    await exchange_info.load()

    cs = CollectorState()
    await preload_candles(cs, config.SYMBOL)
    from state import RuntimeState
    rs = RuntimeState()
    stop_event = asyncio.Event()

    async def signal_loop():
        while not stop_event.is_set():
            try:
                if _kill_switch_triggered():
                    logging.warning("Kill switch detected (%s). Stopping.", STOP_TRADING_FILE)
                    stop_event.set()
                    continue
                _maybe_reset_daily(ps)
                await run_paper_signal_loop(ps, rs, cs)
                if await maybe_close_deadman_position(ps, rs):
                    continue
                await maybe_close_expired_position(ps, rs)
            except Exception as e:
                logging.error(f"signal_loop: {e}", exc_info=True)
            await asyncio.sleep(1.0)

    async def ws_loop():
        attempt = 0
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                await run_market_stream(cs)
            except Exception as e:
                logging.warning(f"WS reco: {e}")
            uptime = time.monotonic() - started
            attempt = 0 if uptime >= 15 else (attempt + 1)
            if not stop_event.is_set():
                delay = _calc_reconnect_delay(config.WS_RECONNECT_DELAY_SEC, attempt)
                logging.info("WS reconnect in %ss (attempt=%s)", delay, attempt)
                await asyncio.sleep(delay)

    sess = await get_session()
    await send_startup("paper", ps.available_balance,
                       rs.sentiment.value if rs.sentiment.available else -1)

    tasks = [
        asyncio.create_task(ws_loop(),                         name="ws_loop"),
        asyncio.create_task(run_keepalive(cs),                 name="keepalive"),
        asyncio.create_task(signal_loop(),                     name="signal_loop"),
        asyncio.create_task(run_sentiment_loop(rs, sess),      name="sentiment"),
        asyncio.create_task(run_telegram_command_loop(ps, rs, stop_event), name="telegram_cmd"),
        asyncio.create_task(run_config_hot_reload_loop(stop_event), name="hot_reload"),
        asyncio.create_task(run_dashboard(ps, rs, "paper", stop_event), name="dashboard"),
    ]

    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        stop_event.set()
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_rest_session()
        _ask_close_position(ps)
        state.save(ps)
        logging.info("Бот остановлен.")

def _ask_close_position(ps) -> None:
    if not ps.position: return
    print(f"\n⚠️  Открытая позиция: {ps.position.direction} @ {ps.position.entry_price:.2f}")
    try:
        ans = input("Закрыть позицию при следующем запуске? [C=да / K=оставить]: ").strip().upper()
        if ans == "C":
            logging.info("Позиция будет закрыта при следующем запуске.")
    except (EOFError, KeyboardInterrupt):
        pass

async def run_live() -> None:
    import config
    config.PAPER_MODE = False
    import state
    from data.collector import CollectorState, preload_candles, run_market_stream, run_user_stream, run_keepalive
    from data.rest_client import close as close_rest_session, get_session, sync_server_time
    from data.sentiment import run_sentiment_loop
    from execution import exchange_info, exchange_setup
    from execution.position_sync import sync_on_startup
    from execution.position_tracker import (
        handle_queue_event,
        maybe_close_deadman_position,
        maybe_close_expired_position,
        update_trailing_stop,
    )
    from strategy.signal_engine import evaluate_signal
    from execution.order_manager import enter_trade, run_smoke_test_trade
    from monitor.dashboard import run as run_dashboard
    from monitor import logger as trade_logger
    from monitor.notifier import send_startup
    from monitor.telegram_commands import run_telegram_command_loop
    from state import RuntimeState
    from data.indicators import calculate
    from data.market_context import update as update_market_context

    ps = state.load()
    _maybe_reset_daily(ps)
    if ps.position:
        logging.info(f"🔄 ВОССТАНОВЛЕНА ПОЗИЦИЯ: {ps.position.direction} @ {ps.position.entry_price}")

    await sync_server_time()
    await exchange_setup.setup()
    await exchange_info.load()
    await sync_on_startup(ps)

    if config.LIVE_SMOKE_TEST_ON_START:
        if not config.TESTNET and not config.LIVE_SMOKE_ALLOW_MAINNET:
            logging.warning(
                "SMOKE TEST пропущен: TESTNET=false и LIVE_SMOKE_ALLOW_MAINNET=false"
            )
        else:
            logging.info(
                "SMOKE TEST: старт (вход до %ss, удержание %ss)",
                config.LIVE_SMOKE_MAX_WAIT_SEC,
                config.LIVE_SMOKE_HOLD_SEC,
            )
            ok = await run_smoke_test_trade(ps)
            if ok:
                logging.info("SMOKE TEST: успешно завершён")
            else:
                logging.warning("SMOKE TEST: не выполнен")
            await sync_on_startup(ps)

    cs = CollectorState()
    await preload_candles(cs, config.SYMBOL)
    rs = RuntimeState()
    stop_event = asyncio.Event()
    last_logged_rejection = {"value": ""}

    async def signal_loop():
        while not stop_event.is_set():
            try:
                if _kill_switch_triggered():
                    logging.warning("Kill switch detected (%s). Stopping.", STOP_TRADING_FILE)
                    stop_event.set()
                    continue
                _maybe_reset_daily(ps)
                for tf in ("1h", "15m", "5m", "1m"):
                    min_len = config.HTF_MIN_CANDLES if tf == "1h" else 50
                    if cs.new_candle_flags.get(tf) and len(cs.candles[tf]) >= min_len:
                        rs.indicators[tf] = calculate(cs.candles[tf], tf)
                        cs.new_candle_flags[tf] = False
                rs.micro = cs.micro
                if rs.indicators.get("15m"):
                    await update_market_context(rs, cs)
                if await maybe_close_deadman_position(ps, rs):
                    continue
                if await maybe_close_expired_position(ps, rs):
                    continue
                if ps.position and ps.position.tp1_filled:
                    await update_trailing_stop(ps, rs)
                if not ps.position:
                    sig = await evaluate_signal(ps, rs)
                    if sig:
                        last_logged_rejection["value"] = ""
                        pos = await enter_trade(sig, ps, rs)
                        if pos:
                            ps.position = pos
                            state.save(ps)
                    else:
                        ind15 = rs.indicators.get("15m")
                        rejection = rs.last_rejection_reason or "NO_SIGNAL"
                        if rejection != last_logged_rejection["value"]:
                            trade_logger.log_signal(
                                rejection, 0, 0, 0, 0, False, rejection, 0,
                                ind15.adx if ind15 and ind15.adx else 0,
                                rs.context.regime, rs.micro.spread_pct,
                                ind15.volume_ratio if ind15 and ind15.volume_ratio else 0,
                                rs.sentiment.value if rs.sentiment.available else -1,
                                rs.last_score_breakdown.to_str() if rs.last_score_breakdown else ""
                            )
                            last_logged_rejection["value"] = rejection
            except Exception as e:
                logging.error(f"live signal_loop: {e}", exc_info=True)
            await asyncio.sleep(1.0)

    async def order_queue_loop():
        while not stop_event.is_set():
            try:
                event = await asyncio.wait_for(cs.order_queue.get(), timeout=1.0)
                await handle_queue_event(event, ps, rs)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logging.error(f"order_queue: {e}", exc_info=True)

    async def ws_loop():
        attempt = 0
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                await run_market_stream(cs)
            except Exception as e:
                logging.warning(f"market WS: {e}")
            uptime = time.monotonic() - started
            attempt = 0 if uptime >= 15 else (attempt + 1)
            if not stop_event.is_set():
                delay = _calc_reconnect_delay(config.WS_RECONNECT_DELAY_SEC, attempt)
                logging.info("Market WS reconnect in %ss (attempt=%s)", delay, attempt)
                await asyncio.sleep(delay)

    async def user_ws_loop():
        attempt = 0
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                await run_user_stream(cs)
            except Exception as e:
                logging.warning(f"user WS: {e}")
            uptime = time.monotonic() - started
            attempt = 0 if uptime >= 15 else (attempt + 1)
            if not stop_event.is_set():
                delay = _calc_reconnect_delay(config.WS_RECONNECT_DELAY_SEC, attempt)
                logging.info("User WS reconnect in %ss (attempt=%s)", delay, attempt)
                await asyncio.sleep(delay)

    sess = await get_session()
    await send_startup("live", ps.available_balance,
                       rs.sentiment.value if rs.sentiment.available else -1)

    tasks = [
        asyncio.create_task(ws_loop(),                          name="ws_loop"),
        asyncio.create_task(user_ws_loop(),                     name="user_ws"),
        asyncio.create_task(run_keepalive(cs),                  name="keepalive"),
        asyncio.create_task(signal_loop(),                      name="signal_loop"),
        asyncio.create_task(order_queue_loop(),                 name="order_queue"),
        asyncio.create_task(run_sentiment_loop(rs, sess),       name="sentiment"),
        asyncio.create_task(run_telegram_command_loop(ps, rs, stop_event), name="telegram_cmd"),
        asyncio.create_task(run_config_hot_reload_loop(stop_event), name="hot_reload"),
        asyncio.create_task(run_dashboard(ps, rs, "live", stop_event), name="dashboard"),
    ]

    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        stop_event.set()
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_rest_session()
        _ask_close_position(ps)
        state.save(ps)
        logging.info("Live бот остановлен.")

async def main():
    args = parse_args()
    if not await startup_check(args.mode):
        sys.exit(1)
    _log_ai_startup_status()
    logging.info(f"=== APEX BOT v12 | режим: {args.mode} ===")
    if   args.mode == "backtest":    await run_backtest(args.days)
    elif args.mode == "walkforward": await run_walkforward(args.days)
    elif args.mode == "paper":       await run_paper()
    elif args.mode == "live":        await run_live()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Остановлен по Ctrl+C")
