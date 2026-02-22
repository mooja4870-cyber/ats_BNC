"""매매 신호 생성 엔진 (롱/숏 지원)"""
from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from loguru import logger
from src.utils.helpers import now_kst


@dataclass
class Signal:
    """매매 신호 데이터"""
    pair: str
    signal_type: str        # "long" | "short" | "exit" | "hold"
    score: float            # 0~100
    conditions: dict = field(default_factory=dict)
    reason: str = ""
    timestamp: str = ""
    price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_side: str = "long"  # "long" | "short"
    quantity_pct: float = 1.0     # 청산 시 수량 비율 (0.3, 1.0 등)


class SignalEngine:
    """롱/숏 신호 생성"""

    def __init__(self, config: dict):
        self.cfg_trading = config["trading"]
        self.cfg_ind = config["indicators"]
        self.cfg_risk = config["risk"]
        self._last_signal_time: dict[str, str] = {}  # 중복 방지

    # ═══════════════════════════════════════════
    #  롱 신호 (= 기존 매수 신호)
    # ═══════════════════════════════════════════

    def check_long_signal(
        self,
        pair: str,
        df_main: pd.DataFrame,     # 5분봉
        df_trend: pd.DataFrame,    # 1시간봉
    ) -> Signal:
        """
        롱 진입 신호 확인

        조건 (모두 충족):
          1. EMA 9 > EMA 21 (5분봉)
          2. RSI 40~55 (5분봉)
          3. 현재가 > 볼린저밴드 중간선 (5분봉)
          4. 거래량 >= 20봉 평균 × 1.5 (5분봉)
          5. 현재가 > VWAP (5분봉)
          6. EMA 9 > EMA 21 (1시간봉, 큰 추세)
        """
        latest = df_main.iloc[-1]
        trend_latest = df_trend.iloc[-1]

        conditions = {}

        # 조건 1: EMA 골든크로스 상태
        conditions["ema_bullish"] = bool(latest.get("ema_bullish", False))

        # 조건 2: RSI 범위
        rsi = latest.get("rsi", 50)
        rsi_min = self.cfg_ind["rsi_buy_min"]
        rsi_max = self.cfg_ind["rsi_buy_max"]
        conditions["rsi_in_range"] = (
            rsi_min <= rsi <= rsi_max if pd.notna(rsi) else False
        )

        # 조건 3: 현재가 > 볼린저 밴드 중간선
        close = latest.get("close", 0)
        bb_mid = latest.get("bb_mid", 0)
        conditions["above_bb_mid"] = close > bb_mid if pd.notna(bb_mid) else False

        # 조건 4: 거래량 급증
        conditions["volume_surge"] = bool(latest.get("vol_surge", False))

        # 조건 5: 현재가 > VWAP
        vwap = latest.get("vwap", 0)
        conditions["above_vwap"] = close > vwap if pd.notna(vwap) else False

        # 조건 6: 1시간봉 상승 추세
        conditions["trend_bullish"] = bool(trend_latest.get("ema_bullish", False))

        # 점수 계산 (가중치)
        weights = {
            "ema_bullish": 25,
            "rsi_in_range": 15,
            "above_bb_mid": 15,
            "volume_surge": 20,
            "above_vwap": 10,
            "trend_bullish": 15,
        }
        score = sum(weights[k] for k, v in conditions.items() if v)

        # 중복 신호 방지
        candle_time = str(df_main.index[-1])
        long_key = f"{pair}_long"
        last_time = self._last_signal_time.get(long_key, "")

        require_all_conditions = bool(
            self.cfg_trading.get("buy_require_all_conditions", True)
        )
        min_conditions = int(
            self.cfg_trading.get("buy_min_conditions", len(conditions))
        )
        min_score = float(self.cfg_trading.get("buy_min_score", 70))
        met_conditions_count = sum(1 for v in conditions.values() if v)
        all_conditions_met = all(conditions.values())
        conditions_ok = (
            all_conditions_met
            if require_all_conditions
            else (met_conditions_count >= min_conditions)
        )
        is_duplicate = candle_time == last_time

        if conditions_ok and score >= min_score and not is_duplicate:
            self._last_signal_time[long_key] = candle_time

            sl_pct = self.cfg_risk["stop_loss_pct"]
            tp_pct = self.cfg_risk["take_profit_pct"].get(pair, 0.01)
            stop_loss = close * (1 - sl_pct)
            take_profit = close * (1 + tp_pct)

            logger.info(
                f"🟢 [Signal] {pair} 롱 신호! "
                f"Score={score}, Price={close:,.2f}"
            )

            return Signal(
                pair=pair,
                signal_type="long",
                score=score,
                conditions=conditions,
                reason="롱 진입 조건 충족",
                timestamp=now_kst().isoformat(),
                price=close,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_side="long",
            )

        return Signal(
            pair=pair,
            signal_type="hold",
            score=score,
            conditions=conditions,
            reason=self._get_hold_reason(conditions, is_duplicate),
            timestamp=now_kst().isoformat(),
            price=close,
        )

    # ═══════════════════════════════════════════
    #  숏 신호 (롱 조건의 반대)
    # ═══════════════════════════════════════════

    def check_short_signal(
        self,
        pair: str,
        df_main: pd.DataFrame,     # 5분봉
        df_trend: pd.DataFrame,    # 1시간봉
    ) -> Signal:
        """
        숏 진입 신호 확인

        조건 (반대 로직):
          1. EMA 9 < EMA 21 (5분봉) — 데드크로스
          2. RSI > 65 (과매수 구간)
          3. 현재가 < 볼린저밴드 중간선
          4. 거래량 >= 20봉 평균 × 1.5 (급증)
          5. 현재가 < VWAP
          6. EMA 9 < EMA 21 (1시간봉, 큰 추세 하락)
        """
        latest = df_main.iloc[-1]
        trend_latest = df_trend.iloc[-1]

        conditions = {}

        # 조건 1: EMA 데드크로스 상태
        conditions["ema_bearish"] = not bool(latest.get("ema_bullish", True))

        # 조건 2: RSI 과매수 구간 (>65)
        rsi = latest.get("rsi", 50)
        conditions["rsi_overbought"] = rsi > 65 if pd.notna(rsi) else False

        # 조건 3: 현재가 < 볼린저 밴드 중간선
        close = latest.get("close", 0)
        bb_mid = latest.get("bb_mid", 0)
        conditions["below_bb_mid"] = close < bb_mid if pd.notna(bb_mid) else False

        # 조건 4: 거래량 급증
        conditions["volume_surge"] = bool(latest.get("vol_surge", False))

        # 조건 5: 현재가 < VWAP
        vwap = latest.get("vwap", 0)
        conditions["below_vwap"] = close < vwap if pd.notna(vwap) else False

        # 조건 6: 1시간봉 하락 추세
        conditions["trend_bearish"] = not bool(
            trend_latest.get("ema_bullish", True)
        )

        # 점수 계산 (가중치)
        weights = {
            "ema_bearish": 25,
            "rsi_overbought": 15,
            "below_bb_mid": 15,
            "volume_surge": 20,
            "below_vwap": 10,
            "trend_bearish": 15,
        }
        score = sum(weights[k] for k, v in conditions.items() if v)

        # 중복 신호 방지
        candle_time = str(df_main.index[-1])
        short_key = f"{pair}_short"
        last_time = self._last_signal_time.get(short_key, "")

        require_all_conditions = bool(
            self.cfg_trading.get("buy_require_all_conditions", True)
        )
        min_conditions = int(
            self.cfg_trading.get("buy_min_conditions", len(conditions))
        )
        min_score = float(self.cfg_trading.get("buy_min_score", 70))
        met_conditions_count = sum(1 for v in conditions.values() if v)
        all_conditions_met = all(conditions.values())
        conditions_ok = (
            all_conditions_met
            if require_all_conditions
            else (met_conditions_count >= min_conditions)
        )
        is_duplicate = candle_time == last_time

        if conditions_ok and score >= min_score and not is_duplicate:
            self._last_signal_time[short_key] = candle_time

            sl_pct = self.cfg_risk["stop_loss_pct"]
            tp_pct = self.cfg_risk["take_profit_pct"].get(pair, 0.01)
            # 숏은 방향이 반대
            stop_loss = close * (1 + sl_pct)
            take_profit = close * (1 - tp_pct)

            logger.info(
                f"🔴 [Signal] {pair} 숏 신호! "
                f"Score={score}, Price={close:,.2f}"
            )

            return Signal(
                pair=pair,
                signal_type="short",
                score=score,
                conditions=conditions,
                reason="숏 진입 조건 충족",
                timestamp=now_kst().isoformat(),
                price=close,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_side="short",
            )

        return Signal(
            pair=pair,
            signal_type="hold",
            score=score,
            conditions=conditions,
            reason=self._get_hold_reason(conditions, is_duplicate),
            timestamp=now_kst().isoformat(),
            price=close,
        )

    # ═══════════════════════════════════════════
    #  청산(Exit) 신호 (롱/숏 공통)
    # ═══════════════════════════════════════════

    def check_exit_signal(
        self,
        pair: str,
        df_main: pd.DataFrame,
        position: dict,
    ) -> Signal:
        """
        포지션 청산 신호 확인 (개선된 SL/TP 로직)
        """
        latest = df_main.iloc[-1]
        close = latest.get("close", 0)
        entry_price = position["entry_price"]
        position_side = position.get("position_side", "long")
        tp_stage = position.get("tp_stage_hit", 0)
        peak_price = position.get("peak_price", entry_price)

        if position_side == "long":
            pnl_pct = (close - entry_price) / entry_price
            # 고점 업데이트
            if close > peak_price:
                peak_price = close
        else:  # short
            pnl_pct = (entry_price - close) / entry_price
            # 저점 업데이트
            if close < peak_price:
                peak_price = close

        # 1. 손절(SL) 로직
        # 1-1. 고정 손절 (1.0%)
        sl_fixed_pct = 0.010
        if pnl_pct <= -sl_fixed_pct:
            return Signal(pair=pair, signal_type="exit", score=0.0, reason="SL", price=close, timestamp=now_kst().isoformat(), position_side=position_side)

        # 1-2. 동적 손절 (10캔들 기반, 최대 2.0% 캡)
        # 캡 가격 계산
        if position_side == "long":
            sl_cap_price = entry_price * 0.98
            recent_low = df_main["low"].iloc[-10:].min()
            # "캡"이라는 것은 손절선이 이 가격보다 더 아래로 내려가지 않음을 의미 (즉, max 로직)
            dynamic_sl = max(recent_low, sl_cap_price)
            if close < dynamic_sl:
                return Signal(pair=pair, signal_type="exit", score=0.0, reason="SL", price=close, timestamp=now_kst().isoformat(), position_side=position_side)
        else:
            sl_cap_price = entry_price * 1.02
            recent_high = df_main["high"].iloc[-10:].max()
            dynamic_sl = min(recent_high, sl_cap_price)
            if close > dynamic_sl:
                return Signal(pair=pair, signal_type="exit", score=0.0, reason="SL", price=close, timestamp=now_kst().isoformat(), position_side=position_side)

        # 2. 익절(TP) 로직 (다단계)
        # TP1: +0.8% (30%), TP2: +1.5% (30%), TP3: +2.5% (전량)
        if tp_stage < 1 and pnl_pct >= 0.008:
            return Signal(pair=pair, signal_type="exit", score=0.0, reason="TP1", price=close, quantity_pct=0.3, timestamp=now_kst().isoformat(), position_side=position_side)
        
        if tp_stage < 2 and pnl_pct >= 0.015:
            # TP1을 건너뛰고 바로 TP2로 올 수도 있으므로, 남은 수량의 적절한 비율을 계산해야 함.
            # 하지만 여기서는 단순화를 위해 "현재 수량의 30%를 추가로 턴다"는 개념으로 0.3 반환.
            # (MainController에서 처리 방식에 따라 다름)
            return Signal(pair=pair, signal_type="exit", score=0.0, reason="TP2", price=close, quantity_pct=0.3, timestamp=now_kst().isoformat(), position_side=position_side)
            
        if pnl_pct >= 0.025:
            return Signal(pair=pair, signal_type="exit", score=0.0, reason="TP3", price=close, quantity_pct=1.0, timestamp=now_kst().isoformat(), position_side=position_side)

        # 3. 트레일링 스톱 (TP1 이후 활성화, 고점 대비 0.4% 되돌림)
        if tp_stage >= 1:
            if position_side == "long":
                pullback = (peak_price - close) / peak_price
            else:
                pullback = (close - peak_price) / peak_price
                
            if pullback >= 0.004:
                return Signal(pair=pair, signal_type="exit", score=0.0, reason="Trailing", price=close, quantity_pct=1.0, timestamp=now_kst().isoformat(), position_side=position_side)

        # 4. EMA 크로스 청산 (미실현 손실 중일 때만)
        if pnl_pct < 0:
            ema_cross = latest.get("ema_cross", 0)
            if position_side == "long" and ema_cross == -1:
                return Signal(pair=pair, signal_type="exit", score=0.0, reason="EMA", price=close, timestamp=now_kst().isoformat(), position_side=position_side)
            elif position_side == "short" and ema_cross == 1:
                return Signal(pair=pair, signal_type="exit", score=0.0, reason="EMA", price=close, timestamp=now_kst().isoformat(), position_side=position_side)

        # 5. 시간 청산 (60분)
        from datetime import datetime
        entry_time = datetime.fromisoformat(position["entry_time"])
        hold_minutes = (now_kst() - entry_time).total_seconds() / 60
        max_hold = self.cfg_trading.get("max_hold_minutes", 60)

        if hold_minutes >= max_hold:
            if pnl_pct > 0:
                # 수익권이면 트레일링 스탑으로 전환 (이미 전환되었을 수도 있음)
                # 여기서는 별도 시그널 대신 관망을 리턴하여 루프에서 peak_price 업데이트를 계속하도록 함.
                pass
            else:
                return Signal(pair=pair, signal_type="exit", score=0.0, reason="Time", price=close, timestamp=now_kst().isoformat(), position_side=position_side)

        return Signal(
            pair=pair,
            signal_type="hold",
            score=0,
            reason="보유 유지",
            price=close,
            timestamp=now_kst().isoformat(),
            position_side=position_side,
        )

    # 레거시 호환
    def check_buy_signal(self, pair, df_main, df_trend):
        return self.check_long_signal(pair, df_main, df_trend)

    def check_sell_signal(self, pair, df_main, position):
        return self.check_exit_signal(pair, df_main, position)

    def _get_hold_reason(self, conditions: dict, is_duplicate: bool) -> str:
        """관망 사유 생성"""
        if is_duplicate:
            return "중복 신호 (같은 봉)"
        failed = [k for k, v in conditions.items() if not v]
        return f"미충족 조건: {', '.join(failed)}"
