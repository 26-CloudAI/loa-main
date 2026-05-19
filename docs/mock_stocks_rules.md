# MockStocks — 게임 룰

> 이 파일은 `src/stocks/config.py` / `engine.py` / `market.py` 의 수치와 항상 동기화한다.
> 룰 관련 코드를 수정하면 반드시 이 파일도 함께 수정할 것.

---

## 1. 게임 개요

| 항목 | 값 | 위치 |
|---|---|---|
| 게임 기간 | 200턴 (1턴 = 현실의 1영업일) | `GameConfig.total_ticks` |
| 틱 간격 | 0.1초 | `GameConfig.tick_interval` |
| 플레이 인원 | 최소 2명 ~ 최대 20명 | `GameConfig.min_bots / max_bots` |
| 초기 자본 | ₩100,000,000 (1억 원) | `GameConfig.starting_cash` |
| 초기 신용 점수 | 1,000점 | `CreditConfig.initial_score` |

---

## 2. 상장 종목 (15종)

모든 종목은 GBM으로 가격이 결정되며, 종목별 μ(기대수익률)와 σ(변동성)가 다르다.

| 심볼 | 이름 | 섹터 | 초기가 | μ (턴당) | σ (턴당) |
|---|---|---|---|---|---|
| NeoChips | 네오칩스 | 반도체 | 50,000 | 0.10% | 4.0% |
| CodeBase | 코드베이스 | 소프트웨어 | 80,000 | 0.20% | 2.0% |
| FusionGrid | 퓨전그리드 | 신재생에너지 | 35,000 | 0.10% | 2.5% |
| GenomX | 제놈엑스 | 바이오 | 120,000 | 0.20% | 5.0% |
| PlayVerse | 플레이버스 | 게임/메타버스 | 45,000 | 0.10% | 3.5% |
| VoltMotors | 볼트모터스 | 전기차 | 95,000 | 0.15% | 4.0% |
| EtherBank | 이더뱅크 | 금융 | 60,000 | 0.05% | 1.5% |
| TrendHub | 트렌드허브 | 이커머스 | 70,000 | 0.10% | 2.5% |
| OrbitalLink | 오비탈링크 | 우주항공 | 85,000 | 0.20% | 4.5% |
| GreenHarvest | 그린하베스트 | 농업/푸드테크 | 25,000 | 0.05% | 1.8% |
| QuantumLeap | 퀀텀리프 | 양자컴퓨팅 | 200,000 | 0.30% | 6.0% |
| DataMine | 데이터마인 | 빅데이터/AI | 65,000 | 0.20% | 3.0% |
| BlueWave | 블루웨이브 | 해운/물류 | 30,000 | 0.05% | 2.5% |
| SteelGuardian | 스틸가디언 | 철강/방산 | 40,000 | 0.05% | 2.2% |
| CoreREITs | 코어리츠 | 부동산 | 55,000 | 0.05% | 1.2% |

실제 시작가 = 초기가 × 랜덤(0.9 ~ 1.1) — 종목마다 다름

---

## 3. 주가 변동 로직

**기하 브라운 운동 (GBM):**
```
다음 가격 = 현재 가격 × (1 + μ_effective + σ × N(0,1))
μ_effective = 기본 μ + 뉴스 효과 δμ (뉴스 없으면 0)
최저 가격 하한: 1원
```

**뉴스 이벤트:**

| 항목 | 값 | 위치 |
|---|---|---|
| 발생 간격 | 10 ~ 20턴마다 랜덤 | `NewsConfig.interval_min/max` |
| 효과 지속 | 5 ~ 10턴 | `NewsConfig.effect_duration_min/max` |
| δμ 범위 | ±0.5% ~ ±1.5% | `NewsConfig.delta_mu_min/max` |

---

## 4. 플레이어 행동 (1턴 1행동)

