# 🤖 ATS_BNC — Binance 선물/현물 자동매매 봇

Binance 거래소 기반의 암호화폐 자동매매 시스템입니다.  
기술적 지표(EMA, RSI, 볼린저밴드, VWAP, 거래량)를 활용한 다중 조건 스코어링 전략으로 매매합니다.

---

## 📁 프로젝트 구조

```
ATS_BNC/
├── config/                  # 설정 파일
│   ├── settings.yaml        # 메인 설정 (모드, 페어, 지표, 리스크 등)
│   ├── pairs.yaml           # 거래 페어 상세 설정
│   └── risk.yaml            # 리스크 관리 설정
├── src/                     # 소스 코드
│   ├── main.py              # 메인 컨트롤러
│   ├── core/                # 핵심 모듈
│   │   ├── data_fetcher.py  # OHLCV 데이터 수집
│   │   ├── indicators.py    # 기술적 지표 계산
│   │   ├── signal_engine.py # 매매 신호 생성
│   │   ├── order_executor.py# 주문 실행
│   │   ├── position_tracker.py # 포지션 관리
│   │   └── risk_manager.py  # 리스크 관리
│   ├── database/            # DB 관련
│   │   ├── models.py        # 데이터 모델
│   │   └── trade_logger.py  # 거래 기록
│   ├── notifications/       # 알림
│   │   └── discord_notifier.py # 디스코드 알림
│   ├── analysis/            # 분석
│   │   ├── backtester.py    # 백테스트
│   │   └── performance.py   # 성과 분석
│   └── utils/               # 유틸리티
│       ├── constants.py     # 상수
│       └── helpers.py       # 헬퍼 함수
├── scripts/                 # 실행 스크립트
│   ├── paper_trade.py       # 종이거래 실행
│   ├── live_trade.py        # 실전 거래 실행
│   ├── backtest_run.py      # 백테스트 실행
│   └── analyze_performance.py # 성과 분석
├── tests/                   # 테스트
├── data/                    # 데이터 (로그, 상태 파일)
├── docs/                    # 문서
│   ├── API_SETUP.md         # Binance API 설정 가이드
│   ├── DISCORD_SETUP.md     # 디스코드 알림 설정
│   └── STRATEGY.md          # 매매 전략 상세
├── .env                     # 환경변수 (API 키 등, git 미포함)
├── .env.example             # 환경변수 예시
└── requirements.txt         # Python 패키지
```

---

## ⚡ 빠른 시작

### 1. 환경 설정

```bash
# 패키지 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일에 Binance API 키, Discord Webhook URL 입력
```

### 2. 설정 확인

`config/settings.yaml`에서 거래 모드, 페어, 리스크 등을 설정합니다.

### 3. 종이거래 (권장: 최소 2주 테스트)

```bash
python scripts/paper_trade.py
```

### 4. 실전 거래

```bash
# settings.yaml에서 mode: "live"로 변경 후
python scripts/live_trade.py
```

---

## 📊 매매 전략 요약

| 지표 | 설정 | 용도 |
|------|------|------|
| EMA 9/21 | 5분봉 | 추세 방향 및 반전 감지 |
| RSI 14 | 5분봉 | 진입 강도 필터링 |
| 볼린저밴드 | 20, 2σ | 변동성 및 중심선 필터 |
| ATR 14 | 5분봉 | **동적 포지션 사이징** |
| VWAP | 당일 | 당일 평균가 필터 |

**진입**: 다중 조건 스코어링 (100점 만점, 설정 점수 이상 시 진입)  
**청산 (개선됨)**:
- **다단계 익절**: TP1(+0.8%, 30%), TP2(+1.5%, 30%), TP3(+2.5%, 전량)
- **트레일링 스탑**: 고점 대비 0.4% 되돌림 시 수익 보존 청산
- **손절**: 고정 1.0% + 동적 저점 이탈(최대 2.0% 캡)
- **추세/시간**: EMA 조건부 청산 및 60분 시간 초과 청산

자세한 전략은 [docs/STRATEGY.md](docs/STRATEGY.md)를 참고하세요.

---

## 🛡️ 리스크 관리 (개선됨)

- **포지션 비중**: 티커당 총자산의 **3% 마진** 투입 (ATR에 따라 가변)
- **마진 한도**: 총 사용 마진 **20% 이내** 제한 (안전 마진 확보)
- **유동성 보호**: 가용 잔고 **50% 미만** 시 신규 진입 금지
- **일일 최대 손실**: 총자산의 7% 도달 시 당일 모든 거래 정지
- **연속 패배 중단**: 5연패 시 당일 종료

---

## 🔔 디스코드 알림

매매 신호, 체결, 손익, 일일 리포트 등을 디스코드로 실시간 알림받습니다.  
설정 방법: [docs/DISCORD_SETUP.md](docs/DISCORD_SETUP.md)

---

## 📌 거래 페어

| 페어 | 마켓 | 레버리지 |
|------|------|----------|
| BTC/USDT | 선물 (USDT-M) | 10x |
| ETH/USDT | 선물 (USDT-M) | 10x |
| XRP/USDT | 선물 (USDT-M) | 10x |
| SOL/USDT | 선물 (USDT-M) | 10x |

---

## ⚙️ 운영 및 동기화 기준 (Operational Standards)

본 봇은 거래소와 내부 데이터베이스간의 **엄격한 동기화(Strict Sync)**를 원칙으로 합니다.

### 1. 시스템 초기화 프로토콜 (5-Step Reset)
초기화 실행 시 다음 과정을 순서대로 강제 수행합니다:
1. **포지션 조회**: 거래소의 모든 활성 포지션을 조회합니다.
2. **전량 청산**: 발견된 모든 포지션을 시장가로 즉시 청산합니다.
3. **미체결 취소**: 모든 미체결 주문(Open Orders)을 취소합니다.
4. **데이터 리셋**: 내부 DB, 거래 이력, 잔고 스냅샷, 누적 손익을 모두 초기화합니다.
5. **통지**: 초기화 상세 내역을 디스코드 시스템 채널로 전송합니다.

### 2. 포지션 관리 원칙
- **Managed Only**: 봇이 직접 진입 신호를 발생시키고 알림을 보낸 포지션만 유효합니다.
- **Auto-Liquidation**: 봇 DB에 없는 '미관리(Ghost) 포지션'이 거래소에서 감지되면 **즉시 시장가 청산** 처리합니다.
- **Sync Check**: 매 10초 사이클마다 거래소 실시간 포지션과 봇 DB를 교차 검증합니다.

### 3. 잔고 리포트 기준
- 모든 잔고 스냅샷은 거래소의 실제 잔고와 무관하게 **봇 DB가 관리하는 자산 상태**만을 기준으로 작성됩니다.
- 미관리 포지션은 총자산 및 종목 현황 계산에서 제외됩니다 (발견 즉시 청산 대상).

---

## ⚠️ 면책 조항

- 이 봇은 교육 및 연구 목적으로 제작되었습니다.
- **선물 거래는 원금 이상의 손실이 발생할 수 있습니다.**
- 투자의 모든 책임은 사용자 본인에게 있습니다.
- 반드시 종이거래로 충분히 테스트한 후 소액으로 시작하세요.
