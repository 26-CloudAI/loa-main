"""
AI Arena — DB + 인증 레이어 테스트

외부 의존성 없이 표준 라이브러리만으로 실행 가능.
SQLite는 인메모리 DB 사용 (:memory:).
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arena.db.schema import init_db
from src.arena.db.user_repo import UserRepository
from src.arena.db.bot_repo import BotRepository
from src.arena.db.game_repo import GameRepository
from src.arena.auth.auth_service import (
    FirebaseUserService,
    TokenConfig,
    create_token,
    decode_token,
)


class DBTestBase(unittest.TestCase):
    """DB 테스트 공통 setUp."""

    def setUp(self):
        self.conn = init_db(":memory:")
        self.users = UserRepository(self.conn)
        self.bots = BotRepository(self.conn)
        self.games = GameRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def _create_test_user(self, username="testuser") -> int:
        """Firebase UID 기반으로 테스트 유저 생성."""
        firebase_uid = f"firebase_uid_{username}"
        user = self.users.create(
            firebase_uid,
            username,
            f"Test {username}",
            email=f"{username}@test.com",
            auth_provider="google.com",
        )
        return user.id


# ──────────────────────────────────────────────
#  1. 유저 리포지토리
# ──────────────────────────────────────────────

class TestUserRepo(DBTestBase):
    def test_create_and_get(self):
        uid = self._create_test_user()
        user = self.users.get_by_id(uid)
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.display_name, "Test testuser")
        self.assertTrue(user.is_active)

    def test_get_by_username(self):
        self._create_test_user("alice")
        user = self.users.get_by_username("alice")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "alice")

    def test_get_by_firebase_uid(self):
        self._create_test_user("bob")
        user = self.users.get_by_firebase_uid("firebase_uid_bob")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "bob")

    def test_get_nonexistent(self):
        self.assertIsNone(self.users.get_by_id(9999))
        self.assertIsNone(self.users.get_by_username("ghost"))
        self.assertIsNone(self.users.get_by_firebase_uid("no_such_uid"))

    def test_duplicate_username(self):
        self._create_test_user("charlie")
        with self.assertRaises(Exception):
            self._create_test_user("charlie")

    def test_username_exists(self):
        self._create_test_user("dave")
        self.assertTrue(self.users.username_exists("dave"))
        self.assertFalse(self.users.username_exists("nobody"))

    def test_update_display_name(self):
        uid = self._create_test_user()
        self.users.update_display_name(uid, "New Name")
        user = self.users.get_by_id(uid)
        self.assertEqual(user.display_name, "New Name")

    def test_deactivate(self):
        uid = self._create_test_user()
        self.users.deactivate(uid)
        user = self.users.get_by_id(uid)
        self.assertFalse(user.is_active)

    def test_update_last_login(self):
        uid = self._create_test_user()
        self.users.update_last_login(uid)
        user = self.users.get_by_id(uid)
        self.assertIsNotNone(user.last_login_at)


# ──────────────────────────────────────────────
#  2. 봇 리포지토리
# ──────────────────────────────────────────────

class TestBotRepo(DBTestBase):
    def test_create_and_get(self):
        uid = self._create_test_user()
        bot = self.bots.create(uid, "my_bot", "def action(s): return 'STAY'", "첫 봇")
        self.assertIsNotNone(bot)
        self.assertEqual(bot.name, "my_bot")
        self.assertEqual(bot.version, 1)
        self.assertEqual(bot.user_id, uid)

    def test_get_by_user(self):
        uid = self._create_test_user()
        self.bots.create(uid, "bot_a", "def action(s): return 'STAY'")
        self.bots.create(uid, "bot_b", "def action(s): return 'MINE'")
        bots = self.bots.get_by_user(uid)
        self.assertEqual(len(bots), 2)

    def test_update_code_increments_version(self):
        uid = self._create_test_user()
        bot = self.bots.create(uid, "v_bot", "def action(s): return 'STAY'")
        updated = self.bots.update_code(bot.id, "def action(s): return 'MINE'")
        self.assertEqual(updated.version, 2)
        self.assertIn("MINE", updated.code)

    def test_soft_delete(self):
        uid = self._create_test_user()
        bot = self.bots.create(uid, "del_bot", "def action(s): return 'STAY'")
        self.bots.soft_delete(bot.id)
        active = self.bots.get_by_user(uid, active_only=True)
        all_bots = self.bots.get_by_user(uid, active_only=False)
        self.assertEqual(len(active), 0)
        self.assertEqual(len(all_bots), 1)

    def test_duplicate_name_per_user(self):
        uid = self._create_test_user()
        self.bots.create(uid, "same_name", "def action(s): return 'STAY'")
        with self.assertRaises(Exception):
            self.bots.create(uid, "same_name", "def action(s): return 'MINE'")

    def test_different_users_same_name(self):
        uid1 = self._create_test_user("user1")
        uid2 = self._create_test_user("user2")
        b1 = self.bots.create(uid1, "bot_x", "def action(s): return 'STAY'")
        b2 = self.bots.create(uid2, "bot_x", "def action(s): return 'MINE'")
        self.assertNotEqual(b1.id, b2.id)

    def test_record_game_result(self):
        uid = self._create_test_user()
        bot = self.bots.create(uid, "stats_bot", "def action(s): return 'STAY'")
        self.bots.record_game_result(bot.id, won=True)
        self.bots.record_game_result(bot.id, won=False)
        self.bots.record_game_result(bot.id, won=True)

        updated = self.bots.get_by_id(bot.id)
        self.assertEqual(updated.wins, 2)
        self.assertEqual(updated.losses, 1)
        self.assertEqual(updated.games_played, 3)
        self.assertAlmostEqual(updated.win_rate, 2 / 3)

    def test_validate_code_valid(self):
        ok, msg = self.bots.validate_code("def action(state):\n    return 'STAY'")
        self.assertTrue(ok)

    def test_validate_code_no_action(self):
        ok, msg = self.bots.validate_code("def foo(x): return x")
        self.assertFalse(ok)
        self.assertIn("action", msg)

    def test_validate_code_syntax_error(self):
        ok, msg = self.bots.validate_code("def action(state:\n  return")
        self.assertFalse(ok)
        self.assertIn("문법", msg)

    def test_validate_code_empty(self):
        ok, msg = self.bots.validate_code("")
        self.assertFalse(ok)

    def test_validate_code_too_large(self):
        ok, msg = self.bots.validate_code("x" * 60_000)
        self.assertFalse(ok)


# ──────────────────────────────────────────────
#  3. 게임 리포지토리
# ──────────────────────────────────────────────

class TestGameRepo(DBTestBase):
    def test_create_and_get(self):
        owner_id = self._create_test_user()
        game = self.games.create_game("g-001", owner_id, total_bots=5, seed=42)
        self.assertEqual(game.id, "g-001")
        self.assertEqual(game.owner_user_id, owner_id)
        self.assertEqual(game.status, "waiting")
        self.assertEqual(game.total_bots, 5)

    def test_update_started(self):
        owner_id = self._create_test_user()
        self.games.create_game("g-002", owner_id, 4)
        self.games.update_game_started("g-002")
        game = self.games.get_game("g-002")
        self.assertEqual(game.status, "running")
        self.assertIsNotNone(game.started_at)

    def test_update_finished(self):
        owner_id = self._create_test_user()
        self.games.create_game("g-003", owner_id, 4)
        self.games.update_game_finished("g-003", 250, "last_standing")
        game = self.games.get_game("g-003")
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.final_tick, 250)

    def test_participants(self):
        uid = self._create_test_user()
        bot = self.bots.create(uid, "bot_a", "def action(s): return 'STAY'")
        self.games.create_game("g-004", uid, 3)
        self.games.add_participant("g-004", "bot_a", bot_id=bot.id)
        self.games.add_participant("g-004", "AI_초식_00", is_ai_filler=True)

        parts = self.games.get_participants("g-004")
        self.assertEqual(len(parts), 2)
        self.assertFalse(parts[0].is_ai_filler)
        self.assertTrue(parts[1].is_ai_filler)

    def test_participant_results(self):
        owner_id = self._create_test_user()
        self.games.create_game("g-005", owner_id, 2)
        self.games.add_participant("g-005", "bot_a")
        self.games.update_participant_result(
            "g-005", "bot_a",
            final_rank=1, final_score=150.5,
            kills=3, minerals_mined=10, survival_ticks=200,
        )
        parts = self.games.get_participants("g-005")
        self.assertEqual(parts[0].final_rank, 1)
        self.assertAlmostEqual(parts[0].final_score, 150.5)

    def test_recent_games(self):
        owner_id = self._create_test_user()
        for i in range(5):
            self.games.create_game(f"g-{i:03d}", owner_id, 4)
        recent = self.games.get_recent_games(3)
        self.assertEqual(len(recent), 3)

    def test_get_game_by_owner(self):
        owner_id = self._create_test_user("owner")
        other_id = self._create_test_user("other")
        self.games.create_game("g-own", owner_id, 2)
        self.assertIsNotNone(self.games.get_game_by_owner("g-own", owner_id))
        self.assertIsNone(self.games.get_game_by_owner("g-own", other_id))

    def test_list_games_by_owner(self):
        owner_id = self._create_test_user("owner2")
        other_id = self._create_test_user("other2")
        self.games.create_game("g-a", owner_id, 2)
        self.games.create_game("g-b", owner_id, 2)
        self.games.create_game("g-c", other_id, 2)
        games = self.games.list_games_by_owner(owner_id)
        self.assertEqual({game.id for game in games}, {"g-a", "g-b"})


# ──────────────────────────────────────────────
#  4. JWT 토큰 (mock_auth용)
# ──────────────────────────────────────────────

class TestJWT(unittest.TestCase):
    def setUp(self):
        self.config = TokenConfig(secret_key="test-secret-key-1234")

    def test_create_and_decode(self):
        token = create_token({"user_id": 42, "username": "alice"}, self.config)
        payload = decode_token(token, self.config)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["user_id"], 42)
        self.assertEqual(payload["username"], "alice")

    def test_expired_token(self):
        token = create_token(
            {"user_id": 1},
            self.config,
            expires_in=-1,
        )
        payload = decode_token(token, self.config)
        self.assertIsNone(payload)

    def test_invalid_signature(self):
        token = create_token({"user_id": 1}, self.config)
        other_config = TokenConfig(secret_key="wrong-key")
        payload = decode_token(token, other_config)
        self.assertIsNone(payload)

    def test_tampered_token(self):
        token = create_token({"user_id": 1}, self.config)
        parts = token.split(".")
        parts[1] = parts[1] + "x"
        tampered = ".".join(parts)
        payload = decode_token(tampered, self.config)
        self.assertIsNone(payload)

    def test_malformed_token(self):
        self.assertIsNone(decode_token("not.a.valid.token.at.all", self.config))
        self.assertIsNone(decode_token("garbage", self.config))
        self.assertIsNone(decode_token("", self.config))


# ──────────────────────────────────────────────
#  5. FirebaseUserService
# ──────────────────────────────────────────────

class TestFirebaseUserService(DBTestBase):
    def setUp(self):
        super().setUp()
        self.firebase_service = FirebaseUserService(self.users)

    def _make_token(self, uid, email="user@test.com", name="Test User"):
        return {
            "uid": uid,
            "email": email,
            "name": name,
            "firebase": {"sign_in_provider": "google.com"},
            "picture": "https://example.com/photo.jpg",
        }

    def test_create_new_user(self):
        token = self._make_token("uid_001", "alice@test.com", "Alice")
        user = self.firebase_service.get_or_create_user(token)
        self.assertIsNotNone(user)
        self.assertEqual(user.firebase_uid, "uid_001")
        self.assertEqual(user.email, "alice@test.com")
        self.assertEqual(user.display_name, "Alice")
        self.assertEqual(user.auth_provider, "google.com")

    def test_get_existing_user(self):
        token = self._make_token("uid_002", "bob@test.com", "Bob")
        user1 = self.firebase_service.get_or_create_user(token)
        user2 = self.firebase_service.get_or_create_user(token)
        self.assertEqual(user1.id, user2.id)

    def test_last_login_updated_on_existing(self):
        token = self._make_token("uid_003")
        self.firebase_service.get_or_create_user(token)
        user = self.firebase_service.get_or_create_user(token)
        self.assertIsNotNone(user.last_login_at)

    def test_username_generated_from_email(self):
        token = self._make_token("uid_004", "charlie@example.com", "Charlie")
        user = self.firebase_service.get_or_create_user(token)
        self.assertEqual(user.username, "charlie")

    def test_username_generated_from_uid_when_no_email(self):
        token = {"uid": "abcdef1234567890", "firebase": {"sign_in_provider": "anonymous"}}
        user = self.firebase_service.get_or_create_user(token)
        self.assertEqual(user.username, "abcdef1234567890")


if __name__ == "__main__":
    unittest.main(verbosity=2)
