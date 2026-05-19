"""
MockStocks — 게임 엔진

매 틱 처리 순서:
  1. 시장 가격 갱신 (GBM + 뉴스 효과)
  2. 각 봇 state 구성 → 행동 수집
  3. 행동 체결 (BUY / SELL / SHORT / COVER / INQUIRY / HOLD)
  4. 총 자산 갱신 (신용점수 포함)
  5. 게임 종료 확인
"""

import random
from .config import Config, DEFAULT_CONFIG
from .types import (
    Order, OrderType,
    LongPosition, ShortPosition,
    BotState, StockData, GameResult,
)
from .market import Market
from .bot_interface import BotInterface


class GameEngine:
    def __init__(
        self,
        bots: list[BotInterface],
        config: Config = DEFAULT_CONFIG,
        seed: int | None = None,
    ):
        self._cfg = config
        self._rng = random.Random(seed)
        self.market = Market(config=config, seed=seed)
        self.tick = 0
        self.game_over = False
        self.game_result: GameResult | None = None

        self.bots: dict[str, BotInterface] = {b.bot_id: b for b in bots}
        self.bot_states: dict[str, BotState] = {
            b.bot_id: BotState(
                bot_id=b.bot_id,
                cash=config.game.starting_cash,
                credit_score=config.credit.initial_score,
                total_value=config.game.starting_cash,
            )
            for b in bots
        }
        self._prev_actions: dict[str, OrderType] = {
            b.bot_id: OrderType.HOLD for b in bots
        }

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def process_tick(self) -> None:
        if self.game_over:
            return

        self.market.update()
        self.tick += 1

        stock_data = self.market.get_all_stock_data()
        leaderboard = self._build_leaderboard(stock_data)

        for bot_id, bot in self.bots.items():
            state = self._build_state(bot_id, stock_data, leaderboard)
            try:
                raw = bot.get_action(state)
                order = self._parse_order(raw)
            except Exception:
                order = Order(action=OrderType.HOLD)
            self._execute_order(bot_id, order, stock_data)
            self._prev_actions[bot_id] = order.action

        self._update_total_values(stock_data)
        self._handle_delisted_positions(stock_data)

        if self.tick >= self._cfg.game.total_ticks:
            self._end_game(stock_data)

    def snapshot(self) -> dict:
        stock_data = self.market.get_all_stock_data()
        return {
            "tick": self.tick,
            "finished": self.game_over,
            "market": {
                "stocks": [self._stock_dict(s) for s in stock_data],
                "news": [
                    {"symbol": n.symbol, "headline": n.headline, "ticks_remaining": n.ticks_remaining}
                    for n in self.market.get_active_news()
                ],
            },
            "bots": {
                bot_id: self._bot_public_dict(state, stock_data)
                for bot_id, state in self.bot_states.items()
            },
            "leaderboard": self._build_leaderboard(stock_data),
        }

    # ── 행동 처리 ─────────────────────────────────────────────────────────────

    def _parse_order(self, raw: dict) -> Order:
        try:
            action = OrderType(raw.get("action", "HOLD"))
        except ValueError:
            action = OrderType.HOLD
        return Order(
            action=action,
            symbol=str(raw.get("symbol", "")),
            quantity=max(0, int(raw.get("quantity", 0))),
        )

    def _execute_order(self, bot_id: str, order: Order, stock_data: list[StockData]) -> None:
        state = self.bot_states[bot_id]
        price_map = {s.symbol: s.price for s in stock_data}

        if order.action == OrderType.HOLD:
            self._apply_cash_interest(state)

        elif order.action == OrderType.BUY:
            self._execute_buy(state, order, price_map)

        elif order.action == OrderType.SELL:
            self._execute_sell(state, order, price_map)

        elif order.action == OrderType.SHORT:
            self._execute_short(state, order, price_map)

        elif order.action == OrderType.COVER:
            self._execute_cover(state, order, price_map)

        elif order.action == OrderType.INQUIRY:
            state.last_inquiry_hint = self.market.peek_next_news_hint()

    def _apply_cash_interest(self, state: BotState) -> None:
        interest = round(state.cash * self._cfg.game.cash_interest_rate, 0)
        state.cash += interest

    def _get_fee_rate(self, credit_score: int) -> float:
        cfg = self._cfg.credit
        if credit_score >= cfg.fee_min_score:
            return cfg.fee_minimum
        ratio = (credit_score - cfg.short_min_score) / (cfg.fee_min_score - cfg.short_min_score)
        ratio = max(0.0, min(1.0, ratio))
        return round(cfg.fee_standard - ratio * (cfg.fee_standard - cfg.fee_minimum), 6)

    def _execute_buy(self, state: BotState, order: Order, price_map: dict) -> None:
        if order.quantity == 0 or order.symbol not in price_map:
            return
        price = price_map[order.symbol]
        if price == 0:
            return
        fee = self._get_fee_rate(state.credit_score)
        cost = round(price * order.quantity * (1 + fee), 0)
        if state.cash < cost:
            return
        state.cash -= cost
        pos = state.long_positions.get(order.symbol)
        if pos:
            total_qty = pos.quantity + order.quantity
            pos.avg_cost = round((pos.avg_cost * pos.quantity + price * order.quantity) / total_qty, 0)
            pos.quantity = total_qty
        else:
            state.long_positions[order.symbol] = LongPosition(
                quantity=order.quantity, avg_cost=price
            )

    def _execute_sell(self, state: BotState, order: Order, price_map: dict) -> None:
        pos = state.long_positions.get(order.symbol)
        if not pos or order.quantity == 0:
            return
        qty = min(order.quantity, pos.quantity)
        price = price_map.get(order.symbol, 0)
        fee = self._get_fee_rate(state.credit_score)
        proceeds = round(price * qty * (1 - fee), 0)
        pnl = proceeds - round(pos.avg_cost * qty * (1 + fee), 0)
        state.cash += proceeds
        self._adjust_credit(state, pnl, pos.avg_cost * qty)
        pos.quantity -= qty
        if pos.quantity == 0:
            del state.long_positions[order.symbol]

    def _execute_short(self, state: BotState, order: Order, price_map: dict) -> None:
        if state.credit_score < self._cfg.credit.short_min_score:
            return
        if order.quantity == 0 or order.symbol not in price_map:
            return
        price = price_map[order.symbol]
        if price == 0:
            return

        # 공매도 한도: 총 자산의 50%
        short_value = price * order.quantity
        max_short = state.total_value * self._cfg.credit.short_max_asset_ratio
        existing_short = sum(
            p.avg_sell_price * p.quantity for p in state.short_positions.values()
        )
        if existing_short + short_value > max_short:
            return

        # 증거금: 공매도 금액의 50%
        margin = round(short_value * 0.5, 0)
        if state.cash < margin:
            return

        fee = self._get_fee_rate(state.credit_score)
        proceeds = round(price * order.quantity * (1 - fee), 0)
        state.cash = state.cash - margin + proceeds

        pos = state.short_positions.get(order.symbol)
        if pos:
            total_qty = pos.quantity + order.quantity
            pos.avg_sell_price = round(
                (pos.avg_sell_price * pos.quantity + price * order.quantity) / total_qty, 0
            )
            pos.quantity = total_qty
            pos.margin += margin
        else:
            state.short_positions[order.symbol] = ShortPosition(
                quantity=order.quantity,
                avg_sell_price=price,
                margin=margin,
            )

    def _execute_cover(self, state: BotState, order: Order, price_map: dict) -> None:
        pos = state.short_positions.get(order.symbol)
        if not pos or order.quantity == 0:
            return
        qty = min(order.quantity, pos.quantity)
        price = price_map.get(order.symbol, 0)
        fee = self._get_fee_rate(state.credit_score)
        buyback_cost = round(price * qty * (1 + fee), 0)

        # 공매도 손익 = 매도가 - 매수상환가
        pnl = round((pos.avg_sell_price - price) * qty, 0)
        returned_margin = round(pos.margin * qty / pos.quantity, 0)

        state.cash = state.cash - buyback_cost + returned_margin
        self._adjust_credit(state, pnl, pos.avg_sell_price * qty)

        pos.quantity -= qty
        pos.margin -= returned_margin
        if pos.quantity == 0:
            del state.short_positions[order.symbol]

    # ── 신용 점수 ─────────────────────────────────────────────────────────────

    def _adjust_credit(self, state: BotState, pnl: float, base_amount: float) -> None:
        if base_amount == 0:
            return
        pnl_pct = pnl / base_amount * 100
        delta = max(-5, min(5, round(pnl_pct)))
        state.credit_score = max(0, state.credit_score + delta)

    # ── 상장폐지 처리 ─────────────────────────────────────────────────────────

    def _handle_delisted_positions(self, stock_data: list[StockData]) -> None:
        delisted = {s.symbol for s in stock_data if s.delisted}
        for sym in delisted:
            for state in self.bot_states.values():
                if sym in state.long_positions:
                    del state.long_positions[sym]
                if sym in state.short_positions:
                    pos = state.short_positions.pop(sym)
                    state.cash += pos.margin  # 증거금 반환

    # ── 총 자산 갱신 ──────────────────────────────────────────────────────────

    def _update_total_values(self, stock_data: list[StockData]) -> None:
        price_map = {s.symbol: s.price for s in stock_data}
        for state in self.bot_states.values():
            long_val = sum(
                price_map.get(sym, 0) * pos.quantity
                for sym, pos in state.long_positions.items()
            )
            # 공매도 미실현 손익 반영 (음수일 수 있음)
            short_pnl = sum(
                (pos.avg_sell_price - price_map.get(sym, 0)) * pos.quantity
                for sym, pos in state.short_positions.items()
            )
            state.total_value = round(state.cash + long_val + short_pnl, 0)

    # ── 상태 구성 ─────────────────────────────────────────────────────────────

    def _build_state(self, bot_id: str, stock_data: list[StockData], leaderboard: list[dict]) -> dict:
        state = self.bot_states[bot_id]
        price_map = {s.symbol: s.price for s in stock_data}

        portfolio = {}
        for sym, pos in state.long_positions.items():
            cur_price = price_map.get(sym, 0)
            unrealized_pnl = round((cur_price - pos.avg_cost) * pos.quantity, 0)
            pnl_pct = round((cur_price - pos.avg_cost) / pos.avg_cost * 100, 2) if pos.avg_cost else 0
            portfolio[sym] = {
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": cur_price,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct": pnl_pct,
                "value": round(cur_price * pos.quantity, 0),
            }

        short_positions = {
            sym: {
                "quantity": pos.quantity,
                "avg_sell_price": pos.avg_sell_price,
                "current_price": price_map.get(sym, 0),
                "unrealized_pnl": round((pos.avg_sell_price - price_map.get(sym, 0)) * pos.quantity, 0),
                "margin": pos.margin,
            }
            for sym, pos in state.short_positions.items()
        }

        return {
            "tick": self.tick,
            "my_bot": {
                "id": bot_id,
                "cash": state.cash,
                "credit_score": state.credit_score,
                "total_value": state.total_value,
                "portfolio": portfolio,
                "short_positions": short_positions,
                "inquiry_hint": state.last_inquiry_hint,
            },
            "market": {
                "stocks": [self._stock_dict(s) for s in stock_data],
                "news": [
                    {
                        "symbol": n.symbol,
                        "headline": n.headline,
                        "ticks_remaining": n.ticks_remaining,
                    }
                    for n in self.market.get_active_news()
                ],
            },
            "leaderboard": leaderboard,
        }

    def _build_leaderboard(self, stock_data: list[StockData]) -> list[dict]:
        ranked = sorted(
            self.bot_states.values(),
            key=lambda s: s.total_value,
            reverse=True,
        )
        return [
            {"rank": i + 1, "id": s.bot_id, "total_value": s.total_value, "credit_score": s.credit_score}
            for i, s in enumerate(ranked)
        ]

    def _stock_dict(self, s: StockData) -> dict:
        return {
            "symbol": s.symbol,
            "name": s.name,
            "sector": s.sector,
            "price": s.price,
            "initial_price": s.initial_price,
            "price_history": s.price_history,
            "change_pct": s.change_pct,
            "delisted": s.delisted,
        }

    def _bot_public_dict(self, state: BotState, stock_data: list[StockData]) -> dict:
        price_map = {s.symbol: s.price for s in stock_data}
        return {
            "cash": state.cash,
            "credit_score": state.credit_score,
            "total_value": state.total_value,
            "portfolio": {
                sym: {"quantity": pos.quantity, "avg_cost": pos.avg_cost,
                      "value": round(price_map.get(sym, 0) * pos.quantity, 0)}
                for sym, pos in state.long_positions.items()
            },
            "short_positions": {
                sym: {"quantity": pos.quantity, "avg_sell_price": pos.avg_sell_price}
                for sym, pos in state.short_positions.items()
            },
        }

    # ── 게임 종료 ─────────────────────────────────────────────────────────────

    def _end_game(self, stock_data: list[StockData]) -> None:
        self.game_over = True
        leaderboard = self._build_leaderboard(stock_data)
        self.game_result = GameResult(final_tick=self.tick, rankings=leaderboard)
