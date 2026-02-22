"""Binance 데이터 수집 모듈 (ccxt 기반)"""

from __future__ import annotations

import time
import ccxt
import pandas as pd
from loguru import logger
from src.utils.constants import (
    API_DELAY,
    MAX_CANDLES_CACHE,
    MIN_CANDLES_FOR_INDICATORS,
    TIMEFRAME_MAP,
)
from src.utils.helpers import normalize_symbol


class DataFetcher:
    """Binance 캔들/시세 데이터 수집기 (ccxt)"""

    def __init__(self, exchange: ccxt.Exchange | None = None):
        """
        Args:
            exchange: ccxt.Exchange 인스턴스 (None이면 public API 전용 인스턴스 생성)
        """
        if exchange is not None:
            self.exchange = exchange
        else:
            self.exchange = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 15000})
        self.market_type = "swap" if "usdm" in self.exchange.id.lower() or "future" in self.exchange.id.lower() else "spot"
        self._cache: dict[str, pd.DataFrame] = {}
        self._price_cache: dict[str, float] = {}
        self._last_request_time: float = 0
        self._warn_last_ts: dict[str, float] = {}
        self._warn_suppressed: dict[str, int] = {}
        self._warn_throttle_seconds = 300

    # ── 내부 유틸 ──

    def _warn_throttled(self, key: str, message: str) -> None:
        """동일 경고 메시지를 일정 시간 간격으로만 출력"""
        self._log_throttled(key, message, level="warning")

    def _log_throttled(self, key: str, message: str, level: str = "warning") -> None:
        """동일 로그 메시지를 일정 시간 간격으로만 출력"""
        now = time.time()
        last = self._warn_last_ts.get(key, 0.0)
        if now - last >= self._warn_throttle_seconds:
            suppressed = self._warn_suppressed.get(key, 0)
            if suppressed > 0:
                message = f"{message} (유사 경고 {suppressed}건 생략)"
            log_fn = getattr(logger, level, logger.warning)
            log_fn(message)
            self._warn_last_ts[key] = now
            self._warn_suppressed[key] = 0
        else:
            self._warn_suppressed[key] = self._warn_suppressed.get(key, 0) + 1

    def _rate_limit(self):
        """API Rate Limit 준수"""
        elapsed = time.time() - self._last_request_time
        if elapsed < API_DELAY:
            time.sleep(API_DELAY - elapsed)
        self._last_request_time = time.time()

    @staticmethod
    def _resolve_timeframe(interval: str) -> str:
        """타임프레임을 ccxt 표준으로 변환"""
        return TIMEFRAME_MAP.get(interval, interval)

    # ── 캔들 데이터 ──

    def get_candles(
        self,
        pair: str,
        interval: str = "5m",
        count: int = MAX_CANDLES_CACHE,
    ) -> pd.DataFrame | None:
        """
        캔들 데이터 조회

        Args:
            pair: 'BTC/USDT' (현물/선물 공통)
            interval: '1m', '5m', '15m', '1h', '1d' (ccxt 표준)
            count: 캔들 개수

        Returns:
            OHLCV DataFrame 또는 None
        """
        symbol = normalize_symbol(pair, self.market_type)
        tf = self._resolve_timeframe(interval)
        cache_key = f"{pair}_{tf}"

        try:
            ohlcv = None
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    self._rate_limit()
                    ohlcv = self.exchange.fetch_ohlcv(symbol, tf, limit=count)
                    if ohlcv and len(ohlcv) > 0:
                        break
                except ccxt.NetworkError as e:
                    if attempt < max_retries:
                        time.sleep(0.3 * (attempt + 1))
                        continue
                    raise
                if attempt < max_retries:
                    time.sleep(0.2 * (attempt + 1))

            if not ohlcv or len(ohlcv) == 0:
                if cache_key in self._cache:
                    logger.warning(
                        f"[DataFetcher] {pair} {tf} 데이터 비어있음 — 캐시 데이터 사용"
                    )
                    return self._cache[cache_key]
                logger.warning(f"[DataFetcher] {pair} {tf} 데이터 비어있음")
                return None

            # ccxt OHLCV → DataFrame 변환
            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("timestamp")
            df = df[["open", "high", "low", "close", "volume"]].astype(float)

            if len(df) < MIN_CANDLES_FOR_INDICATORS:
                if (
                    cache_key in self._cache
                    and len(self._cache[cache_key]) >= MIN_CANDLES_FOR_INDICATORS
                ):
                    logger.warning(
                        f"[DataFetcher] {pair} 캔들 부족: "
                        f"{len(df)}/{MIN_CANDLES_FOR_INDICATORS} — 캐시 데이터 사용"
                    )
                    return self._cache[cache_key]
                logger.warning(
                    f"[DataFetcher] {pair} 캔들 부족: "
                    f"{len(df)}/{MIN_CANDLES_FOR_INDICATORS}"
                )
                return None

            # NaN 체크
            if df.isnull().any().any():
                logger.warning(f"[DataFetcher] {pair} NaN 값 발견 — 제거")
                df = df.dropna()

            # 캐시 업데이트
            self._cache[cache_key] = df

            logger.debug(
                f"[DataFetcher] {pair} {tf} — {len(df)}개 캔들 수집 완료"
            )
            return df

        except Exception as e:
            logger.error(f"[DataFetcher] {pair} {tf} 데이터 수집 실패: {e}")
            if cache_key in self._cache:
                logger.info(f"[DataFetcher] 캐시 데이터 반환: {cache_key}")
                return self._cache[cache_key]
            return None

    # ── 현재가 조회 ──

    def get_current_price(self, pair: str) -> float | None:
        """현재가 조회"""
        symbol = normalize_symbol(pair, self.market_type)
        try:
            self._rate_limit()
            ticker = self.exchange.fetch_ticker(symbol)
            price = float(ticker.get("last", 0))
            if price > 0:
                self._price_cache[pair] = price
                return price
            return self._price_cache.get(pair)
        except Exception as e:
            self._log_throttled(
                f"{pair}:price_error",
                f"[DataFetcher] {pair} 현재가 조회 실패: {e!r}",
                level="warning",
            )
            return self._price_cache.get(pair)

    def get_current_prices(self, pairs: list[str]) -> dict[str, float]:
        """여러 페어 현재가 조회"""
        pairs = [p for p in pairs if isinstance(p, str) and p]
        if not pairs:
            return {}

        result: dict[str, float] = {}
        symbols = [normalize_symbol(p, self.market_type) for p in pairs]

        # ccxt fetch_tickers 사용 (배치 조회)
        try:
            self._rate_limit()
            tickers = self.exchange.fetch_tickers(symbols)
            for pair, symbol in zip(pairs, symbols):
                ticker = tickers.get(symbol, {})
                price = ticker.get("last")
                if price is not None and float(price) > 0:
                    result[pair] = float(price)
                    self._price_cache[pair] = float(price)
        except Exception as e:
            self._log_throttled(
                "batch_ticker_error",
                f"[DataFetcher] 배치 현재가 조회 실패: {e!r}",
                level="warning",
            )

        # 누락된 페어는 개별 조회
        missing_pairs = [p for p in pairs if p not in result]
        for pair in missing_pairs:
            price = self.get_current_price(pair)
            if price is not None:
                result[pair] = price

        return result

    # ── 호가창 ──

    def get_orderbook(self, pair: str, limit: int = 5) -> dict | None:
        """호가창 조회"""
        symbol = normalize_symbol(pair, self.market_type)
        try:
            self._rate_limit()
            orderbook = self.exchange.fetch_order_book(symbol, limit)
            return orderbook
        except Exception as e:
            logger.error(f"[DataFetcher] {pair} 호가창 조회 실패: {e}")
            return None

    # ── 잔고 조회 ──

    def get_balance(self, market_type: str = "swap") -> dict:
        """
        계좌 잔고 조회

        Args:
            market_type: 'spot' 또는 'swap'

        Returns:
            {
                'USDT': {'free': float, 'used': float, 'total': float},
                'BTC': {'free': float, 'used': float, 'total': float},
                ...
            }
        """
        try:
            self._rate_limit()
            params = {}
            # Binance에서는 exchange 인스턴스 자체가 선물/현물 구분
            # 추가 params 없이도 정상 동작

            raw_balance = self.exchange.fetch_balance(params)
            result = {}

            # Binance는 totalEq 대신 totalWalletBalance 등 사용
            info_data = raw_balance.get("info", {})
            if isinstance(info_data, dict):
                total_wallet = info_data.get("totalWalletBalance")
                if total_wallet is not None:
                    result["INFO"] = {
                        "totalEq": float(total_wallet or 0.0),
                        "isoEq": float(info_data.get("totalCrossUnPnl", 0) or 0.0)
                    }

            for currency, info in raw_balance.items():
                if currency in ("info", "free", "used", "total", "timestamp", "datetime"):
                    continue
                if isinstance(info, dict):
                    total = float(info.get("total", 0) or 0)
                    if total > 0:
                        result[currency] = {
                            "free": float(info.get("free", 0) or 0),
                            "used": float(info.get("used", 0) or 0),
                            "total": total,
                        }
            return result
        except Exception as e:
            logger.error(f"[DataFetcher] 잔고 조회 실패: {e}")
            return {}

    # ── 티커 조회 ──

    def get_ticker(self, pair: str) -> dict | None:
        """24h 티커 정보 조회"""
        symbol = normalize_symbol(pair, self.market_type)
        try:
            self._rate_limit()
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            logger.error(f"[DataFetcher] {pair} 티커 조회 실패: {e}")
            return None
