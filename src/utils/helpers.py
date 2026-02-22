from __future__ import annotations

"""유틸리티 함수 (Binance 지원)"""

import os
import yaml
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import ccxt
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

KST = ZoneInfo("Asia/Seoul")


def load_config(path: str = "config/settings.yaml") -> dict:
    """YAML 설정 파일 로드"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_kst() -> datetime:
    """현재 한국 시간"""
    return datetime.now(KST)


def is_trading_session(config: dict) -> bool:
    """현재 시간이 매매 세션 내인지 확인"""
    schedule_cfg = config.get("schedule", {})
    if bool(schedule_cfg.get("always_on", False)):
        return True

    current = now_kst()
    current_time = current.strftime("%H:%M")
    sessions = schedule_cfg.get("sessions", [])

    def _in_session(start: str, end: str, now_hhmm: str) -> bool:
        # 자정을 넘지 않는 세션
        if start <= end:
            return start <= now_hhmm <= end
        # 자정을 넘는 세션 (예: 16:00~00:00, 22:00~06:00)
        return now_hhmm >= start or now_hhmm <= end

    for session in sessions:
        start = session["start"]
        end = session["end"]
        if _in_session(start, end, current_time):
            # 세션 종료 N분 전 신규 진입 차단 체크
            no_entry_min = int(schedule_cfg.get("no_entry_before_end_minutes", 15))
            if no_entry_min <= 0:
                return True

            now_dt = current.replace(second=0, microsecond=0)
            end_dt = current.replace(
                hour=int(end[:2]),
                minute=int(end[3:5]),
                second=0,
                microsecond=0,
            )
            if start > end and current_time >= start:
                end_dt += timedelta(days=1)

            cutoff_dt = end_dt - timedelta(minutes=no_entry_min)
            if now_dt <= cutoff_dt:
                return True

            logger.debug(f"세션 종료 {no_entry_min}분 전 — 신규 진입 차단")
            return False
    return False


def format_krw(amount: float) -> str:
    """KRW 금액 포맷팅 (레거시 호환)"""
    return f"{amount:,.0f} KRW"


def format_usdt(amount: float) -> str:
    """USDT 금액 포맷팅"""
    if abs(amount) >= 1:
        return f"{amount:,.2f} USDT"
    return f"{amount:.4f} USDT"


def format_pct(value: float) -> str:
    """퍼센트 포맷팅"""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def get_env(key: str, default=None):
    """환경변수 가져오기"""
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"환경변수 {key}가 설정되지 않았습니다.")
    return value


def normalize_symbol(pair: str) -> str:
    """OKX 스타일 심볼을 Binance 호환 형식으로 변환

    'BTC/USDT:USDT' -> 'BTC/USDT'
    'ETH/USDT'      -> 'ETH/USDT' (변경 없음)
    """
    if ":" in pair:
        return pair.split(":")[0]
    return pair


# ═══════════════════════════════════════════
#  Binance 자격증명
# ═══════════════════════════════════════════

def get_binance_credentials(mode: str = "live") -> dict:
    """모드별 Binance API 자격증명 조회 (passphrase 없음)"""
    mode = (mode or "").lower().strip()

    if mode == "demo":
        return {
            "apiKey": get_env("BINANCE_TESTNET_API_KEY"),
            "secret": get_env("BINANCE_TESTNET_SECRET_KEY"),
        }

    if mode == "live":
        return {
            "apiKey": get_env("BINANCE_API_KEY"),
            "secret": get_env("BINANCE_SECRET_KEY"),
        }

    return {}


# ═══════════════════════════════════════════
#  범용 거래소 생성 함수
# ═══════════════════════════════════════════

def create_exchange(
    exchange_name: str = "binance",
    mode: str = "paper",
    market_type: str | None = None,
    use_testnet: bool | None = None,
) -> ccxt.Exchange:
    """거래소 인스턴스 생성 (일반화)

    Args:
        exchange_name: 거래소 이름 ('binance')
        mode: 'paper' / 'demo' / 'live'
        market_type: 'spot' / 'swap' / 'future' (None이면 기본 spot)
        use_testnet: 명시적 테스트넷 사용 여부 (None이면 mode로 자동 결정)

    Returns:
        ccxt.Exchange 인스턴스
    """
    mode = (mode or "").lower().strip()
    exchange_name = (exchange_name or "binance").lower().strip()

    if exchange_name != "binance":
        raise ValueError(f"지원하지 않는 거래소: {exchange_name}")

    # 자격증명
    params: dict = {"enableRateLimit": True, "timeout": 15000}

    if mode in ("live", "demo"):
        params.update(get_binance_credentials(mode))

    # 선물 vs 현물 분기
    is_futures = market_type in ("swap", "future", "futures")

    if is_futures:
        # Binance USDT-M 선물 = binanceusdm
        exchange = ccxt.binanceusdm(params)
    else:
        exchange = ccxt.binance(params)

    # 테스트넷(sandbox) 설정
    if use_testnet is None:
        use_testnet = (mode == "demo")

    if use_testnet:
        try:
            exchange.set_sandbox_mode(True)
            logger.info(f"[Exchange] Binance {'선물' if is_futures else '현물'} Testnet 모드 활성화")
        except Exception as e:
            logger.warning(
                f"[Exchange] Binance Testnet 모드 설정 실패: {e} — "
                "Live 환경으로 동작합니다 (demo=live와 동일)"
            )

    return exchange


# 레거시 호환 함수 (기존 코드에서 import하는 곳이 있을 수 있으므로)
def create_okx_exchange(mode: str = "paper") -> ccxt.Exchange:
    """레거시 호환: create_exchange('binance', ...) 호출로 연결"""
    logger.debug("[helpers] create_okx_exchange() → create_exchange('binance', ...) 연결")
    return create_exchange("binance", mode)


def get_okx_credentials(mode: str = "live") -> dict:
    """레거시 호환: get_binance_credentials() 호출로 연결"""
    return get_binance_credentials(mode)


def generate_trade_id(pair: str) -> str:
    """고유 거래 ID 생성"""
    ts = now_kst().strftime("%Y%m%d%H%M%S%f")
    clean_pair = pair.replace("/", "").replace(":", "_")
    return f"{clean_pair}_{ts}"


def symbol_to_base(pair: str) -> str:
    """심볼에서 기초자산 이름 추출

    'BTC/USDT:USDT' -> 'BTC'
    'BTC/USDT'      -> 'BTC'
    """
    return pair.split("/")[0]
