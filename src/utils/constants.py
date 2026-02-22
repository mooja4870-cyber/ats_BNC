"""상수 정의 (Binance)"""

from enum import Enum

class TradeMode(Enum):
    PAPER = "paper"
    DEMO = "demo"
    LIVE = "live"

class Side(Enum):
    BUY = "buy"
    SELL = "sell"

class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"

class MarketType(Enum):
    SPOT = "spot"
    SWAP = "swap"

class ExitReason(Enum):
    TAKE_PROFIT = "tp"
    STOP_LOSS = "sl"
    DEAD_CROSS = "dead_cross"
    TIMEOUT = "timeout"
    EMERGENCY = "emergency"
    MANUAL = "manual"

class SignalType(Enum):
    LONG = "long"
    SHORT = "short"
    EXIT = "exit"
    HOLD = "hold"

# API 제한 (Binance)
API_RATE_LIMIT = 20              # 초당 최대 요청 (가중치 기반이므로 보수적)
API_DELAY = 0.05                 # 요청 간 최소 딜레이(초)
MIN_ORDER_USDT = 5               # 최소 주문 금액 (USDT) — Binance minNotional ~5 USDT

# 레거시 호환 별칭 (기존 import 깨지지 않도록)
OKX_API_RATE_LIMIT = API_RATE_LIMIT
OKX_API_DELAY = API_DELAY
OKX_MIN_ORDER_USDT = MIN_ORDER_USDT

# 캔들 데이터 설정
MIN_CANDLES_FOR_INDICATORS = 50  # 지표 계산 최소 캔들 수
MAX_CANDLES_CACHE = 200          # 캐시 유지 캔들 수

# 타임프레임 매핑 (레거시 → ccxt 형식)
TIMEFRAME_MAP = {
    "minute1": "1m",
    "minute5": "5m",
    "minute15": "15m",
    "minute60": "1h",
    "day": "1d",
    # ccxt 네이티브 형식도 허용
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "1d": "1d",
}
