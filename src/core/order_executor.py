"""주문 실행 모듈 (Binance 현물+선물)"""

from __future__ import annotations

import time
import json
import ccxt
from pathlib import Path
from loguru import logger
from src.utils.constants import (
    TradeMode,
    PositionSide,
    MarketType,
    MIN_ORDER_USDT,
    API_DELAY,
)
from src.utils.helpers import (
    create_exchange,
    normalize_symbol,
    now_kst,
    generate_trade_id,
)


class OrderExecutor:
    """Binance 현물+선물 주문 실행기 (ccxt)"""

    def __init__(self, config: dict, exchange: ccxt.Exchange | None = None):
        self.mode = TradeMode(config["trading"]["mode"])
        self.fee_rate = config["risk"]["fee_rate"]
        self.market_type = config["trading"].get("market_type", "swap")  # spot / swap
        self.leverage = int(config["trading"].get("leverage", 1))
        self.margin_mode = config["trading"].get("margin_mode", "isolated")

        if self.mode in (TradeMode.LIVE, TradeMode.DEMO):
            if exchange is not None:
                self.exchange = exchange
            else:
                self.exchange = create_exchange(
                    "binance", self.mode.value, market_type=self.market_type
                )
            # 선물 레버리지 설정
            if self.market_type in ("swap", "both"):
                self._set_leverage_for_pairs(config)
            logger.info(f"🔴 [OrderExecutor] {self.mode.value.upper()} 모드 초기화 (Binance)")
        else:
            self.exchange = create_exchange(
                "binance", "paper", market_type=self.market_type
            )
            self.exchange.timeout = 15000
            logger.info("🟡 [OrderExecutor] PAPER 모드 초기화 (Binance)")

        # 종이거래 가상 잔고
        self._paper_state_path = Path("data/paper_state.json")
        self._paper_balance_usdt = 10_000.0  # 10,000 USDT 가상
        self._paper_holdings: dict = {}  # {base_currency: quantity}
        self._price_cache: dict[str, float] = {}
        if self.mode == TradeMode.PAPER:
            self._load_paper_state()

    def _set_leverage_for_pairs(self, config: dict):
        """선물 모드 시 전체 페어 레버리지 설정 (Binance)"""
        pairs = config.get("trading", {}).get("pairs", [])
        for pair in pairs:
            symbol = normalize_symbol(pair, self.market_type)
            try:
                # Binance에서는 마진 모드 먼저 설정, 그 후 레버리지
                try:
                    self.exchange.set_margin_mode(
                        self.margin_mode, symbol
                    )
                    logger.info(
                        f"[OrderExecutor] 마진 모드 설정: {symbol} = {self.margin_mode}"
                    )
                except Exception as margin_err:
                    # 이미 동일한 마진 모드면 에러 발생 가능 — 무시
                    err_msg = str(margin_err).lower()
                    if "no need to change" in err_msg or "already" in err_msg:
                        logger.debug(
                            f"[OrderExecutor] 마진 모드 이미 설정됨: {symbol} = {self.margin_mode}"
                        )
                    else:
                        logger.warning(
                            f"[OrderExecutor] 마진 모드 설정 실패 {symbol}: {margin_err}"
                        )

                self.exchange.set_leverage(self.leverage, symbol)
                logger.info(
                    f"[OrderExecutor] 레버리지 설정: {symbol} = {self.leverage}x "
                    f"({self.margin_mode})"
                )
            except Exception as e:
                logger.warning(f"[OrderExecutor] 레버리지 설정 실패 {symbol}: {e}")

    # ═══════════════════════════════════════════
    #  공통 주문 인터페이스
    # ═══════════════════════════════════════════

    def open_long(self, pair: str, amount_usdt: float) -> dict | None:
        """
        롱 포지션 진입 (현물 매수 또는 선물 롱)

        Args:
            pair: 'BTC/USDT' (현물/선물 공통)
            amount_usdt: 주문 금액 (USDT)
        """
        if amount_usdt < MIN_ORDER_USDT:
            logger.warning(
                f"[OrderExecutor] 최소 주문금액 미달: {amount_usdt:.2f} USDT"
            )
            return None

        symbol = normalize_symbol(pair, self.market_type)
        trade_id = generate_trade_id(pair)

        if self.mode in (TradeMode.LIVE, TradeMode.DEMO):
            return self._live_open_long(symbol, amount_usdt, trade_id, pair)
        else:
            return self._paper_open_long(pair, amount_usdt, trade_id)

    def open_short(self, pair: str, amount_usdt: float) -> dict | None:
        """
        숏 포지션 진입 (선물 전용)

        Args:
            pair: 'BTC/USDT' 또는 'BTC/USDT:USDT' (선물)
            amount_usdt: 주문 금액 (USDT)
        """
        # Binance 선물에서는 :USDT 접미 없이도 숏 가능 (market_type으로 판별)
        if self.market_type not in ("swap", "both", "future", "futures"):
            logger.warning(f"[OrderExecutor] 숏은 선물 모드에서만 가능 (현재: {self.market_type})")
            return None

        if amount_usdt < MIN_ORDER_USDT:
            logger.warning(
                f"[OrderExecutor] 최소 주문금액 미달: {amount_usdt:.2f} USDT"
            )
            return None

        symbol = normalize_symbol(pair, self.market_type)
        trade_id = generate_trade_id(pair)

        if self.mode in (TradeMode.LIVE, TradeMode.DEMO):
            return self._live_open_short(symbol, amount_usdt, trade_id, pair)
        else:
            return self._paper_open_short(pair, amount_usdt, trade_id)

    def close_position(
        self, pair: str, quantity: float, position_side: str = "long"
    ) -> dict | None:
        """
        포지션 청산

        Args:
            pair: 심볼
            quantity: 청산 수량
            position_side: 'long' 또는 'short'
        """
        symbol = normalize_symbol(pair, self.market_type)
        trade_id = generate_trade_id(pair)

        if self.mode in (TradeMode.LIVE, TradeMode.DEMO):
            return self._live_close(symbol, quantity, position_side, trade_id, pair)
        else:
            return self._paper_close(pair, quantity, position_side, trade_id)

    # 레거시 호환 (main.py에서 buy_market/sell_market 호출 대체)
    def buy_market(self, pair: str, amount_usdt: float) -> dict | None:
        return self.open_long(pair, amount_usdt)

    def sell_market(self, pair: str, quantity: float) -> dict | None:
        return self.close_position(pair, quantity, "long")

    def get_all_positions_standardized(self) -> list[dict]:
        """
        거래소(또는 Paper)의 모든 포지션을 표준 형식으로 변환하여 반환
        Returns:
            [{'pair': 'BTC/USDT', 'side': 'long', 'qty': 0.1}, ...]
        """
        results = []
        if self.mode in (TradeMode.LIVE, TradeMode.DEMO):
            try:
                positions = self.exchange.fetch_positions()
                for pos in positions:
                    contracts = float(pos.get("contracts", 0))
                    if contracts > 0:
                        results.append({
                            "pair": pos["symbol"],
                            "side": "long" if pos["side"] == "long" else "short",
                            "qty": contracts
                        })
            except Exception as e:
                logger.error(f"[OrderExecutor] 포지션 조회 실패: {e}")
        else:
            # Paper 모드
            state = self.get_paper_balance()
            holdings = state.get("holdings", {})
            for symbol_base, qty in holdings.items():
                if qty > 0:
                    pair = f"{symbol_base}/USDT" if "SHORT_" not in symbol_base else f"{symbol_base.replace('SHORT_', '')}/USDT"
                    side = "short" if "SHORT_" in symbol_base else "long"
                    results.append({
                        "pair": pair,
                        "side": side,
                        "qty": qty
                    })
        return results

    def cancel_all_orders(self, pair: str | None = None) -> bool:
        """모든 미체결 주문 취소"""
        if self.mode in (TradeMode.LIVE, TradeMode.DEMO):
            try:
                if pair:
                    symbol = normalize_symbol(pair, self.market_type)
                    self.exchange.cancel_all_orders(symbol)
                else:
                    pass
                return True
            except Exception as e:
                logger.error(f"[OrderExecutor] 주문 취소 실패: {e}")
                return False
        else:
            # Paper 모드는 미체결 주문 시스템이 없으므로 항상 성공
            return True

    # ═══════════════════════════════════════════
    #  현재가 조회
    # ═══════════════════════════════════════════

    def _safe_get_current_price(self, pair: str, retries: int = 2) -> float | None:
        """현재가 조회 (재시도 포함)"""
        symbol = normalize_symbol(pair, self.market_type)
        for attempt in range(retries + 1):
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                price = float(ticker.get("last", 0))
                if price > 0:
                    self._price_cache[pair] = price
                    return price
            except Exception as e:
                if attempt == retries:
                    logger.warning(f"[OrderExecutor] 현재가 조회 실패: {pair} / {e}")
            time.sleep(API_DELAY * (attempt + 1))

        return self._price_cache.get(pair)

    @staticmethod
    def _format_price(price: float) -> str:
        """가격 표시 형식"""
        if price >= 1000:
            return f"{price:,.2f}"
        if price >= 1:
            return f"{price:,.4f}"
        return f"{price:.6f}"

    # ═══════════════════════════════════════════
    #  LIVE 주문 (Binance)
    # ═══════════════════════════════════════════

    def _live_open_long(
        self, symbol: str, amount_usdt: float, trade_id: str, original_pair: str = ""
    ) -> dict | None:
        """LIVE 롱 진입"""
        try:
            price = self._safe_get_current_price(symbol)
            if price is None or price <= 0:
                logger.error(f"[OrderExecutor] 가격 조회 실패: {symbol}")
                return None

            quantity = amount_usdt / price

            is_futures = self.market_type in ("swap", "future", "futures", "both")
            params = {}
            if is_futures:
                # Binance 선물 — 기본 양방향(Hedge Mode) 또는 One-way 모드에 따라 다름
                # 안전하게 positionSide 설정을 시도
                params["positionSide"] = "LONG"

            order = self.exchange.create_market_buy_order(symbol, quantity, params=params)
            time.sleep(API_DELAY)

            filled_price = float(order.get("average", price))
            filled_qty = float(order.get("filled", quantity))
            cost = float(order.get("cost", filled_price * filled_qty))
            fee_info = order.get("fee", {})
            fee = abs(float(fee_info.get("cost", 0))) if fee_info else cost * self.fee_rate

            pair_out = original_pair or symbol
            logger.info(
                f"[OrderExecutor] ✅ LIVE 롱 진입 | {pair_out} | "
                f"Price: {self._format_price(filled_price)} | Qty: {filled_qty:.6f}"
            )
            return {
                "trade_id": trade_id,
                "pair": pair_out,
                "side": "buy",
                "position_side": "long",
                "price": filled_price,
                "quantity": filled_qty,
                "amount_usdt": cost,
                "initial_margin": cost / self.leverage if self.leverage > 0 else cost,
                "fee_usdt": fee,
                "timestamp": now_kst().isoformat(),
                "mode": self.mode.value,
                "order_id": order.get("id"),
            }
        except Exception as e:
            logger.error(f"[OrderExecutor] LIVE 롱 진입 실패: {e}")
            return None

    def _live_open_short(
        self, symbol: str, amount_usdt: float, trade_id: str, original_pair: str = ""
    ) -> dict | None:
        """LIVE 숏 진입"""
        try:
            price = self._safe_get_current_price(symbol)
            if price is None or price <= 0:
                return None

            quantity = amount_usdt / price
            params = {
                "positionSide": "SHORT",
            }

            order = self.exchange.create_market_sell_order(symbol, quantity, params=params)
            time.sleep(API_DELAY)

            filled_price = float(order.get("average", price))
            filled_qty = float(order.get("filled", quantity))
            cost = float(order.get("cost", filled_price * filled_qty))
            fee_info = order.get("fee", {})
            fee = abs(float(fee_info.get("cost", 0))) if fee_info else cost * self.fee_rate

            pair_out = original_pair or symbol
            logger.info(
                f"[OrderExecutor] ✅ LIVE 숏 진입 | {pair_out} | "
                f"Price: {self._format_price(filled_price)} | Qty: {filled_qty:.6f}"
            )
            return {
                "trade_id": trade_id,
                "pair": pair_out,
                "side": "sell",
                "position_side": "short",
                "price": filled_price,
                "quantity": filled_qty,
                "amount_usdt": cost,
                "initial_margin": cost / self.leverage if self.leverage > 0 else cost,
                "fee_usdt": fee,
                "timestamp": now_kst().isoformat(),
                "mode": self.mode.value,
                "order_id": order.get("id"),
            }
        except Exception as e:
            logger.error(f"[OrderExecutor] LIVE 숏 진입 실패: {e}")
            return None

    def _live_close(
        self, symbol: str, quantity: float, position_side: str, trade_id: str,
        original_pair: str = ""
    ) -> dict | None:
        """LIVE 포지션 청산"""
        try:
            is_futures = self.market_type in ("swap", "future", "futures", "both")
            params = {}
            if is_futures:
                params["positionSide"] = position_side.upper()

            if position_side == "long":
                order = self.exchange.create_market_sell_order(symbol, quantity, params=params)
            else:  # short
                order = self.exchange.create_market_buy_order(symbol, quantity, params=params)

            time.sleep(API_DELAY)

            filled_price = float(order.get("average", 0))
            filled_qty = float(order.get("filled", quantity))
            cost = float(order.get("cost", filled_price * filled_qty))
            fee_info = order.get("fee", {})
            fee = abs(float(fee_info.get("cost", 0))) if fee_info else cost * self.fee_rate

            pair_out = original_pair or symbol
            side_label = "롱 청산" if position_side == "long" else "숏 청산"
            logger.info(
                f"[OrderExecutor] ✅ LIVE {side_label} | {pair_out} | "
                f"Price: {self._format_price(filled_price)} | Qty: {filled_qty:.6f}"
            )
            return {
                "trade_id": trade_id,
                "pair": pair_out,
                "side": "sell" if position_side == "long" else "buy",
                "position_side": position_side,
                "price": filled_price,
                "quantity": filled_qty,
                "amount_usdt": cost,
                "fee_usdt": fee,
                "timestamp": now_kst().isoformat(),
                "mode": self.mode.value,
                "order_id": order.get("id"),
            }
        except Exception as e:
            logger.error(f"[OrderExecutor] LIVE 포지션 청산 실패: {e}")
            return None

    # ═══════════════════════════════════════════
    #  PAPER 주문
    # ═══════════════════════════════════════════

    def _paper_open_long(
        self, pair: str, amount_usdt: float, trade_id: str
    ) -> dict | None:
        """PAPER 롱 진입"""
        try:
            # 잔고 체크 시 사용 증거금을 기준으로 확인합니다.
            margin = amount_usdt / self.leverage if self.leverage > 0 else amount_usdt

            price = self._safe_get_current_price(pair)
            if price is None:
                return None

            fee = amount_usdt * self.fee_rate
            quantity = amount_usdt / price

            if margin + fee > self._paper_balance_usdt:
                logger.warning(
                    f"[OrderExecutor] PAPER 잔고 부족 | 필요 증거금+수수료: {margin+fee:.2f} USDT | "
                    f"지갑잔고: {self._paper_balance_usdt:.2f} USDT"
                )
                return None

            # 롱 진입 시 지갑잔고(Wallet Balance)에서는 수수료만 차감
            self._paper_balance_usdt -= fee
            
            base = pair.split("/")[0]
            self._paper_holdings[base] = self._paper_holdings.get(base, 0) + quantity
            self._save_paper_state()

            logger.info(
                f"[OrderExecutor] 📝 PAPER 롱 진입 | {pair} | "
                f"Price: {self._format_price(price)} | Qty: {quantity:.6f} | "
                f"잔고: {self._paper_balance_usdt:.2f} USDT"
            )

            return {
                "trade_id": trade_id,
                "pair": pair,
                "side": "buy",
                "position_side": "long",
                "price": price,
                "quantity": quantity,
                "amount_usdt": amount_usdt,
                "initial_margin": margin,
                "fee_usdt": fee,
                "timestamp": now_kst().isoformat(),
                "mode": "paper",
            }
        except Exception as e:
            logger.error(f"[OrderExecutor] PAPER 롱 진입 오류: {e}")
            return None

    def _paper_open_short(
        self, pair: str, amount_usdt: float, trade_id: str
    ) -> dict | None:
        """PAPER 숏 진입"""
        try:
            margin = amount_usdt / self.leverage if self.leverage > 0 else amount_usdt

            price = self._safe_get_current_price(pair)
            if price is None:
                return None

            fee = amount_usdt * self.fee_rate
            quantity = amount_usdt / price

            if margin + fee > self._paper_balance_usdt:
                logger.warning(
                    f"[OrderExecutor] PAPER 잔고 부족 | 필요 증거금+수수료: {margin+fee:.2f} USDT | "
                    f"지갑잔고: {self._paper_balance_usdt:.2f} USDT"
                )
                return None

            # 숏 진입 시 지갑잔고(Wallet Balance)에서는 수수료만 차감
            self._paper_balance_usdt -= fee

            short_key = f"SHORT_{pair.split('/')[0]}"
            self._paper_holdings[short_key] = (
                self._paper_holdings.get(short_key, 0) + quantity
            )
            self._save_paper_state()

            logger.info(
                f"[OrderExecutor] 📝 PAPER 숏 진입 | {pair} | "
                f"Price: {self._format_price(price)} | Qty: {quantity:.6f} | "
                f"잔고: {self._paper_balance_usdt:.2f} USDT"
            )

            return {
                "trade_id": trade_id,
                "pair": pair,
                "side": "sell",
                "position_side": "short",
                "price": price,
                "quantity": quantity,
                "amount_usdt": amount_usdt,
                "initial_margin": margin,
                "fee_usdt": fee,
                "timestamp": now_kst().isoformat(),
                "mode": "paper",
            }
        except Exception as e:
            logger.error(f"[OrderExecutor] PAPER 숏 진입 오류: {e}")
            return None

    def _paper_close(
        self, pair: str, quantity: float, position_side: str, trade_id: str
    ) -> dict | None:
        """PAPER 포지션 청산"""
        try:
            price = self._safe_get_current_price(pair)
            if price is None:
                return None

            amount_usdt = quantity * price
            fee = amount_usdt * self.fee_rate

            if position_side == "long":
                base = pair.split("/")[0]
                self._paper_holdings[base] = max(
                    0, self._paper_holdings.get(base, 0) - quantity
                )
            else:  # short
                short_key = f"SHORT_{pair.split('/')[0]}"
                self._paper_holdings[short_key] = max(
                    0, self._paper_holdings.get(short_key, 0) - quantity
                )

            # 종이거래 지갑잔고(Wallet Balance)에서는 수수료만 차감
            # 실현손익은 별도로 반영(add_paper_pnl)
            self._paper_balance_usdt -= fee

            self._save_paper_state()

            side_label = "롱 청산" if position_side == "long" else "숏 청산"
            logger.info(
                f"[OrderExecutor] 📝 PAPER {side_label} | {pair} | "
                f"Price: {self._format_price(price)} | Qty: {quantity:.6f} | "
                f"잔고: {self._paper_balance_usdt:.2f} USDT"
            )

            return {
                "trade_id": trade_id,
                "pair": pair,
                "side": "sell" if position_side == "long" else "buy",
                "position_side": position_side,
                "price": price,
                "quantity": quantity,
                "amount_usdt": amount_usdt,
                "fee_usdt": fee,
                "timestamp": now_kst().isoformat(),
                "mode": "paper",
            }
        except Exception as e:
            logger.error(f"[OrderExecutor] PAPER 포지션 청산 오류: {e}")
            return None

    # ═══════════════════════════════════════════
    #  Paper State 관리
    # ═══════════════════════════════════════════

    def add_paper_pnl(self, pnl_usdt: float) -> None:
        """종이거래 지갑 잔고에 실현손익 추가"""
        if self.mode == TradeMode.PAPER:
            self._paper_balance_usdt += pnl_usdt
            self._save_paper_state()
            logger.info(
                f"[OrderExecutor] 📝 PAPER 손익 합산 | PnL: {pnl_usdt:+.2f} USDT | 잔고: {self._paper_balance_usdt:.2f} USDT"
            )

    def get_paper_balance(self) -> dict:
        """종이거래 잔고 조회"""
        return {
            "usdt": self._paper_balance_usdt,
            "holdings": self._paper_holdings.copy(),
        }

    def _load_paper_state(self) -> None:
        """종이거래 상태(현금/보유수량) 복구"""
        try:
            if not self._paper_state_path.exists():
                return
            raw = json.loads(self._paper_state_path.read_text(encoding="utf-8"))
            usdt = float(raw.get("usdt", self._paper_balance_usdt))
            holdings_raw = raw.get("holdings", {})
            holdings: dict[str, float] = {}
            if isinstance(holdings_raw, dict):
                for currency, qty in holdings_raw.items():
                    try:
                        qty_f = float(qty)
                    except (TypeError, ValueError):
                        continue
                    if qty_f > 0:
                        holdings[str(currency)] = qty_f
            self._paper_balance_usdt = max(0.0, usdt)
            self._paper_holdings = holdings
            logger.info(
                "[OrderExecutor] PAPER 상태 복구 완료 | "
                f"잔고: {self._paper_balance_usdt:.2f} USDT | 종목수: {len(holdings)}"
            )
        except Exception as e:
            logger.warning(f"[OrderExecutor] PAPER 상태 복구 실패: {e}")

    def _save_paper_state(self) -> None:
        """종이거래 상태(현금/보유수량) 저장"""
        try:
            self._paper_state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "usdt": float(self._paper_balance_usdt),
                "holdings": {
                    k: float(v)
                    for k, v in self._paper_holdings.items()
                    if float(v) > 0
                },
            }
            self._paper_state_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[OrderExecutor] PAPER 상태 저장 실패: {e}")
