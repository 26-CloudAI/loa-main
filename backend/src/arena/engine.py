"""
AI Arena — 게임 엔진 코어

틱 처리 순서 (각 틱마다):
  1. 모든 봇에서 action 수집 (타임아웃 시 STAY)
  2. 실드 처리 (이전 틱 실드 해제, 이번 틱 실드 활성화)
  3. 공격 해석 (데미지 적용, 실드 감소 반영)
  4. 이동 해석 (경계 클램핑, 에너지 차감)
  5. 채굴 해석 (광물 확인, 점수 부여, 경합 분배)
  6. 대기(STAY) 에너지 차감
  7. 자기장 데미지 적용
  8. 사망 판정 및 제거
  9. 생존 틱 갱신
  10. 광물 재생
  11. 자기장 경계 업데이트
  12. 승리 조건 확인
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from typing import Optional

from .bot_interface import BotInterface
from .config import DEFAULT_CONFIG, GameConfig
from .grid import Grid
from .types import (
    ATTACK_ACTIONS,
    DIRECTION_DELTA,
    MOVE_ACTIONS,
    Action,
    Bot,
    GameOverReason,
    GameResult,
    Position,
    TickEvent,
    action_to_direction,
)
from .vision import build_bot_state, build_leaderboard
from .zone import ZoneManager

logger = logging.getLogger(__name__)


class GameEngine:
    """
    AI Arena 게임 엔진.
    봇 인터페이스를 받아 한 판의 게임을 실행한다.
    """

    def __init__(
        self,
        bot_interfaces: list[BotInterface],
        config: GameConfig = DEFAULT_CONFIG,
        seed: Optional[int] = None,
    ):
        if not bot_interfaces:
            raise ValueError("최소 1개 이상의 봇이 필요합니다.")

        self.config = config
        self.rng = random.Random(seed)
        self.tick = 0
        self.game_over = False
        self.game_result: Optional[GameResult] = None
        self.events: list[TickEvent] = []

        # 봇 인터페이스 → 봇 ID 매핑
        self._interfaces: dict[str, BotInterface] = {}
        for bi in bot_interfaces:
            self._interfaces[bi.bot_id] = bi

        # 맵 초기화
        self.grid = Grid(config, self.rng)
        self.zone = ZoneManager(config, self.rng)

        # 봇 엔티티 생성 및 스폰
        self.bots: dict[str, Bot] = {}

        # ── 스폰 위치 선택 ──────────────────────────────────────────────────
        # 맵 정보를 구성해 모든 봇에게 동시에 제공한다.
        map_info = {
            "width":    config.map.width,
            "height":   config.map.height,
            "minerals": [
                {"x": x, "y": y, "rare": rare}
                for x, y, rare in self.grid.get_all_mineral_positions()
            ],
        }

        # 각 봇에게 스폰 위치를 요청한다 (봇끼리 서로의 선택을 모름).
        spawn_requests: dict[str, tuple[int, int] | None] = {}
        for bi in bot_interfaces:
            try:
                choice = bi.choose_spawn(map_info)
                if choice is not None:
                    x, y = int(choice[0]), int(choice[1])
                    spawn_requests[bi.bot_id] = (x, y) if self.grid.is_in_bounds(x, y) else None
                else:
                    spawn_requests[bi.bot_id] = None
            except Exception:
                logger.debug("Bot %s choose_spawn 실패, 랜덤 스폰 처리", bi.bot_id, exc_info=True)
                spawn_requests[bi.bot_id] = None

        # 같은 칸을 요청한 봇이 여럿이면 무작위로 1명만 허용한다.
        position_claims: defaultdict[tuple[int, int], list[str]] = defaultdict(list)
        for bot_id, pos in spawn_requests.items():
            if pos is not None:
                position_claims[pos].append(bot_id)

        confirmed: dict[str, tuple[int, int]] = {}
        for pos, claimants in position_claims.items():
            winner = self.rng.choice(claimants)
            confirmed[winner] = pos

        # ── 실제 스폰 ───────────────────────────────────────────────────────
        used_positions: set[tuple[int, int]] = set(confirmed.values())

        for bi in bot_interfaces:
            if bi.bot_id in confirmed:
                pos = Position(*confirmed[bi.bot_id])
            else:
                # 선택 없음 또는 충돌 패배 → 랜덤 스폰
                pos = None
                attempts = 0
                while attempts < 10000:
                    x = self.rng.randint(0, self.config.map.width - 1)
                    y = self.rng.randint(0, self.config.map.height - 1)
                    if (x, y) not in used_positions:
                        pos = Position(x, y)
                        break
                    attempts += 1
                if pos is None:
                    raise RuntimeError("맵에 봇을 배치할 공간을 찾을 수 없습니다.")

            used_positions.add(pos.as_tuple())
            self.bots[bi.bot_id] = Bot(
                id=bi.bot_id,
                position=pos,
                energy=config.bot.initial_energy,
                max_energy=config.bot.max_energy,
            )

    # ──────────────────────────────────────────────
    #  공개 API
    # ──────────────────────────────────────────────

    def run_full_game(self) -> GameResult:
        """게임을 끝까지 실행하고 결과를 반환."""
        while not self.game_over:
            self.process_tick()
        assert self.game_result is not None
        return self.game_result

    def process_tick(self) -> list[TickEvent]:
        """한 틱을 처리하고 이벤트 로그를 반환."""
        if self.game_over:
            return []

        tick_events: list[TickEvent] = []

        # 1. 액션 수집
        actions = self._collect_actions()

        # 2. 실드 처리
        self._clear_old_shields()
        self._resolve_shields(actions, tick_events)

        # 3. 공격 해석
        self._resolve_attacks(actions, tick_events)

        # 4. 이동 해석
        self._resolve_moves(actions, tick_events)

        # 5. 채굴 해석
        self._resolve_mines(actions, tick_events)

        # 6. STAY 비용
        self._resolve_stays(actions, tick_events)

        # 7. 자기장 데미지
        self._apply_zone_damage(tick_events)

        # 8. 사망 판정
        self._process_deaths(tick_events)

        # 9. 생존 틱 갱신
        for bot in self.bots.values():
            if bot.alive:
                bot.survival_ticks += 1

        # 10. 광물 재생
        self.grid.try_regen_minerals(self.tick)

        # 11. 틱 증가 후 자기장 업데이트
        self.tick += 1
        self.zone.update(self.tick)

        # 12. 승리 조건
        self._check_game_over()

        self.events.extend(tick_events)
        return tick_events

    def get_alive_bots(self) -> list[Bot]:
        return [b for b in self.bots.values() if b.alive]

    def get_rankings(self) -> list[dict]:
        """최종 점수 기준 랭킹 반환."""
        gc = self.config

        # survival_ticks 기준으로 상위 3인 보너스 결정
        sorted_by_survival = sorted(
            self.bots.values(),
            key=lambda b: b.survival_ticks,
            reverse=True,
        )
        survival_bonus: dict[str, float] = {}
        for i, bot in enumerate(sorted_by_survival):
            if i < len(gc.survival_rank_bonus):
                survival_bonus[bot.id] = gc.survival_rank_bonus[i]

        rankings = []
        for bot in self.bots.values():
            final_score = (
                bot.score
                + bot.survival_ticks * gc.score_per_survival_tick
                + bot.kills * gc.score_per_kill
                + survival_bonus.get(bot.id, 0)
            )
            rankings.append({
                "id": bot.id,
                "final_score": round(final_score, 1),
                "minerals_mined": bot.minerals_mined,
                "kills": bot.kills,
                "survival_ticks": bot.survival_ticks,
                "survival_bonus": survival_bonus.get(bot.id, 0),
                "energy": bot.energy,
                "alive": bot.alive,
            })
        rankings.sort(key=lambda r: r["final_score"], reverse=True)
        for i, r in enumerate(rankings):
            r["rank"] = i + 1
        return rankings

    # ──────────────────────────────────────────────
    #  내부 — 액션 수집
    # ──────────────────────────────────────────────

    def _collect_actions(self) -> dict[str, Action]:
        """모든 생존 봇에서 action을 수집. 예외 시 STAY."""
        actions: dict[str, Action] = {}
        leaderboard = build_leaderboard(self.bots, self.config)

        for bot_id, bot in self.bots.items():
            if not bot.alive:
                continue

            interface = self._interfaces.get(bot_id)
            if interface is None:
                actions[bot_id] = Action.STAY
                continue

            state = build_bot_state(
                bot, self.bots, self.grid, self.zone, self.config, self.tick,
                leaderboard=leaderboard,
            )

            try:
                raw = interface.get_action(state)
                action = Action(raw)
            except Exception:
                logger.debug(
                    "Bot %s 액션 파싱 실패, STAY 처리", bot_id, exc_info=True
                )
                action = Action.STAY

            actions[bot_id] = action

        self.current_actions = actions
        return actions

    # ──────────────────────────────────────────────
    #  내부 — 실드
    # ──────────────────────────────────────────────

    def _clear_old_shields(self) -> None:
        """이전 틱에서 활성화된 실드를 해제."""
        for bot in self.bots.values():
            bot.shield_active = False

    def _resolve_shields(
        self, actions: dict[str, Action], events: list[TickEvent]
    ) -> None:
        """SHIELD 액션 처리. 공격 해석 전에 실드를 활성화해야 한다."""
        cost = self.config.action_cost.shield
        for bot_id, action in actions.items():
            if action != Action.SHIELD:
                continue
            bot = self.bots[bot_id]
            if not bot.alive:
                continue
            bot.deduct_energy(cost)
            if bot.alive:
                bot.shield_active = True

    # ──────────────────────────────────────────────
    #  내부 — 공격
    # ──────────────────────────────────────────────

    def _resolve_attacks(
        self, actions: dict[str, Action], events: list[TickEvent]
    ) -> None:
        """ATTACK 액션 처리. 모든 공격을 먼저 수집한 뒤 일괄 적용."""
        attack_cost = self.config.action_cost.attack
        attack_damage = self.config.combat.attack_damage

        # 공격 전 위치 스냅샷 — O(1) 봇 탐색
        pos_to_bot: dict[tuple[int, int], str] = {
            b.position.as_tuple(): b.id
            for b in self.bots.values()
            if b.alive
        }

        pending_attacks: list[tuple[str, str]] = []

        for bot_id, action in actions.items():
            if action not in ATTACK_ACTIONS:
                continue
            bot = self.bots[bot_id]
            if not bot.alive:
                continue

            bot.deduct_energy(attack_cost)

            if not bot.alive:
                continue

            direction = action_to_direction(action)
            if direction is None:
                continue

            dx, dy = DIRECTION_DELTA[direction]
            target_x = bot.position.x + dx
            target_y = bot.position.y + dy

            target_id = pos_to_bot.get((target_x, target_y))
            if target_id is None or target_id == bot_id:
                target_id = None
            target_bot = self.bots[target_id] if target_id else None
            if target_bot is None:
                events.append(TickEvent(
                    tick=self.tick,
                    event_type="attack_miss",
                    actor_id=bot_id,
                    detail=f"공격 빗나감 → ({target_x}, {target_y})",
                ))
                continue

            pending_attacks.append((target_bot.id, bot_id))

        # 데미지 일괄 적용 (동시 공격 처리)
        # 에너지 흡수는 모든 데미지 적용 후 처리 — 동시 처치 시 흡수 에너지가
        # 같은 틱의 피격 결과에 영향을 주지 않도록 분리한다.
        pending_kills: list[tuple[str, str, int]] = []  # (attacker_id, target_id, energy_absorbed)

        for target_id, attacker_id in pending_attacks:
            target = self.bots[target_id]
            if not target.alive:
                continue

            energy_before_damage = target.energy

            if target.shield_active:
                target.score += self.config.score_per_guard
                events.append(TickEvent(
                    tick=self.tick,
                    event_type="guard_success",
                    actor_id=target_id,
                    target_id=attacker_id,
                    detail=f"방어 성공 (+{self.config.score_per_guard}점)",
                ))

            actual_damage = target.apply_damage(attack_damage)
            events.append(TickEvent(
                tick=self.tick,
                event_type="attack_hit",
                actor_id=attacker_id,
                target_id=target_id,
                detail=f"데미지 {actual_damage} (실드: {target.shield_active})",
            ))

            if not target.alive:
                pending_kills.append((attacker_id, target_id, energy_before_damage))

        # 모든 데미지 적용 후 처치 처리 (에너지 흡수 및 킬 카운트)
        for attacker_id, target_id, energy_absorbed in pending_kills:
            attacker = self.bots[attacker_id]
            if attacker.alive:
                attacker.kills += 1
                attacker.gain_energy(energy_absorbed)

            events.append(TickEvent(
                tick=self.tick,
                event_type="kill",
                actor_id=attacker_id,
                target_id=target_id,
                detail=f"{attacker_id}이(가) {target_id} 처치 (에너지 +{energy_absorbed})",
            ))

    # ──────────────────────────────────────────────
    #  내부 — 이동
    # ──────────────────────────────────────────────

    def _resolve_moves(
        self, actions: dict[str, Action], events: list[TickEvent]
    ) -> None:
        """MOVE 액션 처리. 경계 밖 이동은 무시(비용은 소모)."""
        move_cost = self.config.action_cost.move

        for bot_id, action in actions.items():
            if action not in MOVE_ACTIONS:
                continue
            bot = self.bots[bot_id]
            if not bot.alive:
                continue

            bot.deduct_energy(move_cost)

            # 비용 차감으로 사망 시 이동 무효
            if not bot.alive:
                continue

            direction = action_to_direction(action)
            if direction is None:
                continue

            dx, dy = DIRECTION_DELTA[direction]
            new_x = bot.position.x + dx
            new_y = bot.position.y + dy

            if self.grid.is_in_bounds(new_x, new_y):
                bot.position.x = new_x
                bot.position.y = new_y

    # ──────────────────────────────────────────────
    #  내부 — 채굴
    # ──────────────────────────────────────────────

    def _resolve_mines(
        self, actions: dict[str, Action], events: list[TickEvent]
    ) -> None:
        """MINE 액션 처리. 같은 광물 경합 시 점수 분배."""
        mine_cost = self.config.action_cost.mine
        mc = self.config.mine

        # 같은 칸에서 MINE하는 봇들을 그룹핑
        mine_groups: dict[tuple[int, int], list[str]] = defaultdict(list)

        for bot_id, action in actions.items():
            if action != Action.MINE:
                continue
            bot = self.bots[bot_id]
            if not bot.alive:
                continue

            bot.deduct_energy(mine_cost)
            if bot.alive:
                mine_groups[bot.position.as_tuple()].append(bot_id)

        # 각 위치별 채굴 해석
        for (mx, my), miner_ids in mine_groups.items():
            mineral = self.grid.get_mineral(mx, my)
            if mineral is None:
                for mid in miner_ids:
                    events.append(TickEvent(
                        tick=self.tick,
                        event_type="mine_fail",
                        actor_id=mid,
                        detail=f"({mx}, {my})에 광물 없음",
                    ))
                continue

            # 점수 계산
            base_points = mc.rare_points if mineral.rare else mc.normal_points
            energy_gain = mc.energy_gain_rare if mineral.rare else mc.energy_gain_normal
            split_count = len(miner_ids)
            points_each = base_points / split_count

            # 광물 소비
            self.grid.mark_mined(mx, my, self.tick)


            for mid in miner_ids:
                bot = self.bots[mid]
                if not bot.alive:
                    continue
                bot.score += points_each
                bot.gain_energy(energy_gain // split_count) # 경합 시 에너지도 분배
                bot.minerals_mined += 1
                events.append(TickEvent(
                    tick=self.tick,
                    event_type="mine_success",
                    actor_id=mid,
                    detail=(
                        f"{'희귀 ' if mineral.rare else ''}"
                        f"광물 채굴 +{points_each:.1f}점"
                        f", 에너지 +{energy_gain // split_count}"
                        f"{' (경합)' if split_count > 1 else ''}"
                    ),
                ))

    # ──────────────────────────────────────────────
    #  내부 — 대기
    # ──────────────────────────────────────────────

    def _resolve_stays(
        self, actions: dict[str, Action], events: list[TickEvent]
    ) -> None:
        """STAY 액션 에너지 차감."""
        stay_cost = self.config.action_cost.stay
        for bot_id, action in actions.items():
            if action != Action.STAY:
                continue
            bot = self.bots[bot_id]
            if bot.alive:
                bot.deduct_energy(stay_cost)

    # ──────────────────────────────────────────────
    #  내부 — 자기장
    # ──────────────────────────────────────────────

    def _apply_zone_damage(self, events: list[TickEvent]) -> None:
        """자기장 영역 밖 봇에게 데미지."""
        damage = self.zone.get_zone_damage(self.tick)
        if damage <= 0:
            return

        for bot in self.bots.values():
            if not bot.alive:
                continue
            if self.zone.is_outside_safe_zone(bot.position):
                bot.deduct_energy(damage)
                events.append(TickEvent(
                    tick=self.tick,
                    event_type="zone_damage",
                    actor_id=bot.id,
                    detail=f"자기장 데미지 -{damage}",
                ))

    # ──────────────────────────────────────────────
    #  내부 — 사망 처리
    # ──────────────────────────────────────────────

    def _process_deaths(self, events: list[TickEvent]) -> None:
        """에너지 0 이하인 봇을 사망 처리."""
        for bot in self.bots.values():
            if bot.energy <= 0 and bot.alive:
                bot.alive = False
                events.append(TickEvent(
                    tick=self.tick,
                    event_type="death",
                    target_id=bot.id,
                    detail=f"{bot.id} 탈락 (에너지: {bot.energy})",
                ))

    # ──────────────────────────────────────────────
    #  내부 — 승리 조건
    # ──────────────────────────────────────────────

    def _check_game_over(self) -> None:
        """게임 종료 조건 확인."""
        alive = self.get_alive_bots()

        # 조건 1: 봇 1개 이하 생존
        if len(alive) <= 1:
            self.game_over = True
            self.game_result = GameResult(
                reason=GameOverReason.LAST_STANDING,
                final_tick=self.tick,
                rankings=self.get_rankings(),
            )
            return

        # 조건 2: 최대 틱 도달
        if self.tick >= self.config.max_ticks:
            self.game_over = True
            self.game_result = GameResult(
                reason=GameOverReason.MAX_TICKS,
                final_tick=self.tick,
                rankings=self.get_rankings(),
            )
            return

        # 조건 3: 전체 광물 소진
        if self.grid.all_minerals_depleted():
            self.game_over = True
            self.game_result = GameResult(
                reason=GameOverReason.ALL_MINERALS_DEPLETED,
                final_tick=self.tick,
                rankings=self.get_rankings(),
            )
            return

    # ──────────────────────────────────────────────
    #  유틸리티
    # ──────────────────────────────────────────────

    def _find_bot_at(
        self, x: int, y: int, exclude: Optional[str] = None
    ) -> Optional[Bot]:
        """해당 좌표에 있는 생존 봇을 찾는다."""
        for bot in self.bots.values():
            if not bot.alive:
                continue
            if bot.id == exclude:
                continue
            if bot.position.x == x and bot.position.y == y:
                return bot
        return None