| 행동 | 형식 | 설명 |
|---|---|---|
| 매수 | `{"action": "BUY", "symbol": "NeoChips", "quantity": 10}` | 현재가 즉시 체결. 보유 현금 범위 내. |
| 매도 | `{"action": "SELL", "symbol": "NeoChips", "quantity": 5}` | 보유 수량 범위 내. |
| 공매도 | `{"action": "SHORT", "symbol": "NeoChips", "quantity": 10}` | 신용점수 800 이상 + 총 자산 50% 한도. |
| 공매도 청산 | `{"action": "COVER", "symbol": "NeoChips", "quantity": 10}` | 빌린 주식 상환. |
| 정보 탐색 | `{"action": "INQUIRY"}` | 다음 턴 state에 뉴스 힌트 제공. |
| 대기 | `{"action": "HOLD"}` | 보유 현금에 0.01%/턴 이자 지급. |

---

## 5. 거래 세부 규칙

| 규칙 | 내용 | 위치 |
|---|---|---|
| 기본 수수료 | 0.15% (매수·매도·공매도·청산 모두) | `CreditConfig.fee_standard` |
| 최저 수수료 | 0.10% (신용점수 1,200 이상) | `CreditConfig.fee_minimum / fee_min_score` |
| 체결 방식 | 해당 턴 확정가로 즉시 전량 체결 | `engine.py` |
| 공매도 조건 | 신용점수 ≥ 800, 총 자산의 최대 50% | `CreditConfig.short_min_score / short_max_asset_ratio` |
| 공매도 증거금 | 공매도 금액의 50% 선납 | `engine.py — _execute_short` |
| 현금 이자 | HOLD 시 0.01%/턴 | `GameConfig.cash_interest_rate` |

---

## 6. 신용 점수 시스템

| 상황 | 변화 |
|---|---|
| 매도/청산 시 수익 발생 | 수익률 1%당 +1점 (최대 +5점/거래) |
| 매도/청산 시 손실 발생 | 손실률 1%당 -1점 (최대 -5점/거래) |
| 공매도 가능 기준 | 신용점수 ≥ 800 |
| 수수료 우대 기준 | 신용점수 ≥ 1,200 → 0.10% 최저 수수료 |

---

## 7. 상장 폐지

| 조건 | 내용 | 위치 |
|---|---|---|
| 경고 기준 | 현재가 < 초기가 × 5% | `GameConfig.delisting_threshold` |
| 폐지 조건 | 경고 상태 5턴 연속 유지 | `GameConfig.delisting_ticks` |
| 폐지 효과 | 보유 주식 0원 처리, 공매도 증거금 반환 | `engine.py — _handle_delisted_positions` |

---

## 8. 봇이 받는 정보 (state)

```python
state = {
    "tick": int,                         # 현재 턴 (1~200)
    "my_bot": {
        "id": str,
        "cash": float,                   # 보유 현금
        "credit_score": int,             # 신용 점수
        "total_value": float,            # 현금 + 주식 평가액 + 공매도 손익
        "portfolio": {                   # 보유 주식 (롱 포지션)
            symbol: {
                "quantity": int,
                "avg_cost": float,       # 평균 매수 단가
                "current_price": float,
                "unrealized_pnl": float, # 평가 손익
                "pnl_pct": float,        # 수익률 (%)
                "value": float,          # 평가 금액
            }
        },
        "short_positions": {            # 공매도 포지션
            symbol: {
                "quantity": int,
                "avg_sell_price": float,
                "current_price": float,
                "unrealized_pnl": float,
                "margin": float,
            }
        },
        "inquiry_hint": str,            # INQUIRY 사용 시 다음 틱에 제공
    },
    "market": {
        "stocks": [
            {
                "symbol": str,
                "name": str,
                "sector": str,
                "price": float,
                "initial_price": float,
                "price_history": [float],  # 최근 10턴
                "change_pct": float,       # 직전 턴 대비 변동률 (%)
                "delisted": bool,
            }
        ],
        "news": [
            {
                "symbol": str,
                "headline": str,
                "ticks_remaining": int,
            }
        ],
    },
    "leaderboard": [
        {"rank": int, "id": str, "total_value": float, "credit_score": int}
    ],
}
```

---

## 9. 승리 조건

200턴 종료 후 **총 자산 (현금 + 주식 평가액 + 공매도 미실현 손익)** 이 가장 높은 봇이 우승.

---

## 10. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-04-28 | 최초 작성 (8종목, 기본 BUY/SELL/HOLD) |
| 2026-04-28 | 전면 개편 — 15종목, 공매도/INQUIRY/신용점수/상장폐지/뉴스이벤트 추가 |
