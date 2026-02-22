# scripts/paper_trade.py
"""
종이거래 모드 실행 스크립트 (Binance)

실제 자금 없이 가상 매매를 시뮬레이션합니다.
최소 2주~1개월 테스트 후 실전 전환을 권장합니다.

실행:
    python scripts/paper_trade.py
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from src.main import MainController
from src.utils.helpers import load_config


def setup_paper_trade_logging():
    """종이거래 전용 로깅 설정"""
    log_path = PROJECT_ROOT / "data" / "logs" / "paper_trade_{time}.log"

    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    logger.add(
        str(log_path),
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )


def check_config():
    """설정 파일 검증"""
    config = load_config()

    if config["trading"]["mode"] != "paper":
        logger.error("❌ config/settings.yaml에서 trading.mode를 'paper'로 설정해주세요.")
        sys.exit(1)

    pairs = config["trading"]["pairs"]
    market_type = config["trading"].get("market_type", "swap")
    leverage = config["trading"].get("leverage", 1)

    logger.info(f"📊 거래 페어: {', '.join(pairs)}")
    logger.info(f"🏦 거래소: Binance ({market_type})")
    logger.info(f"⚡ 레버리지: {leverage}x")
    logger.info(f"⏱️  매매 간격: {config['trading']['loop_interval_seconds']}초")
    logger.info(f"💰 초기 가상 잔고: 10,000 USDT")
    logger.info(f"🎯 하루 최대 매매: 무제한")

    return config


def print_banner():
    """시작 배너 출력"""
    banner = """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║       📝 Binance 선물+현물 자동매매 - 종이거래 모드        ║
    ║                                                           ║
    ║   ⚠️  주의: 이 모드는 실제 거래를 하지 않습니다          ║
    ║   💡 최소 2주 이상 테스트 후 실전 모드로 전환하세요      ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)


async def run_paper_trade():
    """종이거래 실행"""
    print_banner()
    setup_paper_trade_logging()

    logger.info("🔍 설정 파일 검증 중...")
    config = check_config()

    logger.info("✅ 검증 완료! 종이거래를 시작합니다...")
    logger.info("⏸️  종료하려면 Ctrl+C를 누르세요\n")

    try:
        controller = MainController()
        await controller.run()
    except KeyboardInterrupt:
        logger.info("\n\n⏹️  사용자 종료 요청")
    except Exception as e:
        logger.error(f"❌ 예상치 못한 오류: {e}", exc_info=True)
    finally:
        logger.info("🏁 종이거래 종료")


if __name__ == "__main__":
    asyncio.run(run_paper_trade())
