"""AI Arena — ELO 레이팅 엔진"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EloConfig:
    initial_rating: int = 1200
    k_factor_new: float = 40.0
    k_factor_mid: float = 24.0
    k_factor_veteran: float = 16.0
    new_threshold: int = 10
    mid_threshold: int = 30
    min_rating: int = 100
    placement_games: int = 5


DEFAULT_ELO_CONFIG = EloConfig()


@dataclass
class PlayerResult:
    player_id: int
    rating_before: float
    games_played: int
    final_rank: int


@dataclass
class RatingChange:
    player_id: int
    rating_before: float
    rating_after: float
    rating_delta: float
    final_rank: int


def get_k_factor(games_played: int, config: EloConfig = DEFAULT_ELO_CONFIG) -> float:
    if games_played < config.new_threshold:
        return config.k_factor_new
    if games_played < config.mid_threshold:
        return config.k_factor_mid
    return config.k_factor_veteran


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400))


def actual_score_from_ranks(rank_a: int, rank_b: int) -> float:
    if rank_a < rank_b:
        return 1.0
    elif rank_a > rank_b:
        return 0.0
    return 0.5


def calculate_multiplayer_elo(
    results: list[PlayerResult],
    config: EloConfig = DEFAULT_ELO_CONFIG,
) -> list[RatingChange]:
    n = len(results)
    if n < 2:
        return [
            RatingChange(r.player_id, r.rating_before, r.rating_before, 0, r.final_rank)
            for r in results
        ]
    changes = []
    for player in results:
        k = get_k_factor(player.games_played, config)
        total_expected = 0.0
        total_actual = 0.0
        for opp in results:
            if opp.player_id == player.player_id:
                continue
            total_expected += expected_score(player.rating_before, opp.rating_before)
            total_actual += actual_score_from_ranks(player.final_rank, opp.final_rank)
        delta = k * (total_actual - total_expected) / (n - 1)
        new_rating = max(config.min_rating, player.rating_before + delta)
        changes.append(RatingChange(
            player.player_id, player.rating_before,
            round(new_rating, 1), round(new_rating - player.rating_before, 1),
            player.final_rank,
        ))
    return changes


def get_tier(rating: float) -> str:
    if rating >= 2000: return "Grandmaster"
    if rating >= 1800: return "Master"
    if rating >= 1600: return "Diamond"
    if rating >= 1400: return "Platinum"
    if rating >= 1200: return "Gold"
    if rating >= 1000: return "Silver"
    if rating >= 800: return "Bronze"
    return "Iron"


def get_tier_color(tier: str) -> str:
    return {
        "Grandmaster": "#ff4500", "Master": "#e040fb",
        "Diamond": "#00bcd4", "Platinum": "#4fc3f7",
        "Gold": "#ffd700", "Silver": "#c0c0c0",
        "Bronze": "#cd7f32", "Iron": "#808080",
    }.get(tier, "#808080")


def estimate_rank_probability(player_rating: float, opponent_ratings: list[float]) -> dict[int, float]:
    n = len(opponent_ratings) + 1
    win_probs = [expected_score(player_rating, opp) for opp in opponent_ratings]
    avg_wp = sum(win_probs) / max(len(win_probs), 1)
    exp_rank = 1 + (n - 1) * (1 - avg_wp)
    probs = {r: math.exp(-abs(r - exp_rank) * 0.8) for r in range(1, n + 1)}
    total = sum(probs.values())
    return {r: round(p / total, 3) for r, p in probs.items()}
