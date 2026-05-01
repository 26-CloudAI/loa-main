"""
ShortTraderBot — 단기 공매도 + 모멘텀 봇

전략:
  1. 공매도: 최근 5턴 누적 상승률이 높은 종목을 공매도 (평균 회귀 노린다)
     - 목표 수익: +6% 도달 시 청산
     - 손절선: -10% 초과 손실 시 강제 청산
  2. 모멘텀 매수: 최근 3턴 연속 상승 종목을 단기 매수 후 다음 틱에 매도
  3. 뉴스 악재 종목 공매도 추가 진입
  4. 15턴마다 INQUIRY로 정보 수집
"""

from src.stocks.bot_interface import BotInterface

_SHORT_TRIGGER   = 0.10   # 5턴 누적 +10% 이상이면 공매도 진입
_SHORT_TAKE      = 0.06   # 공매도 수익 +6% 청산
_SHORT_STOP      = -0.10  # 공매도 손실 -10% 강제 청산
_MOMENTUM_TICKS  = 3      # 연속 상승 판정 틱 수
_MOMENTUM_SELL_AFTER = 2  # 모멘텀 매수 후 N턴 뒤 매도
_MAX_SHORT_POSITIONS = 3  # 동시 공매도 포지션 최대 수


def _is_bearish_news(headline: str) -> bool:
    keywords = ["부진", "사임", "조사", "부정", "이탈", "감소", "악화"]
    return any(k in headline for k in keywords)


def _cumulative_return(history: list[float], n: int) -> float:
    if len(history) < n + 1:
        return 0.0
    start = history[-(n + 1)]
    end   = history[-1]
    return (end - start) / start if start > 0 else 0.0


def _consecutive_up(history: list[float], n: int) -> bool:
    if len(history) < n + 1:
        return False
    return all(history[-i] > history[-i - 1] for i in range(1, n + 1))


class ShortTraderBot(BotInterface):

    def __init__(self, bot_id: str, **kwargs):
        super().__init__(bot_id)
        self._momentum_bought: dict[str, int] = {}  # symbol → 매수한 턴
        self._inquiry_done: set[int] = set()

    def get_action(self, state: dict) -> dict:
        tick      = state["tick"]
        my        = state["my_bot"]
        cash      = my["cash"]
        total     = my["total_value"]
        credit    = my["credit_score"]
        portfolio  = my["portfolio"]
        shorts     = my["short_positions"]
        news      = state["market"]["news"]
        stocks    = {s["symbol"]: s for s in state["market"]["stocks"]}

        # ── 1. 공매도 청산 (익절 / 손절) ────────────────────────────────────
        for sym, pos in shorts.items():
            pnl_pct = pos["unrealized_pnl"] / (pos["avg_sell_price"] * pos["quantity"]) if pos["quantity"] else 0
            if pnl_pct >= _SHORT_TAKE or pnl_pct <= _SHORT_STOP:
                return {"action": "COVER", "symbol": sym, "quantity": pos["quantity"]}

        # ── 2. 모멘텀 포지션 매도 (N턴 경과) ────────────────────────────────
        to_sell = [sym for sym, bought_tick in self._momentum_bought.items()
                   if tick - bought_tick >= _MOMENTUM_SELL_AFTER and sym in portfolio]
        if to_sell:
            sym = to_sell[0]
            self._momentum_bought.pop(sym, None)
            qty = portfolio[sym]["quantity"]
            if qty > 0:
                return {"action": "SELL", "symbol": sym, "quantity": qty}

        # ── 3. 뉴스 악재 공매도 ──────────────────────────────────────────────
        if credit >= 800 and len(shorts) < _MAX_SHORT_POSITIONS:
            bearish_syms = {n["symbol"] for n in news if _is_bearish_news(n["headline"])}
            for sym in bearish_syms:
                stock = stocks.get(sym, {})
                if stock.get("delisted") or sym in shorts:
                    continue
                price     = stock["price"]
                max_short = total * 0.15  # 악재 공매도 1회 최대 15%
                qty       = int(max_short / (price * 1.0015))
                margin    = price * qty * 0.5
                if qty > 0 and cash >= margin:
                    return {"action": "SHORT", "symbol": sym, "quantity": qty}

        # ── 4. 급등 종목 공매도 (평균 회귀) ──────────────────────────────────
        if credit >= 800 and len(shorts) < _MAX_SHORT_POSITIONS:
            candidates = []
            for sym, stock in stocks.items():
                if stock.get("delisted") or sym in shorts:
                    continue
                hist  = stock["price_history"]
                ret5  = _cumulative_return(hist, 5)
                if ret5 >= _SHORT_TRIGGER:
                    candidates.append((sym, ret5, stock["price"]))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                sym, _, price = candidates[0]
                max_short = total * 0.20
                qty    = int(max_short / (price * 1.0015))
                margin = price * qty * 0.5
                if qty > 0 and cash >= margin:
                    return {"action": "SHORT", "symbol": sym, "quantity": qty}

        # ── 5. 모멘텀 매수 (연속 상승 종목 단기 추종) ────────────────────────
        if sym not in self._momentum_bought:
            for sym, stock in stocks.items():
                if stock.get("delisted") or sym in portfolio or sym in shorts:
                    continue
                hist = stock["price_history"]
                if _consecutive_up(hist, _MOMENTUM_TICKS):
                    price  = stock["price"]
                    invest = min(cash * 0.15, total * 0.10)
                    qty    = int(invest / (price * 1.0015))
                    if qty > 0 and cash >= price * qty * 1.0015:
                        self._momentum_bought[sym] = tick
                        return {"action": "BUY", "symbol": sym, "quantity": qty}

        # ── 6. INQUIRY (15턴마다) ─────────────────────────────────────────────
        if tick % 15 == 0 and tick not in self._inquiry_done:
            self._inquiry_done.add(tick)
            return {"action": "INQUIRY"}

        return {"action": "HOLD"}
