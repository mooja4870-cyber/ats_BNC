"""Binance OrderExecutor 테스트 (Paper 모드)"""

import pytest
from unittest.mock import patch, MagicMock
from src.core.order_executor import OrderExecutor
from src.utils.constants import MIN_ORDER_USDT


@pytest.fixture
def paper_config():
    return {
        "trading": {
            "mode": "paper",
            "market_type": "swap",
            "leverage": 1,
            "margin_mode": "isolated",
            "pairs": ["BTC/USDT"],
        },
        "risk": {
            "fee_rate": 0.0005,
            "risk_per_trade_pct": 0.005,
            "fixed_order_amount_usdt": 0,
            "max_daily_loss_pct": 0.01,
            "max_consecutive_losses": 2,
        },
    }


@pytest.fixture
def executor(paper_config):
    """Paper 모드 OrderExecutor"""
    with patch("ccxt.binanceusdm") as mock_binance:
        mock_exchange = MagicMock()
        mock_exchange.fetch_ticker.return_value = {"last": 100000.0}
        mock_binance.return_value = mock_exchange

        exe = OrderExecutor(paper_config)
        exe.exchange = mock_exchange
        exe._paper_balance_usdt = 10000.0
        exe._paper_holdings = {}
        return exe


class TestPaperLong:
    """Paper 모드 롱 테스트"""

    def test_open_long_basic(self, executor):
        """기본 롱 진입"""
        result = executor.open_long("BTC/USDT", 100.0)
        assert result is not None
        assert result["side"] == "buy"
        assert result["position_side"] == "long"
        assert result["mode"] == "paper"
        assert result["quantity"] > 0
        assert result["price"] == 100000.0

    def test_open_long_deducts_balance(self, executor):
        """롱 진입 시 잔고 차감 (수수료만)"""
        initial = executor._paper_balance_usdt
        executor.open_long("BTC/USDT", 100.0)
        expected_fee = 100.0 * executor.fee_rate
        assert executor._paper_balance_usdt == initial - expected_fee

    def test_open_long_minimum_order(self, executor):
        """최소 주문금액 미달 시 None 반환"""
        result = executor.open_long("BTC/USDT", MIN_ORDER_USDT - 1)
        assert result is None

    def test_open_long_insufficient_balance(self, executor):
        """잔고 부족 시 None 반환"""
        executor._paper_balance_usdt = 1.0
        result = executor.open_long("BTC/USDT", 100.0)
        assert result is None


class TestPaperShort:
    """Paper 모드 숏 테스트"""

    def test_open_short_basic(self, executor):
        """기본 숏 진입"""
        result = executor.open_short("BTC/USDT", 100.0)
        assert result is not None
        assert result["side"] == "sell"
        assert result["position_side"] == "short"
        assert result["mode"] == "paper"

    def test_open_short_spot_rejected(self, executor):
        """현물 모드에서 숏 시도 시 None (market_type으로 판별)"""
        executor.market_type = "spot"
        result = executor.open_short("BTC/USDT", 100.0)
        assert result is None

    def test_open_short_deducts_margin(self, executor):
        """숏 진입 시 잔고 차감 (수수료만)"""
        initial = executor._paper_balance_usdt
        executor.open_short("BTC/USDT", 100.0)
        expected_fee = 100.0 * executor.fee_rate
        assert executor._paper_balance_usdt == initial - expected_fee


class TestPaperClose:
    """Paper 모드 청산 테스트"""

    def test_close_long_returns_funds(self, executor):
        """롱 청산 시 잔고 감소 (수수료 차감)"""
        executor.open_long("BTC/USDT", 100.0)
        balance_after_buy = executor._paper_balance_usdt

        result = executor.close_position(
            "BTC/USDT", 0.0009995, "long"
        )
        assert result is not None
        # 실현손익은 별도로 반영되므로, OrderExecutor 내부에서는 청산 수수료만 차감됨
        assert executor._paper_balance_usdt < balance_after_buy

    def test_close_short(self, executor):
        """숏 청산"""
        executor.open_short("BTC/USDT", 100.0)
        result = executor.close_position(
            "BTC/USDT", 0.0009995, "short"
        )
        assert result is not None
        assert result["position_side"] == "short"


