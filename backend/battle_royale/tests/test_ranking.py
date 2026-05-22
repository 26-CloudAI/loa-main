"""
AI Arena — 랭킹 시스템 테스트

1. ELO 수학 (기대 승률, K-factor, 대칭성)
2. 멀티플레이어 ELO (승자 상승, 약자 이변, 순위 순서)
3. 티어/유틸
4. 시즌 관리
5. 랭킹 리포지토리 (레이팅 업데이트, 리더보드, 히스토리, 통계)
6. 통합 시나리오 (10판 시뮬레이션)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arena.db.schema import init_db
from src.arena.db.user_repo import UserRepository
from src.arena.db.bot_repo import BotRepository
from src.arena.db.game_repo import GameRepository
from src.arena.ranking.elo import (
    DEFAULT_ELO_CONFIG,
    EloConfig,
    PlayerResult,
    RatingChange,
    calculate_multiplayer_elo,
    expected_score,
    get_k_factor,
    get_tier,
    get_tier_color,
    estimate_rank_probability,
)
from src.arena.ranking.repository import (
    RankingRepository,
    SeasonRepository,
    init_ranking_tables,
)


# ── 1. ELO 수학 ──

class TestEloMath(unittest.TestCase):
    def test_equal_rating_50_percent(self):
        self.assertAlmostEqual(expected_score(1200, 1200), 0.5, places=5)

    def test_higher_rating_favored(self):
        self.assertGreater(expected_score(1400, 1200), 0.5)

    def test_symmetry(self):
        self.assertAlmostEqual(
            expected_score(1300, 1100) + expected_score(1100, 1300), 1.0, places=10
        )

    def test_400_diff_about_91_percent(self):
        self.assertAlmostEqual(expected_score(1600, 1200), 0.909, places=2)

    def test_k_factor_new(self):
        self.assertEqual(get_k_factor(0), 40.0)
        self.assertEqual(get_k_factor(9), 40.0)

    def test_k_factor_mid(self):
        self.assertEqual(get_k_factor(10), 24.0)
        self.assertEqual(get_k_factor(29), 24.0)

    def test_k_factor_veteran(self):
        self.assertEqual(get_k_factor(30), 16.0)
        self.assertEqual(get_k_factor(999), 16.0)


# ── 2. 멀티플레이어 ELO ──

class TestMultiplayerElo(unittest.TestCase):
    def test_winner_gains_loser_loses(self):
        changes = calculate_multiplayer_elo([
            PlayerResult(1, 1200, 20, 1),
            PlayerResult(2, 1200, 20, 2),
        ])
        self.assertGreater(changes[0].rating_delta, 0)
        self.assertLess(changes[1].rating_delta, 0)

    def test_roughly_zero_sum(self):
        changes = calculate_multiplayer_elo([
            PlayerResult(1, 1200, 20, 1),
            PlayerResult(2, 1200, 20, 2),
        ])
        self.assertAlmostEqual(sum(c.rating_delta for c in changes), 0, delta=1.0)

    def test_four_player_order(self):
        changes = calculate_multiplayer_elo([
            PlayerResult(i, 1200, 20, i) for i in range(1, 5)
        ])
        deltas = [next(c for c in changes if c.player_id == i).rating_delta for i in range(1, 5)]
        for i in range(len(deltas) - 1):
            self.assertGreater(deltas[i], deltas[i + 1])

    def test_upset_more_reward(self):
        upset = calculate_multiplayer_elo([
            PlayerResult(1, 1000, 20, 1), PlayerResult(2, 1400, 20, 2),
        ])
        normal = calculate_multiplayer_elo([
            PlayerResult(1, 1400, 20, 1), PlayerResult(2, 1000, 20, 2),
        ])
        self.assertGreater(upset[0].rating_delta, normal[0].rating_delta)

    def test_single_player_no_change(self):
        changes = calculate_multiplayer_elo([PlayerResult(1, 1200, 20, 1)])
        self.assertEqual(changes[0].rating_delta, 0)

    def test_eight_players(self):
        changes = calculate_multiplayer_elo([
            PlayerResult(i, 1200, 20, i) for i in range(1, 9)
        ])
        self.assertEqual(len(changes), 8)
        self.assertGreater(changes[0].rating_delta, 0)  # 1위
        self.assertLess(changes[-1].rating_delta, 0)     # 8위

    def test_min_rating_floor(self):
        changes = calculate_multiplayer_elo([
            PlayerResult(1, 110, 5, 4),
            PlayerResult(2, 1800, 5, 1),
            PlayerResult(3, 1800, 5, 2),
            PlayerResult(4, 1800, 5, 3),
        ])
        loser = next(c for c in changes if c.player_id == 1)
        self.assertGreaterEqual(loser.rating_after, DEFAULT_ELO_CONFIG.min_rating)


# ── 3. 티어/유틸 ──

class TestTiers(unittest.TestCase):
    def test_tier_boundaries(self):
        self.assertEqual(get_tier(2100), "Grandmaster")
        self.assertEqual(get_tier(1900), "Master")
        self.assertEqual(get_tier(1700), "Diamond")
        self.assertEqual(get_tier(1500), "Platinum")
        self.assertEqual(get_tier(1200), "Gold")
        self.assertEqual(get_tier(1000), "Silver")
        self.assertEqual(get_tier(800), "Bronze")
        self.assertEqual(get_tier(500), "Iron")

    def test_tier_colors(self):
        for r in [2100, 1200, 500]:
            self.assertTrue(get_tier_color(get_tier(r)).startswith("#"))

    def test_rank_probability_sums_to_1(self):
        probs = estimate_rank_probability(1400, [1200, 1200, 1200])
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=2)

    def test_rank_probability_favors_strong(self):
        probs = estimate_rank_probability(1400, [1200, 1200, 1200])
        self.assertGreater(probs[1], probs[4])


# ── DB 테스트 베이스 ──

class RankingDBBase(unittest.TestCase):
    def setUp(self):
        self.conn = init_db(":memory:")
        init_ranking_tables(self.conn)
        self.users = UserRepository(self.conn)
        self.bots = BotRepository(self.conn)
        self.games = GameRepository(self.conn)
        self.seasons = SeasonRepository(self.conn)
        self.rankings = RankingRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def _user(self, name="u1"):
        return self.users.create(f"uid_{name}", name, name).id

    def _bot(self, uid, name="b1"):
        return self.bots.create(uid, name, "def action(s): return 'STAY'").id

    def _game(self, gid="g-001", n=4, owner_user_id=None):
        if owner_user_id is None:
            owner_user_id = self._default_owner_id()
        self.games.create_game(gid, owner_user_id, n)
        return gid

    def _default_owner_id(self):
        """게임 owner 용으로 한 번만 생성되는 더미 유저 id를 반환."""
        if not hasattr(self, "_owner_id"):
            self._owner_id = self._user("game_owner")
        return self._owner_id

    def _setup4(self):
        u1, u2 = self._user("u1"), self._user("u2")
        bs = [self._bot(u1, "A"), self._bot(u1, "B"), self._bot(u2, "C"), self._bot(u2, "D")]
        s = self.seasons.create_season("S1")
        return bs, s.id


# ── 4. 시즌 관리 ──

class TestSeasonRepo(RankingDBBase):
    def test_create(self):
        s = self.seasons.create_season("S1")
        self.assertTrue(s.is_active)

    def test_new_deactivates_old(self):
        s1 = self.seasons.create_season("S1")
        self.seasons.create_season("S2")
        self.assertFalse(self.seasons.get_season(s1.id).is_active)

    def test_get_active(self):
        self.seasons.create_season("S1")
        self.seasons.create_season("S2")
        self.assertEqual(self.seasons.get_active_season().name, "S2")

    def test_none_active(self):
        self.assertIsNone(self.seasons.get_active_season())

    def test_list_all(self):
        for i in range(3):
            self.seasons.create_season(f"S{i}")
        self.assertEqual(len(self.seasons.get_all_seasons()), 3)

    def test_end_season(self):
        s = self.seasons.create_season("S1")
        self.seasons.end_season(s.id)
        ended = self.seasons.get_season(s.id)
        self.assertFalse(ended.is_active)
        self.assertIsNotNone(ended.ended_at)


# ── 5. 랭킹 리포지토리 ──

class TestRankingRepo(RankingDBBase):
    def test_create_rating(self):
        uid = self._user()
        bid = self._bot(uid)
        s = self.seasons.create_season("S1")
        br = self.rankings.get_or_create_rating(bid, s.id)
        self.assertEqual(br.rating, 1200)
        self.assertEqual(br.games_played, 0)

    def test_process_results_winner_gains(self):
        bs, sid = self._setup4()
        gid = self._game()
        parts = [
            {"bot_id": bs[i], "final_rank": i + 1, "kills": 3 - i, "minerals_mined": 0, "survival_ticks": 0}
            for i in range(4)
        ]
        changes = self.rankings.process_game_results(gid, sid, parts)
        winner = next(c for c in changes if c.player_id == bs[0])
        loser = next(c for c in changes if c.player_id == bs[3])
        self.assertGreater(winner.rating_after, 1200)
        self.assertLess(loser.rating_after, 1200)

    def test_leaderboard(self):
        bs, sid = self._setup4()
        for i in range(3):
            parts = [{"bot_id": bs[j], "final_rank": j + 1, "kills": 0, "minerals_mined": 0, "survival_ticks": 0} for j in range(4)]
            self.rankings.process_game_results(self._game(f"g-{i}"), sid, parts)
        lb = self.rankings.get_leaderboard(sid, min_games=3)
        self.assertEqual(len(lb), 4)
        self.assertGreater(lb[0]["rating"], lb[-1]["rating"])
        self.assertEqual(lb[0]["rank"], 1)

    def test_rating_history(self):
        bs, sid = self._setup4()
        self.rankings.process_game_results(self._game(), sid, [
            {"bot_id": bs[0], "final_rank": 1, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
            {"bot_id": bs[1], "final_rank": 2, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
        ])
        h = self.rankings.get_rating_history(bs[0], sid)
        self.assertEqual(len(h), 1)
        self.assertGreater(h[0].rating_delta, 0)

    def test_bot_stats(self):
        bs, sid = self._setup4()
        for i in range(5):
            self.rankings.process_game_results(self._game(f"g-{i}"), sid, [
                {"bot_id": bs[0], "final_rank": 1, "kills": 2, "minerals_mined": 5, "survival_ticks": 400},
                {"bot_id": bs[1], "final_rank": 2, "kills": 0, "minerals_mined": 3, "survival_ticks": 300},
            ])
        stats = self.rankings.get_bot_stats(bs[0], sid)
        self.assertEqual(stats["games_played"], 5)
        self.assertEqual(stats["wins"], 5)
        self.assertAlmostEqual(stats["win_rate"], 100.0)
        self.assertEqual(stats["total_kills"], 10)
        self.assertFalse(stats["is_placement"])
        self.assertEqual(stats["current_streak"], 5)

    def test_placement_detection(self):
        bs, sid = self._setup4()
        self.rankings.process_game_results(self._game(), sid, [
            {"bot_id": bs[0], "final_rank": 1, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
            {"bot_id": bs[1], "final_rank": 2, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
        ])
        self.assertTrue(self.rankings.get_bot_stats(bs[0], sid)["is_placement"])

    def test_peak_rating_preserved(self):
        bs, sid = self._setup4()
        self.rankings.process_game_results(self._game("g-0"), sid, [
            {"bot_id": bs[0], "final_rank": 1, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
            {"bot_id": bs[1], "final_rank": 2, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
        ])
        peak = self.rankings.get_rating(bs[0], sid).peak_rating
        self.rankings.process_game_results(self._game("g-1"), sid, [
            {"bot_id": bs[0], "final_rank": 2, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
            {"bot_id": bs[1], "final_rank": 1, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
        ])
        br = self.rankings.get_rating(bs[0], sid)
        self.assertEqual(br.peak_rating, peak)
        self.assertLess(br.rating, peak)

    def test_chart_data_ascending(self):
        bs, sid = self._setup4()
        for i in range(3):
            self.rankings.process_game_results(self._game(f"g-{i}"), sid, [
                {"bot_id": bs[0], "final_rank": 1, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
                {"bot_id": bs[1], "final_rank": 2, "kills": 0, "minerals_mined": 0, "survival_ticks": 0},
            ])
        chart = self.rankings.get_rating_chart_data(bs[0], sid)
        self.assertEqual(len(chart), 3)
        self.assertLess(chart[0]["rating"], chart[-1]["rating"])

    def test_global_stats(self):
        bs, sid = self._setup4()
        self.rankings.process_game_results(self._game(), sid, [
            {"bot_id": bs[0], "final_rank": 1, "kills": 3, "minerals_mined": 0, "survival_ticks": 0},
            {"bot_id": bs[1], "final_rank": 2, "kills": 1, "minerals_mined": 0, "survival_ticks": 0},
        ])
        g = self.rankings.get_global_stats(sid)
        self.assertEqual(g["total_bots"], 2)
        self.assertEqual(g["total_kills"], 4)


# ── 6. 통합 시나리오 ──

class TestIntegration(RankingDBBase):
    def test_10_game_season(self):
        u1, u2, u3 = self._user("a"), self._user("b"), self._user("c")
        b1, b2, b3 = self._bot(u1, "강한봇"), self._bot(u2, "보통봇"), self._bot(u3, "약한봇")
        s = self.seasons.create_season("테스트 시즌")

        patterns = [[1,2,3],[1,3,2],[1,2,3],[2,1,3],[1,2,3],
                     [1,2,3],[1,3,2],[2,1,3],[1,2,3],[1,2,3]]
        for i, ranks in enumerate(patterns):
            self.games.create_game(f"g{i}", u1, 3)
            parts = [{"bot_id": bid, "final_rank": r, "kills": 0, "minerals_mined": 0, "survival_ticks": 0}
                     for bid, r in zip([b1, b2, b3], ranks)]
            self.rankings.process_game_results(f"g{i}", s.id, parts)

        r1 = self.rankings.get_rating(b1, s.id)
        r2 = self.rankings.get_rating(b2, s.id)
        r3 = self.rankings.get_rating(b3, s.id)
        self.assertGreater(r1.rating, r2.rating)
        self.assertGreater(r2.rating, r3.rating)

        lb = self.rankings.get_leaderboard(s.id, min_games=3)
        self.assertEqual(lb[0]["bot_name"], "강한봇")


if __name__ == "__main__":
    unittest.main(verbosity=2)
