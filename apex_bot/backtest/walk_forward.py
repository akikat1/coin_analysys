"""
Walk-forward тест v12.
Исправление vs v11: offset_start теперь ПЕРЕДАЁТСЯ в backtester.run()
через параметр start_offset_days. Каждое окно тестирует разные данные.

Пример для total_days=90, window_days=30, step_days=15:
  Окно 1: данные 90d..60d назад  (start_offset_days=60)
  Окно 2: данные 75d..45d назад  (start_offset_days=45)
  Окно 3: данные 60d..30d назад  (start_offset_days=30)
  Окно 4: данные 45d..15d назад  (start_offset_days=15)
  Окно 5: данные 30d..0d  назад  (start_offset_days=0)
"""
import asyncio, logging
from backtest.backtester import run as bt_run, BacktestResult

async def run(total_days: int=180, window_days: int=30, step_days: int=15) -> list[dict]:
    """
    Возвращает список словарей с метриками по каждому окну.
    Каждое окно тестирует РАЗНЫЙ период (offset_start НЕ равен нулю для всех).
    """
    import config
    config.BACKTEST_MODE = True
    results = []
    # Вычислить все окна: самое раннее окно заканчивается на (total_days - window_days) дней назад
    n_windows = (total_days - window_days) // step_days + 1
    logging.info(f"Walk-forward: {total_days} дней, {n_windows} окон по {window_days}д, шаг {step_days}д")

    for i in range(n_windows):
        # offset_start = сколько дней назад ЗАКАНЧИВАЕТСЯ это окно
        offset_start = (n_windows - 1 - i) * step_days
        label = f"W{i+1} [offset={offset_start}d]"
        logging.info(f"  {label} — тестируем {window_days}д, заканчивая {offset_start}д назад")
        # ← ИСПРАВЛЕНО v12: передаём start_offset_days=offset_start
        r: BacktestResult = await bt_run(days=window_days, start_offset_days=offset_start)
        report_path = ""
        try:
            from monitor import report
            report_path = report.generate(
                "logs/trades_log.csv", r.equity_curve, window_days, r, trades_override=r.trades
            )
            logging.info(f"{label}: HTML отчёт {report_path}")
        except Exception as e:
            logging.warning(f"{label}: report.generate: {e}")
        results.append({
            "Окно": label,
            "Сделок": r.total_trades,
            "W/L": f"{r.wins}/{r.losses}",
            "Win%": f"{r.win_rate*100:.1f}%",
            "PF": f"{r.profit_factor:.2f}",
            "Sharpe": f"{r.sharpe_ratio:.2f}",
            "MaxDD%": f"{r.max_drawdown_pct*100:.1f}%",
            "Net$": f"{r.total_net_pnl:+.2f}",
            "Report": report_path,
        })

    _print_table(results)
    return results

def _print_table(rows: list[dict]) -> None:
    from rich.table import Table
    from rich.console import Console
    t = Table(title="Walk-Forward Results", show_lines=True)
    if not rows: return
    for col in rows[0].keys(): t.add_column(col)
    for row in rows: t.add_row(*[str(v) for v in row.values()])
    Console().print(t)

