import asyncio
import logging
from pathlib import Path


DB_PATH = Path("data") / "trades.db"

_INIT_LOCK = asyncio.Lock()
_DB_READY = False
_DRIVER_CHECKED = False
_HAS_DRIVER = False
_MISSING_DRIVER_WARNED = False

_COLUMNS = [
    "ts_open",
    "ts_close",
    "direction",
    "entry_price",
    "avg_fill",
    "exit_price",
    "qty_btc",
    "closed_qty",
    "leverage",
    "margin_usd",
    "gross_pnl",
    "entry_fee",
    "exit_fee",
    "slippage",
    "net_pnl_partial",
    "realized_total",
    "net_pct_margin",
    "duration_sec",
    "exit_reason",
    "confidence",
    "adx_entry",
    "regime_entry",
    "funding_entry",
    "mode",
]


def _maybe_get_driver():
    global _DRIVER_CHECKED, _HAS_DRIVER, _MISSING_DRIVER_WARNED

    if not _DRIVER_CHECKED:
        _DRIVER_CHECKED = True
        try:
            import aiosqlite  # type: ignore

            _HAS_DRIVER = True
            return aiosqlite
        except Exception:
            _HAS_DRIVER = False
            if not _MISSING_DRIVER_WARNED:
                _MISSING_DRIVER_WARNED = True
                logging.warning("SQLite logging disabled: install aiosqlite")
            return None

    if not _HAS_DRIVER:
        return None

    import aiosqlite  # type: ignore

    return aiosqlite


async def _ensure_ready() -> bool:
    global _DB_READY

    drv = _maybe_get_driver()
    if drv is None:
        return False
    if _DB_READY:
        return True

    async with _INIT_LOCK:
        if _DB_READY:
            return True
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with drv.connect(DB_PATH) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_open INTEGER,
                    ts_close INTEGER,
                    direction TEXT,
                    entry_price REAL,
                    avg_fill REAL,
                    exit_price REAL,
                    qty_btc REAL,
                    closed_qty REAL,
                    leverage INTEGER,
                    margin_usd REAL,
                    gross_pnl REAL,
                    entry_fee REAL,
                    exit_fee REAL,
                    slippage REAL,
                    net_pnl_partial REAL,
                    realized_total REAL,
                    net_pct_margin REAL,
                    duration_sec INTEGER,
                    exit_reason TEXT,
                    confidence REAL,
                    adx_entry REAL,
                    regime_entry TEXT,
                    funding_entry REAL,
                    mode TEXT
                )
                """
            )
            await db.commit()
        _DB_READY = True
    return True


async def insert_trade(row: dict) -> None:
    """Best-effort async insert for trade rows. Failures must not break trading."""
    if not await _ensure_ready():
        return
    drv = _maybe_get_driver()
    if drv is None:
        return

    try:
        vals = [row.get(c) for c in _COLUMNS]
        placeholders = ",".join("?" for _ in _COLUMNS)
        sql = f"INSERT INTO trades ({','.join(_COLUMNS)}) VALUES ({placeholders})"
        async with drv.connect(DB_PATH) as db:
            await db.execute(sql, vals)
            await db.commit()
    except Exception as e:
        logging.warning("SQLite insert failed: %s", e)
