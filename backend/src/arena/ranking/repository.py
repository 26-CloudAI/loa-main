"""AI Arena — 랭킹 리포지토리"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Optional
from .elo import DEFAULT_ELO_CONFIG, EloConfig, PlayerResult, RatingChange, calculate_multiplayer_elo, get_tier

RANKING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    started_at TEXT NOT NULL DEFAULT (datetime('now')), ended_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS bot_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL, rating REAL NOT NULL DEFAULT 1200,
    peak_rating REAL NOT NULL DEFAULT 1200, games_played INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0, top3_count INTEGER NOT NULL DEFAULT 0,
    total_kills INTEGER NOT NULL DEFAULT 0, total_minerals INTEGER NOT NULL DEFAULT 0,
    avg_survival REAL NOT NULL DEFAULT 0, last_played_at TEXT,
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE,
    FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE,
    UNIQUE(bot_id, season_id));
CREATE INDEX IF NOT EXISTS idx_br_season ON bot_ratings(season_id);
CREATE TABLE IF NOT EXISTS rating_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INTEGER NOT NULL,
    season_id INTEGER NOT NULL, game_id TEXT NOT NULL,
    rating_before REAL NOT NULL, rating_after REAL NOT NULL,
    rating_delta REAL NOT NULL, final_rank INTEGER NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE,
    FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_rh_bot ON rating_history(bot_id, season_id);
"""

def init_ranking_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(RANKING_SCHEMA_SQL); conn.commit()

@dataclass
class Season:
    id: int; name: str; started_at: str; ended_at: Optional[str]; is_active: bool

@dataclass
class BotRating:
    id: int; bot_id: int; season_id: int; rating: float; peak_rating: float
    games_played: int; wins: int; top3_count: int; total_kills: int
    total_minerals: int; avg_survival: float; last_played_at: Optional[str]
    @property
    def tier(self): return get_tier(self.rating)
    @property
    def win_rate(self): return self.wins / self.games_played if self.games_played else 0.0
    @property
    def top3_rate(self): return self.top3_count / self.games_played if self.games_played else 0.0

@dataclass
class RatingHistoryEntry:
    id: int; bot_id: int; season_id: int; game_id: str
    rating_before: float; rating_after: float; rating_delta: float
    final_rank: int; recorded_at: str

class SeasonRepository:
    def __init__(self, conn: sqlite3.Connection): self.conn = conn

    def create_season(self, name: str) -> Season:
        self.conn.execute("UPDATE seasons SET is_active=0, ended_at=datetime('now') WHERE is_active=1")
        c = self.conn.execute("INSERT INTO seasons (name) VALUES (?)", (name,))
        self.conn.commit(); return self.get_season(c.lastrowid)

    def get_season(self, sid: int) -> Optional[Season]:
        r = self.conn.execute("SELECT * FROM seasons WHERE id=?", (sid,)).fetchone()
        return self._to(r) if r else None

    def get_active_season(self) -> Optional[Season]:
        r = self.conn.execute("SELECT * FROM seasons WHERE is_active=1 ORDER BY id DESC LIMIT 1").fetchone()
        return self._to(r) if r else None

    def get_all_seasons(self) -> list[Season]:
        return [self._to(r) for r in self.conn.execute("SELECT * FROM seasons ORDER BY id DESC").fetchall()]

    def end_season(self, sid: int) -> None:
        self.conn.execute("UPDATE seasons SET is_active=0, ended_at=datetime('now') WHERE id=?", (sid,))
        self.conn.commit()

    def _to(self, r) -> Season:
        return Season(id=r["id"], name=r["name"], started_at=r["started_at"],
                      ended_at=r["ended_at"], is_active=bool(r["is_active"]))

