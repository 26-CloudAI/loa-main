"""
LongTermBot — 장기 성장형 봇

전략:
  1. 저변동성·안정 성장 종목 5개에 자산 분산 (종목당 목표 비중 15%)
  2. 목표 비중 미달 시 분할 매수, 비중 초과 시 차익 실현
  3. 손절선 -20% 이하 자동 매도
  4. 현재 뉴스에 호재 종목이 포함되면 추가 매수
  5. 할 행동이 없으면 HOLD (0.01%/턴 현금 이자 수령)
  6. 20턴마다 INQUIRY로 다음 뉴스 힌트 수집
"""

from src.stocks.bot_interface import BotInterface


# 안정 성장 타깃 종목 (낮은 σ, 양의 μ)
_TARGETS = ["CodeBase", "EtherBank", "GreenHarvest", "CoreREITs", "TrendHub"]
_ALLOC_RATIO  = 0.15   # 종목당 목표 비중
_REBAL_BAND   = 0.05   # 목표 대비 ±5% 벗어나면 리밸런싱
_STOP_LOSS    = -0.20  # -20% 손절
_TAKE_PROFIT  = 0.35   # +35% 차익 실현
_BUY_CHUNK    = 0.30   # 1회 매수에 사용 가능한 현금 비율 상한


def _is_bullish_news(headline: str) -> bool:
    keywords = ["계약", "실적", "자사주", "파트너십", "출시", "상회"]
    return any(k in headline for k in keywords)


class LongTermBot(BotInterface):

    def __init__(self, bot_id: str, **kwargs):
        super().__init__(bot_id)
        self._inquiry_done: set[int] = set()  # INQUIRY 사용한 턴

    def get_action(self, state: dict) -> dict:
        tick     = state["tick"]
        my       = state["my_bot"]
        cash     = my["cash"]
        total    = my["total_value"]
        portfolio = my["portfolio"]
        news     = state["market"]["news"]
        stocks   = {s["symbol"]: s for s in state["market"]["stocks"]}

        # ── 1. 손절 / 차익 실현 ─────────────────────────────────────────────
        for sym, pos in portfolio.items():
            pnl_pct = pos["pnl_pct"]
            if pnl_pct <= _STOP_LOSS * 100 or pnl_pct >= _TAKE_PROFIT * 100:
                return {"action": "SELL", "symbol": sym, "quantity": pos["quantity"]}

        # ── 2. 뉴스 호재 종목 추가 매수 ─────────────────────────────────────
        bullish_syms = {n["symbol"] for n in news if _is_bullish_news(n["headline"])}
        for sym in bullish_syms:
            if sym not in _TARGETS or stocks.get(sym, {}).get("delisted"):
                continue
            price = stocks[sym]["price"]
            invest = min(cash * 0.10, total * 0.05)  # 최대 5%씩 추가
            qty = int(invest / (price * 1.0015))
            if qty > 0 and cash >= price * qty * 1.0015:
                return {"action": "BUY", "symbol": sym, "quantity": qty}

        # ── 3. 목표 비중 미달 → 분할 매수 ───────────────────────────────────
        for sym in _TARGETS:
            if stocks.get(sym, {}).get("delisted"):
                continue
            target_val = total * _ALLOC_RATIO
            cur_val    = portfolio.get(sym, {}).get("value", 0)
            if cur_val < target_val * (1 - _REBAL_BAND):
                price   = stocks[sym]["price"]
                invest  = min(target_val - cur_val, cash * _BUY_CHUNK)
                qty     = int(invest / (price * 1.0015))
                if qty > 0 and cash >= price * qty * 1.0015:
                    return {"action": "BUY", "symbol": sym, "quantity": qty}

        # ── 4. 목표 비중 초과 → 일부 매도 ───────────────────────────────────
        for sym in _TARGETS:
            pos = portfolio.get(sym)
            if not pos:
                continue
            target_val = total * _ALLOC_RATIO
            cur_val    = pos["value"]
            if cur_val > target_val * (1 + _REBAL_BAND * 2):
                excess_val = cur_val - target_val
                price = stocks[sym]["price"]
                qty   = min(pos["quantity"], int(excess_val / price))
                if qty > 0:
                    return {"action": "SELL", "symbol": sym, "quantity": qty}

        # ── 5. INQUIRY (20턴마다) ────────────────────────────────────────────
        if tick % 20 == 0 and tick not in self._inquiry_done:
            self._inquiry_done.add(tick)
            return {"action": "INQUIRY"}

        # ── 6. 대기 (이자 수령) ──────────────────────────────────────────────
        return {"action": "HOLD"}
