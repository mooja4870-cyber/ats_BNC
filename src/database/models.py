"""SQLite 데이터베이스 스키마 및 기본 CRUD (Binance)"""

import sqlite3
from loguru import logger
from pathlib import Path

DB_PATH = Path("data/trades.db")


def init_database():
    """데이터베이스 초기화 (테이블 생성)"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # trades 테이블
    cur.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT UNIQUE NOT NULL,
        pair TEXT NOT NULL,
        side TEXT NOT NULL,
        position_side TEXT DEFAULT 'long',
        market_type TEXT DEFAULT 'swap',
        entry_price REAL,
        exit_price REAL,
        quantity REAL,
        entry_time DATETIME,
        exit_time DATETIME,
        pnl_pct REAL,
        pnl_usdt REAL,
        fee_usdt REAL,
        signal_score REAL,
        exit_reason TEXT,
        trade_mode TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 기존 테이블에 신규 컬럼 추가 (마이그레이션 호환)
    for col, col_type, default in [
        ("position_side", "TEXT", "'long'"),
        ("market_type", "TEXT", "'swap'"),
        ("pnl_usdt", "REAL", "NULL"),
        ("fee_usdt", "REAL", "NULL"),
    ]:
        try:
            cur.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type} DEFAULT {default}")
        except sqlite3.OperationalError:
            pass  # 이미 존재

    # daily_summary 마이그레이션
    for col, col_type, default in [
        ("total_pnl_usdt", "REAL", "0.0"),
        ("max_drawdown_pct", "REAL", "0.0"),
        ("balance_end", "REAL", "0.0"),
    ]:
        try:
            cur.execute(f"ALTER TABLE daily_summary ADD COLUMN {col} {col_type} DEFAULT {default}")
        except sqlite3.OperationalError:
            pass

    # daily_summary 테이블
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_summary (
        date TEXT PRIMARY KEY,
        total_trades INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0.0,
        total_pnl_usdt REAL DEFAULT 0.0,
        max_drawdown_pct REAL DEFAULT 0.0,
        balance_end REAL DEFAULT 0.0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # signals 테이블
    cur.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME,
        pair TEXT,
        signal_type TEXT,
        score REAL,
        conditions TEXT,
        acted BOOLEAN,
        reason_skipped TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()
    logger.info("[DB] ✅ 데이터베이스 초기화 완료")


def get_connection():
    """DB 연결 반환"""
    return sqlite3.connect(str(DB_PATH))


def close_connection(conn):
    """DB 연결 종료"""
    if conn:
        conn.close()
