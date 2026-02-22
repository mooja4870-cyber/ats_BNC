# 🔑 Binance API 키 설정 가이드

## 1. API 키 발급

### 현물/선물 실거래 API 키

1. [Binance](https://www.binance.com) 로그인
2. **프로필** → **API 관리** 이동
3. **API 키 생성** 클릭 (라벨 입력)
4. 2FA 인증 완료

### 권한 설정 (중요!)

✅ 체크할 항목:
- **읽기(Read)** — 잔고/포지션 조회용
- **선물 거래(Enable Futures)** — 선물 주문 실행용
- **현물 거래(Enable Spot & Margin Trading)** — 현물 주문용

❌ **절대 체크하지 않을 항목:**
- ~~출금(Enable Withdrawals)~~ — 보안상 절대 불필요

### IP 허용목록

Binance API 키는 **IP 제한 설정을 강력히 권장**합니다:
- 로컬 개발: 공인 IP
- 클라우드: 서버 공인 IP
- "제한 없음" 선택 시 보안 위험

---

### Testnet(데모) API 키 (선택)

Binance는 별도 테스트넷을 제공합니다:

- **선물 Testnet**: https://testnet.binancefuture.com
- **현물 Testnet**: https://testnet.binance.vision

1. 위 사이트에서 GitHub 계정으로 로그인
2. **API Keys** 탭에서 키 생성
3. `.env`의 `BINANCE_TESTNET_*` 키에 입력

> ⚠️ Testnet은 실 계정과 별도이며, 가상 자금으로 테스트합니다.

## 2. .env 파일 설정

```bash
# 프로젝트 루트에서
cp .env.example .env
```

`.env` 파일 편집:
```
BINANCE_API_KEY=발급받은_API_Key
BINANCE_SECRET_KEY=발급받은_Secret_Key

# Demo(Testnet) 모드 사용 시 (선택)
BINANCE_TESTNET_API_KEY=Testnet_API_Key
BINANCE_TESTNET_SECRET_KEY=Testnet_Secret_Key
```

> Binance는 OKX와 달리 **Passphrase가 없습니다** (apiKey + secret만 사용).

## 3. 연결 테스트

### 현물 테스트
```bash
python -c "
import ccxt
exchange = ccxt.binance({
    'apiKey': 'YOUR_API_KEY',
    'secret': 'YOUR_SECRET_KEY',
})
print(exchange.fetch_balance())
"
```

### 선물 테스트
```bash
python -c "
import ccxt
exchange = ccxt.binanceusdm({
    'apiKey': 'YOUR_API_KEY',
    'secret': 'YOUR_SECRET_KEY',
})
print(exchange.fetch_balance())
"
```

## 4. 실행 방법

### Paper 모드 (시세만 조회, API 키 불필요)
```bash
# config/settings.yaml에서 mode: paper 설정 후
python -m src.main
```

### Live 모드 (실거래)
```bash
# config/settings.yaml에서 mode: live 설정 후
# .env에 BINANCE_API_KEY, BINANCE_SECRET_KEY 입력 후
python -m src.main
```

### Demo 모드 (Testnet)
```bash
# config/settings.yaml에서 mode: demo 설정 후
# .env에 BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_SECRET_KEY 입력 후
python -m src.main
```

### 선물 vs 현물
```yaml
# config/settings.yaml
trading:
  market_type: "swap"    # 선물 (USDT-M)
  # market_type: "spot"  # 현물
```

## 5. 주의사항

- API 키는 **절대** 코드에 직접 입력하지 마세요
- `.env` 파일은 `.gitignore`에 반드시 포함
- 주기적으로 키를 갱신하세요
- Binance API Rate Limit: 가중치 기반 (분당 1200 가중치)
- **선물 거래는 원금 이상의 손실이 발생할 수 있습니다**
- Binance 선물은 Hedge Mode(양방향) 설정 시 Long/Short을 동시에 보유할 수 있습니다
