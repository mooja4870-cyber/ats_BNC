import asyncio
import sys
import sqlite3
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from src.utils.helpers import load_config, create_exchange, normalize_symbol
from src.notifications.discord_notifier import DiscordNotifier
from src.database.models import init_database

async def reset_system():
    config = load_config()
    notifier = DiscordNotifier(config)
    market_type = config["trading"].get("market_type", "swap")
    
    exchange = None
    try:
        exchange = create_exchange("binance", "demo", market_type=market_type)
    except Exception as e:
        logger.warning(f"Demo exchange 접속 실패 (API Key 없음 등). 로컬 파일(Paper) 상태만 리셋합니다: {e}")

    closed_pos_count = 0
    canceled_orders_count = 0

    if exchange is not None:
        # 1/2 단계: 포지션 및 주문 검사/청산
        positions = []
        try:
            positions = exchange.fetch_positions()
        except Exception as e:
            logger.error(f"fetch_positions 실패: {e}")

        for pos in positions:
            contracts = float(pos.get("contracts", 0))
            if contracts > 0:
                sym = pos["symbol"]
                posSide = pos.get("side", "")
                # 청산 방향 설정
                if posSide == "long":
                    side = "sell"
                elif posSide == "short":
                    side = "buy"
                else:
                    side = "sell" # fallback
                    
                try:
                    params = {"positionSide": posSide.upper()} if posSide else {}
                    exchange.create_market_order(
                        sym, 
                        side, 
                        contracts, 
                        params=params
                    )
                    closed_pos_count += 1
                    logger.info(f"{sym} 포지션 청산 완료")
                except Exception as e:
                    logger.error(f"{sym} 포지션 청산 실패: {e}")

        # 3 단계: 미체결 주문 취소
        pairs = config.get("trading", {}).get("pairs", [])
        for pair in pairs:
            symbol = normalize_symbol(pair, market_type)
            try:
                open_orders = exchange.fetch_open_orders(symbol)
                if open_orders:
                    exchange.cancel_all_orders(symbol)
                    canceled_orders_count += len(open_orders)
                    logger.info(f"{symbol} 미체결 주문 {len(open_orders)}건 취소 완료")
            except Exception as e:
                logger.debug(f"{symbol} 오픈 주문 조회 오류(또는 주문없음): {e}")

    # 4 단계: DB 리셋
    db_path = PROJECT_ROOT / "data" / "trades.db"
    if db_path.exists():
        open_positions_path = PROJECT_ROOT / "data" / "open_positions.json"
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("DELETE FROM trades")
            cur.execute("DELETE FROM daily_stats")
            try:
                cur.execute("DELETE FROM signals")
            except:
                pass
            conn.commit()
            conn.close()
            logger.info("trades.db 데이터 초기화 완료")
        except Exception as e:
            logger.error(f"DB 초기화 실패: {e}")
            
        if open_positions_path.exists():
            open_positions_path.write_text("{}", encoding="utf-8")
            
    # Paper mode json reset
    paper_path = PROJECT_ROOT / "data" / "paper_state.json"
    paper_path.parent.mkdir(parents=True, exist_ok=True)
    paper_path.write_text('{"usdt": 10000.0, "holdings": {}}', encoding="utf-8")
    
    # 5 단계: 디스코드 푸시
    msg_lines = [
        "⚙️ [초기화 완료]",
        f"• 기존 포지션 청산: {closed_pos_count}건",
        f"• 미체결 주문 취소: {canceled_orders_count}건",
        "• 내부 DB 리셋: 완료",
        "• 잔고 스냅샷 리셋: 완료",
        "• 시작 잔고: 10,000.00 USDT"
    ]
    embed = {
        "description": "\n".join(msg_lines),
        "color": notifier.colors.get("system", 0x808080),
    }
    await notifier._send_webhook(notifier.webhook_system, embed)
    logger.info("모든 초기화 작업 완료.")

if __name__ == "__main__":
    asyncio.run(reset_system())
