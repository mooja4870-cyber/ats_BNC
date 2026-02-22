
import asyncio
import sys
import os
import json
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from src.utils.helpers import load_config, create_exchange, normalize_symbol
from src.core.order_executor import OrderExecutor
from src.notifications.discord_notifier import DiscordNotifier
from src.database.models import init_database
from src.utils.constants import TradeMode

async def system_reset():
    logger.info("═══ [시스템 초기화 및 포지션 관리 지침] 기반 리셋 시작 ═══")
    
    # 1. 설정 로드
    config = load_config()
    mode_str = config["trading"]["mode"]
    mode = TradeMode(mode_str)
    initial_capital = config["risk"].get("initial_capital", 10000.0)
    market_type = config["trading"].get("market_type", "swap")
    
    # 2. 거래소 연결
    exchange = create_exchange("binance", mode_str, market_type=market_type)
    order_executor = OrderExecutor(config, exchange)
    
    closed_pos_count = 0
    cancelled_orders_count = 0
    
    # Step 1 & 2: 포지션 조회 및 청산
    logger.info(f"Step 1 & 2: {mode_str.upper()} 거래소 포지션 조회 및 청산 중...")
    if mode in (TradeMode.LIVE, TradeMode.DEMO):
        try:
            positions = exchange.fetch_positions()
            for pos in positions:
                contracts = float(pos.get('contracts', 0))
                if contracts > 0:
                    symbol = pos['symbol']
                    side = "long" if pos['side'] == 'long' else "short"
                    logger.info(f"⚠️ 미청산 포지션 발견: {symbol} ({side}) {contracts}개")
                    order_executor.close_position(symbol, contracts, side)
                    closed_pos_count += 1
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"거래소 포지션 청산 중 오류: {e}")
    else:
        # Paper 모드
        state = order_executor.get_paper_balance()
        holdings = state.get("holdings", {})
        for symbol_base, qty in list(holdings.items()):
            if qty > 0:
                pair = f"{symbol_base}/USDT" if "SHORT_" not in symbol_base else f"{symbol_base.replace('SHORT_', '')}/USDT"
                p_side = "short" if "SHORT_" in symbol_base else "long"
                logger.info(f"⚠️ Paper 미청산 포지션 발견: {symbol_base} {qty}개")
                order_executor.close_position(pair, qty, p_side)
                closed_pos_count += 1

    # Step 3: 미체결 주문 취소
    logger.info("Step 3: 미체결 주문 취소 중...")
    if mode in (TradeMode.LIVE, TradeMode.DEMO):
        try:
            pairs = config["trading"].get("pairs", [])
            for pair in pairs:
                symbol = normalize_symbol(pair, market_type)
                order_executor.cancel_all_orders(symbol)
                cancelled_orders_count += 1
        except Exception as e:
            logger.error(f"미체결 주문 취소 중 오류: {e}")
    else:
        cancelled_orders_count = 0

    # Step 4: 내부 데이터 초기화
    logger.info("Step 4: 내부 DB 및 상태 파일 초기화 중...")
    
    # paper_state.json 리셋
    with open(PROJECT_ROOT / "data" / "paper_state.json", "w") as f:
        json.dump({"usdt": initial_capital, "holdings": {}}, f)
        
    # open_positions.json 리셋
    with open(PROJECT_ROOT / "data" / "open_positions.json", "w") as f:
        json.dump({}, f)
        
    # trades.db 리셋 (테이블 스키마 재생성 포함)
    db_path = PROJECT_ROOT / "data" / "trades.db"
    if db_path.exists():
        os.remove(db_path)
    init_database()

    # Step 5: 디스코드 알림
    logger.info("Step 5: 초기화 완료 알림 전송 중...")
    try:
        notifier = DiscordNotifier(config)
        msg = (
            f"⚙️ **[초기화 완료]**\n"
            f"• 기존 포지션 청산: {closed_pos_count}건\n"
            f"• 미체결 주문 취소: {cancelled_orders_count}건\n"
            f"• 내부 DB 리셋: 완료\n"
            f"• 잔고 스냅샷 리셋: 완료\n"
            f"• 시작 잔고: {initial_capital:,.2f} USDT"
        )
        await notifier._send_webhook(notifier.webhook_system, {"description": msg, "color": notifier.colors["system"]})
        await notifier.close()
    except Exception as e:
        logger.warning(f"디스코드 알림 실패: {e}")

    logger.info("═══ [시스템 초기화] 완료 ═══")

if __name__ == "__main__":
    asyncio.run(system_reset())