class RankingRepository:
    def __init__(self, conn: sqlite3.Connection, elo_config: EloConfig = DEFAULT_ELO_CONFIG):
        self.conn = conn; self.elo_config = elo_config

    def get_or_create_rating(self, bot_id: int, season_id: int) -> BotRating:
        r = self.conn.execute("SELECT * FROM bot_ratings WHERE bot_id=? AND season_id=?", (bot_id, season_id)).fetchone()
        if r: return self._to_br(r)
        init = self.elo_config.initial_rating
        self.conn.execute("INSERT INTO bot_ratings (bot_id,season_id,rating,peak_rating) VALUES (?,?,?,?)",
                          (bot_id, season_id, init, init))
        self.conn.commit(); return self.get_or_create_rating(bot_id, season_id)

    def get_rating(self, bot_id: int, season_id: int) -> Optional[BotRating]:
        r = self.conn.execute("SELECT * FROM bot_ratings WHERE bot_id=? AND season_id=?", (bot_id, season_id)).fetchone()
        return self._to_br(r) if r else None

    def process_game_results(self, game_id: str, season_id: int, participants: list[dict]) -> list[RatingChange]:
        prs = []
        for p in participants:
            br = self.get_or_create_rating(p["bot_id"], season_id)
            prs.append(PlayerResult(player_id=p["bot_id"], rating_before=br.rating,
                                    games_played=br.games_played, final_rank=p["final_rank"]))
        changes = calculate_multiplayer_elo(prs, self.elo_config)
        for ch in changes:
            pd = next(p for p in participants if p["bot_id"] == ch.player_id)
            self.conn.execute(
                """UPDATE bot_ratings SET rating=?, peak_rating=MAX(peak_rating,?),
                games_played=games_played+1, wins=wins+?, top3_count=top3_count+?,
                total_kills=total_kills+?, total_minerals=total_minerals+?,
                avg_survival=(avg_survival*games_played+?)/(games_played+1),
                last_played_at=datetime('now') WHERE bot_id=? AND season_id=?""",
                (ch.rating_after, ch.rating_after,
                 1 if ch.final_rank == 1 else 0, 1 if ch.final_rank <= 3 else 0,
                 pd.get("kills", 0), pd.get("minerals_mined", 0), pd.get("survival_ticks", 0),
                 ch.player_id, season_id))
            self.conn.execute(
                """INSERT INTO rating_history (bot_id,season_id,game_id,rating_before,rating_after,rating_delta,final_rank)
                VALUES (?,?,?,?,?,?,?)""",
                (ch.player_id, season_id, game_id, ch.rating_before, ch.rating_after, ch.rating_delta, ch.final_rank))
        self.conn.commit(); return changes

    def get_leaderboard(self, season_id: int, limit: int = 50, min_games: int = 3) -> list[dict]:
        rows = self.conn.execute(
            """SELECT br.*, b.name AS bot_name, u.display_name AS owner_name
            FROM bot_ratings br JOIN bots b ON b.id=br.bot_id JOIN users u ON u.id=b.user_id
            WHERE br.season_id=? AND br.games_played>=? AND b.is_active=1
            ORDER BY br.rating DESC LIMIT ?""", (season_id, min_games, limit)).fetchall()
        res = []
        for i, row in enumerate(rows, 1):
            br = self._to_br(row)
            res.append({"rank": i, "bot_id": br.bot_id, "bot_name": row["bot_name"],
                        "owner": row["owner_name"], "rating": round(br.rating, 1),
                        "peak_rating": round(br.peak_rating, 1), "tier": br.tier,
                        "games_played": br.games_played, "wins": br.wins,
                        "win_rate": round(br.win_rate * 100, 1),
                        "top3_rate": round(br.top3_rate * 100, 1),
                        "total_kills": br.total_kills, "avg_survival": round(br.avg_survival, 1)})
        return res

    def get_rating_history(self, bot_id: int, season_id: int, limit: int = 50) -> list[RatingHistoryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM rating_history WHERE bot_id=? AND season_id=? ORDER BY recorded_at DESC LIMIT ?",
            (bot_id, season_id, limit)).fetchall()
        return [self._to_rh(r) for r in rows]

    def get_rating_chart_data(self, bot_id: int, season_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT rating_after, final_rank, recorded_at FROM rating_history WHERE bot_id=? AND season_id=? ORDER BY recorded_at ASC",
            (bot_id, season_id)).fetchall()
        return [{"rating": r["rating_after"], "rank": r["final_rank"], "at": r["recorded_at"]} for r in rows]

    def get_bot_stats(self, bot_id: int, season_id: int) -> Optional[dict]:
        br = self.get_rating(bot_id, season_id)
        if not br: return None
        recent = self.get_rating_history(bot_id, season_id, limit=5)
        recent_trend = sum(h.rating_delta for h in recent)
        all_h = self.get_rating_history(bot_id, season_id, limit=100)
        streak = 0
        if all_h:
            is_w = all_h[0].final_rank == 1
            for h in all_h:
                if (h.final_rank == 1) == is_w: streak += 1
                else: break
            if not is_w: streak = -streak
        return {"bot_id": bot_id, "season_id": season_id, "rating": round(br.rating, 1),
                "peak_rating": round(br.peak_rating, 1), "tier": br.tier,
                "games_played": br.games_played, "wins": br.wins,
                "win_rate": round(br.win_rate * 100, 1), "top3_count": br.top3_count,
                "top3_rate": round(br.top3_rate * 100, 1), "total_kills": br.total_kills,
                "total_minerals": br.total_minerals, "avg_survival": round(br.avg_survival, 1),
                "recent_trend": round(recent_trend, 1), "current_streak": streak,
                "is_placement": br.games_played < self.elo_config.placement_games}

    def get_global_stats(self, season_id: int) -> dict:
        r = self.conn.execute(
            """SELECT COUNT(*) as total_bots, AVG(rating) as avg_rating, MAX(rating) as max_rating,
            SUM(games_played)/2 as total_games, SUM(total_kills) as total_kills
            FROM bot_ratings WHERE season_id=? AND games_played>0""", (season_id,)).fetchone()
        return {"season_id": season_id, "total_bots": r["total_bots"] or 0,
                "avg_rating": round(r["avg_rating"] or 1200, 1),
                "max_rating": round(r["max_rating"] or 1200, 1),
                "total_games": int(r["total_games"] or 0), "total_kills": r["total_kills"] or 0}

    def _to_br(self, r) -> BotRating:
        return BotRating(id=r["id"], bot_id=r["bot_id"], season_id=r["season_id"],
                         rating=r["rating"], peak_rating=r["peak_rating"],
                         games_played=r["games_played"], wins=r["wins"], top3_count=r["top3_count"],
                         total_kills=r["total_kills"], total_minerals=r["total_minerals"],
                         avg_survival=r["avg_survival"], last_played_at=r["last_played_at"])

    def _to_rh(self, r) -> RatingHistoryEntry:
        return RatingHistoryEntry(id=r["id"], bot_id=r["bot_id"], season_id=r["season_id"],
                                  game_id=r["game_id"], rating_before=r["rating_before"],
                                  rating_after=r["rating_after"], rating_delta=r["rating_delta"],
                                  final_rank=r["final_rank"], recorded_at=r["recorded_at"])
