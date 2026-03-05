"""
Rich-дашборд v12.
Завершается через asyncio.CancelledError — не через threading.Event.
"""
import asyncio
from datetime import datetime, timezone

async def run(ps, rs, mode: str, stop_event: asyncio.Event):
    from rich.live import Live
    from rich.table import Table
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text
    import config

    def _color_pnl(v: float) -> str:
        return f"[green]{v:+.2f}$[/green]" if v >= 0 else f"[red]{v:+.2f}$[/red]"

    def _sentiment_color(val: int) -> str:
        if val <= 24:   return f"[bold red]Extreme Fear ({val})[/bold red]"
        if val <= 44:   return f"[red]Fear ({val})[/red]"
        if val <= 55:   return f"[yellow]Neutral ({val})[/yellow]"
        if val <= 74:   return f"[green]Greed ({val})[/green]"
        return f"[bold green]Extreme Greed ({val})[/bold green]"

    def _rejection_color(reason: str) -> str:
        if reason == "PASSED":  return f"[green]{reason}[/green]"
        if not reason:          return "[dim]—[/dim]"
        return f"[yellow]{reason}[/yellow]"

    def _build() -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        layout["body"].split_row(Layout(name="left"), Layout(name="right"))

        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        net = _color_pnl(ps.daily_pnl_usd)
        mode_str = f"[bold cyan]{mode.upper()}[/bold cyan]"
        testnet  = "[yellow]TESTNET[/yellow]" if config.TESTNET else "[bold red]MAINNET![/bold red]"
        layout["header"].update(Panel(
            f"APEX BOT {mode_str} | {testnet} | {now} | Дневной P&L: {net}",
            style="bold"))

        t = Table.grid(padding=(0,1))
        ind15 = rs.indicators.get("15m")
        t.add_row("Режим рынка:", f"[cyan]{rs.context.regime}[/cyan] {rs.context.trend_dir}")
        t.add_row("ADX (15m):",   f"{ind15.adx:.1f}" if ind15 and ind15.adx else "—")
        t.add_row("RSI (15m):",   f"{ind15.rsi:.1f}" if ind15 and ind15.rsi else "—")
        t.add_row("Funding:",     f"{rs.micro.funding_rate:.6f}")
        t.add_row("OBI:",         f"{rs.micro.obi:+.3f}")
        t.add_row("CVD 5m:",      f"{rs.micro.cvd_300s:+.4f}")
        t.add_row("Spread:",      f"{rs.micro.spread_pct*100:.4f}%")
        t.add_row("Mark Price:",  f"{rs.micro.mark_price:.2f}")
        sent = rs.sentiment
        t.add_row("Fear&Greed:",  _sentiment_color(sent.value) if sent.available else "[dim]—[/dim]")
        t.add_row("Last Signal:", _rejection_color(rs.last_rejection_reason))
        if config.AI_ENABLED:
            ai_text = rs.last_ai_note if rs.last_ai_note else "—"
            t.add_row("AI advisor:", f"[magenta]{ai_text[:90]}[/magenta]")
        if rs.last_score_breakdown:
            t.add_row("Score breakdown:", f"[dim]{rs.last_score_breakdown.to_str()[:90]}[/dim]")
        layout["left"].update(Panel(t, title="📊 Рынок"))

        t2 = Table.grid(padding=(0,1))
        pos = ps.position
        if pos:
            pnl_unreal = ((rs.micro.mark_price - pos.avg_fill_price) * pos.qty_remaining
                          * (1 if pos.direction=="LONG" else -1))
            t2.add_row("Направление:", f"[{'green' if pos.direction=='LONG' else 'red'}]{pos.direction}[/]")
            t2.add_row("Вход:",        f"{pos.entry_price:.2f}")
            stop_label = f"[red]{pos.stop_price:.2f}[/red]"
            if pos.trailing_stop_active:
                stop_label += " [cyan]↑TRAIL[/cyan]"
            elif pos.tp1_filled:
                stop_label += " [yellow](BE)[/yellow]"
            t2.add_row("Стоп:",        stop_label)
            t2.add_row("TP1:",         f"[green]{pos.tp1_price:.2f}[/green]" +
                                       (" ✓" if pos.tp1_filled else ""))
            t2.add_row("TP2:",         f"[green]{pos.tp2_price:.2f}[/green]" +
                                       (" ✓" if pos.tp2_filled else ""))
            t2.add_row("TP3:",         f"[green]{pos.tp3_price:.2f}[/green]")
            t2.add_row("Кол-во:",      f"{pos.qty_remaining:.4f} BTC")
            t2.add_row("Нереал P&L:",  _color_pnl(pnl_unreal))
            t2.add_row("Реал P&L:",    _color_pnl(pos.realized_pnl_usd))
            t2.add_row("Уверенность:", f"{pos.confidence_at_entry:.0f}")
        else:
            t2.add_row("[dim]Нет открытой позиции[/dim]", "")
        layout["right"].update(Panel(t2, title="💰 Позиция"))

        w = ("⬇" if ps.reduced_size_active else "")
        dd = f"[red]{ps.equity_drawdown_pct*100:.2f}%[/red]" if ps.equity_drawdown_pct > 0.05 else f"{ps.equity_drawdown_pct*100:.2f}%"
        layout["footer"].update(Panel(
            f"Баланс: [bold]{ps.available_balance:.2f}$[/bold]  "
            f"Сделок: {ps.trades_today} (W:{ps.wins_today}/L:{ps.losses_today})  "
            f"Серия убытков: {ps.consecutive_losses}  "
            f"Просадка: {dd}  {w}",
            style="dim"))
        return layout

    try:
        with Live(refresh_per_second=1, screen=True) as live:
            while not stop_event.is_set():
                live.update(_build())
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass

