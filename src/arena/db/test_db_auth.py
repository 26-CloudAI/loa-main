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
    AuthService,
    TokenConfig,
    generate_salt,
    hash_password,
    verify_password,
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
        salt = generate_salt()
        pw_hash = hash_password("pass123", salt)
        user = self.users.create(username, f"Test {username}", pw_hash, salt)
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

    def test_get_nonexistent(self):
        self.assertIsNone(self.users.get_by_id(9999))
        self.assertIsNone(self.users.get_by_username("ghost"))

    def test_duplicate_username(self):
        self._create_test_user("bob")
        with self.assertRaises(Exception):
            self._create_test_user("bob")

    def test_username_exists(self):
        self._create_test_user("charlie")
        self.assertTrue(self.users.username_exists("charlie"))
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
        game = self.games.create_game("g-001", total_bots=5, seed=42)
        self.assertEqual(game.id, "g-001")
        self.assertEqual(game.status, "waiting")
        self.assertEqual(game.total_bots, 5)

    def test_update_started(self):
        self.games.create_game("g-002", 4)
        self.games.update_game_started("g-002")
        game = self.games.get_game("g-002")
        self.assertEqual(game.status, "running")
        self.assertIsNotNone(game.started_at)

    def test_update_finished(self):
        self.games.create_game("g-003", 4)
        self.games.update_game_finished("g-003", 250, "last_standing")
        game = self.games.get_game("g-003")
        self.assertEqual(game.status, "finished")
        self.assertEqual(game.final_tick, 250)

    def test_participants(self):
        uid = self._create_test_user()
        bot = self.bots.create(uid, "bot_a", "def action(s): return 'STAY'")
        self.games.create_game("g-004", 3)
        self.games.add_participant("g-004", "bot_a", bot_id=bot.id)
        self.games.add_participant("g-004", "AI_초식_00", is_ai_filler=True)

        parts = self.games.get_participants("g-004")
        self.assertEqual(len(parts), 2)
        self.assertFalse(parts[0].is_ai_filler)
        self.assertTrue(parts[1].is_ai_filler)

    def test_participant_results(self):
        self.games.create_game("g-005", 2)
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
        for i in range(5):
            self.games.create_game(f"g-{i:03d}", 4)
        recent = self.games.get_recent_games(3)
        self.assertEqual(len(recent), 3)


# ──────────────────────────────────────────────
#  4. 비밀번호 해싱
# ──────────────────────────────────────────────

class TestPasswordHashing(unittest.TestCase):
    def test_hash_and_verify(self):
        salt = generate_salt()
        pw_hash = hash_password("mypassword", salt)
        self.assertTrue(verify_password("mypassword", salt, pw_hash))
        self.assertFalse(verify_password("wrongpassword", salt, pw_hash))

    def test_different_salts(self):
        salt1 = generate_salt()
        salt2 = generate_salt()
        h1 = hash_password("same_pass", salt1)
        h2 = hash_password("same_pass", salt2)
        self.assertNotEqual(h1, h2)

    def test_salt_length(self):
        salt = generate_salt()
        self.assertEqual(len(bytes.fromhex(salt)), 32)


# ──────────────────────────────────────────────
#  5. JWT 토큰
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
            expires_in=-1,  # 이미 만료
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
        parts[1] = parts[1] + "x"  # 페이로드 변조
        tampered = ".".join(parts)
        payload = decode_token(tampered, self.config)
        self.assertIsNone(payload)

    def test_malformed_token(self):
        self.assertIsNone(decode_token("not.a.valid.token.at.all", self.config))
        self.assertIsNone(decode_token("garbage", self.config))
        self.assertIsNone(decode_token("", self.config))


# ──────────────────────────────────────────────
#  6. AuthService
# ──────────────────────────────────────────────

class TestAuthService(DBTestBase):
    def setUp(self):
        super().setUp()
        self.token_config = TokenConfig(secret_key="test-secret")
        self.auth = AuthService(self.users, self.token_config)

    def test_register_success(self):
        ok, msg, data = self.auth.register("alice", "pass123", "Alice")
        self.assertTrue(ok)
        self.assertIn("id", data)
        self.assertEqual(data["username"], "alice")

    def test_register_duplicate(self):
        self.auth.register("bob", "pass123")
        ok, msg, _ = self.auth.register("bob", "pass456")
        self.assertFalse(ok)
        self.assertIn("이미", msg)

    def test_register_short_username(self):
        ok, msg, _ = self.auth.register("ab", "pass123")
        self.assertFalse(ok)

    def test_register_short_password(self):
        ok, msg, _ = self.auth.register("validuser", "12345")
        self.assertFalse(ok)

    def test_login_success(self):
        self.auth.register("charlie", "secure123")
        ok, msg, data = self.auth.login("charlie", "secure123")
        self.assertTrue(ok)
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["username"], "charlie")

    def test_login_wrong_password(self):
        self.auth.register("dave", "correct")
        ok, msg, _ = self.auth.login("dave", "wrong")
        self.assertFalse(ok)

    def test_login_nonexistent(self):
        ok, msg, _ = self.auth.login("ghost", "pass")
        self.assertFalse(ok)

    def test_login_deactivated(self):
        self.auth.register("eve", "pass123")
        user = self.users.get_by_username("eve")
        self.users.deactivate(user.id)
        ok, msg, _ = self.auth.login("eve", "pass123")
        self.assertFalse(ok)

    def test_authenticate_token(self):
        self.auth.register("frank", "pass123")
        _, _, data = self.auth.login("frank", "pass123")
        payload = self.auth.authenticate_token(data["access_token"])
        self.assertIsNotNone(payload)
        self.assertEqual(payload["username"], "frank")

    def test_authenticate_bad_token(self):
        result = self.auth.authenticate_token("garbage.token.here")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
