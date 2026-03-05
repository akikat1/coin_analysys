"""
HTML-отчёт по результатам бэктеста.
Генерируется в папке reports/ после каждого backtest/walkforward.
Содержит: equity curve, таблицу сделок, метрики, score breakdown.

Использует Jinja2 для шаблонизации.
Открывается в браузере командой: start reports/backtest_YYYY-MM-DD.html
"""
import os, csv, json
from datetime import datetime, timezone
from pathlib import Path

_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="UTF-8">
<title>APEX BOT — Backtest Report</title>
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; background:#0d1117; color:#c9d1d9; margin:20px; }
  h1 { color:#58a6ff; } h2 { color:#79c0ff; border-bottom:1px solid #30363d; padding-bottom:6px; }
  table { border-collapse:collapse; width:100%; margin-bottom:20px; }
  th { background:#161b22; color:#58a6ff; padding:8px 12px; text-align:left; border:1px solid #30363d; }
  td { padding:6px 12px; border:1px solid #21262d; }
  tr:nth-child(even) { background:#161b22; }
  .positive { color:#3fb950; font-weight:bold; }
  .negative { color:#f85149; font-weight:bold; }
  .metric-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin:20px 0; }
  .metric-card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; }
  .metric-label { font-size:12px; color:#8b949e; }
  .metric-value { font-size:24px; font-weight:bold; margin-top:4px; }
  canvas { max-width:100%; margin:20px 0; }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head><body>
<h1>📊 APEX BOT — Backtest Report</h1>
<p>Сгенерирован: {{ generated_at }} | Период: {{ days }} дней</p>

<h2>Сводные метрики</h2>
<div class="metric-grid">
  {% for m in metrics %}
  <div class="metric-card">
    <div class="metric-label">{{ m.label }}</div>
    <div class="metric-value {{ m.css }}">{{ m.value }}</div>
  </div>
  {% endfor %}
</div>

<h2>Equity Curve</h2>
<canvas id="equityChart" height="80"></canvas>
<script>
new Chart(document.getElementById('equityChart'), {
  type: 'line',
  data: {
    labels: {{ equity_labels | tojson }},
    datasets: [{
      label: 'Equity ($)', data: {{ equity_data | tojson }},
      borderColor:'#58a6ff', backgroundColor:'rgba(88,166,255,0.1)',
      tension:0.3, pointRadius:0, fill:true
    }]
  },
  options: { plugins:{ legend:{display:false} }, scales:{ x:{display:false} } }
});
</script>

<h2>Сделки ({{ trades | length }})</h2>
<table>
<tr><th>#</th><th>Направление</th><th>Вход</th><th>Выход</th><th>Причина</th>
    <th>Net PnL</th><th>Длительность</th><th>Score</th></tr>
{% for t in trades %}
<tr>
  <td>{{ loop.index }}</td>
  <td style="color:{{ '#3fb950' if t.direction=='LONG' else '#f85149' }}">{{ t.direction }}</td>
  <td>{{ t.entry }}</td><td>{{ t.exit }}</td><td>{{ t.reason }}</td>
  <td class="{{ 'positive' if t.pnl > 0 else 'negative' }}">{{ '%.2f' | format(t.pnl) }}$</td>
  <td>{{ t.duration }}</td>
  <td>{{ t.confidence }}</td>
</tr>
{% endfor %}
</table>
</body></html>"""

def generate(trades_csv: str, equity_curve: list[float],
             days: int, result, trades_override: list[dict] | None = None) -> str:
    """
    Сгенерировать HTML-отчёт и сохранить в reports/.
    Возвращает путь к созданному файлу.

    Args:
        trades_csv: путь к logs/trades_log.csv
        equity_curve: список значений equity по сделкам
        days: количество дней бэктеста
        result: BacktestResult dataclass
    """
    from jinja2 import Template
    reports_dir = Path("reports"); reports_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    out_path = reports_dir / f"backtest_{today}_{days}d.html"

    trades = trades_override if trades_override is not None else _load_trades(trades_csv)
    equity_labels = list(range(len(equity_curve)))

    metrics = [
        {"label": "Всего сделок",    "value": str(result.total_trades),           "css": ""},
        {"label": "Win Rate",        "value": f"{result.win_rate*100:.1f}%",       "css": "positive" if result.win_rate >= 0.5 else "negative"},
        {"label": "Profit Factor",   "value": f"{result.profit_factor:.2f}",       "css": "positive" if result.profit_factor >= 1.5 else "negative"},
        {"label": "Sharpe Ratio",    "value": f"{result.sharpe_ratio:.2f}",        "css": "positive" if result.sharpe_ratio >= 1.0 else "negative"},
        {"label": "Max Drawdown",    "value": f"{result.max_drawdown_pct*100:.1f}%", "css": "negative" if result.max_drawdown_pct > 0.10 else ""},
        {"label": "Net P&L",         "value": f"{result.total_net_pnl:+.2f}$",    "css": "positive" if result.total_net_pnl > 0 else "negative"},
        {"label": "Avg Win",         "value": f"{result.avg_win:.2f}$",            "css": "positive"},
        {"label": "Avg Loss",        "value": f"{result.avg_loss:.2f}$",           "css": "negative"},
    ]

    # Jinja2 safe-filter для JSON
    import jinja2
    env = jinja2.Environment()
    env.filters["tojson"] = json.dumps
    tmpl = env.from_string(_TEMPLATE)
    html = tmpl.render(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        days=days,
        metrics=metrics,
        equity_labels=equity_labels,
        equity_data=[round(v, 2) for v in equity_curve],
        trades=trades
    )
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)

def _load_trades(csv_path: str) -> list[dict]:
    if not os.path.exists(csv_path): return []
    result = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dur_sec = int(row.get("duration_sec",0))
                dur_str = f"{dur_sec//60}m{dur_sec%60}s"
                result.append({
                    "direction":  row.get("direction",""),
                    "entry":      row.get("entry_price",""),
                    "exit":       row.get("exit_price",""),
                    "reason":     row.get("exit_reason",""),
                    "pnl":        float(row.get("net_pnl_partial",0) or 0),
                    "duration":   dur_str,
                    "confidence": row.get("confidence",""),
                })
            except Exception:
                continue
    return result