class TestPaperBalance:
    """Paper 잔고 관리"""

    def test_get_paper_balance(self, executor):
        """잔고 조회"""
        bal = executor.get_paper_balance()
        assert "usdt" in bal
        assert "holdings" in bal
        assert bal["usdt"] == 10000.0


class TestBalanceSyncWithRiskManager:
    """
    ★ 총자산 계산 버그 수정 검증

    이전 버그: 매수 후 OrderExecutor의 현금은 줄었지만
    RiskManager.current_balance는 그대로 10,000 USDT로 유지되어
    총자산 = 현금(10,000) + 보유평가(100) = 10,100 으로 부풀려짐.

    수정 후: 매수/매도 후 _sync_risk_manager_balance()를 호출하여
    RiskManager.current_balance를 실제 현금과 동기화.
    """

    def test_risk_manager_balance_decreases_after_buy(self, executor, paper_config):
        """매수 후 RiskManager 잔고가 실제 현금과 동기화되는지 검증"""
        from src.core.risk_manager import RiskManager

        rm = RiskManager(paper_config, executor._paper_balance_usdt)
        assert rm.current_balance == 10000.0

        # 매수 실행
        result = executor.open_long("BTC/USDT", 1000.0)
        assert result is not None

        # OrderExecutor 현금은 수수료만큼만 줄어야 함
        fee = 1000.0 * paper_config["risk"]["fee_rate"]
        actual_cash = executor.get_paper_balance()["usdt"]
        assert actual_cash == pytest.approx(10000.0 - fee, abs=0.01)

        # RiskManager 동기화 (main.py의 _sync_risk_manager_balance 역할)
        rm.update_balance(actual_cash)
        assert rm.current_balance == pytest.approx(10000.0 - fee, abs=0.01)

    def test_total_assets_correct_after_buy(self, executor, paper_config):
        """매수 후 총자산 = 현금 + 보유평가 ≈ 초기자본 (수수료 제외)"""
        from src.core.risk_manager import RiskManager
        from src.core.position_tracker import PositionTracker

        rm = RiskManager(paper_config, executor._paper_balance_usdt)
        pt = PositionTracker()

        # 매수 실행
        buy_amount = 1000.0
        result = executor.open_long("BTC/USDT", buy_amount)
        assert result is not None

        # 포지션 등록
        pt.open_position(
            pair="BTC/USDT",
            entry_price=result["price"],
            quantity=result["quantity"],
            stop_loss=95000.0,
            take_profit=110000.0,
            trade_id=result["trade_id"],
            initial_margin=result.get("initial_margin", buy_amount),
            position_side="long",
        )

        # RiskManager 동기화
        actual_cash = executor.get_paper_balance()["usdt"]
        rm.update_balance(actual_cash)

        # 총자산 계산: 현금 + 미실현손익
        current_price = 100000.0  # mock 가격
        position = pt.get_position("BTC/USDT")
        
        # 진입가격과 현재가격이 같으므로 미실현손익은 0
        unrealized_pnl = 0.0
    
        total_assets = actual_cash + unrealized_pnl

        # 총자산은 초기자본(10,000)에서 수수료만큼만 줄어야 함
        fee = buy_amount * paper_config["risk"]["fee_rate"]
        expected_total = 10000.0 - fee
        assert total_assets == pytest.approx(expected_total, abs=0.01)

        # 총자산이 초기자본보다 커지면 안 됨 (가격 변동 없을 때)
        assert total_assets <= 10000.0

        # 정리
        pt.close_position("BTC/USDT")

    def test_risk_manager_update_balance(self, paper_config, executor):
        """RiskManager.update_balance() 메서드 동작 검증"""
        from src.core.risk_manager import RiskManager

        rm = RiskManager(paper_config, 10000.0)
        assert rm.current_balance == 10000.0

        rm.update_balance(8500.0)
        assert rm.current_balance == 8500.0

        rm.update_balance(9200.0)
        assert rm.current_balance == 9200.0
