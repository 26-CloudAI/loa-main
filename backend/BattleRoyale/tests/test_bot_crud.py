"""BotRepository CRUD 직접 테스트."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBotRepositoryDirect(unittest.TestCase):
    def setUp(self):
        os.environ["DB_TYPE"] = "sqlite"

        self.db_file = tempfile.mktemp(suffix=".db")

        from src.arena.db.schema import init_db
        from src.arena.db.bot_repo import BotRepository
        from src.arena.db.user_repo import UserRepository

        self.conn = init_db(self.db_file)
        self.user_repo = UserRepository(self.conn)
        self.bot_repo = BotRepository(self.conn)

        self.user = self.user_repo.create(
            firebase_uid="test_uid_001",
            username="testuser",
            display_name="Test User",
            email="test@test.com",
        )

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.db_file):
            os.unlink(self.db_file)

    def test_create_bot(self):
        bot = self.bot_repo.create(
            user_id=self.user.id,
            name="bot_alpha",
            code="def action(state):\n    return 'STAY'",
        )

        self.assertIsNotNone(bot.id)
        self.assertEqual(bot.name, "bot_alpha")
        self.assertEqual(bot.version, 1)
        self.assertTrue(bot.is_active)

    def test_get_by_user_only_own_bots(self):
        other_user = self.user_repo.create(
            firebase_uid="test_uid_002",
            username="otheruser",
            display_name="Other User",
            email="other@test.com",
        )

        my_bot = self.bot_repo.create(
            user_id=self.user.id,
            name="my_bot",
            code="def action(state):\n    return 'MINE'",
        )
        self.bot_repo.create(
            user_id=other_user.id,
            name="other_bot",
            code="def action(state):\n    return 'STAY'",
        )

        bots_for_other = self.bot_repo.get_by_user(other_user.id)
        self.assertEqual(len(bots_for_other), 1)
        self.assertNotEqual(bots_for_other[0].id, my_bot.id)
        self.assertEqual(bots_for_other[0].user_id, other_user.id)

    def test_update_code_increments_version(self):
        bot = self.bot_repo.create(
            user_id=self.user.id,
            name="version_bot",
            code="def action(state):\n    return 'STAY'",
        )

        updated = self.bot_repo.update_code(bot.id, "def action(state):\n    return 'MINE'")

        self.assertEqual(updated.version, 2)
        self.assertIn("MINE", updated.code)

    def test_soft_delete_removes_from_list(self):
        bot = self.bot_repo.create(
            user_id=self.user.id,
            name="delete_bot",
            code="def action(state):\n    return 'STAY'",
        )

        self.bot_repo.soft_delete(bot.id)
        active_bots = self.bot_repo.get_by_user(self.user.id)

        self.assertEqual(len(active_bots), 0)

    def test_get_by_id_after_delete(self):
        bot = self.bot_repo.create(
            user_id=self.user.id,
            name="deleted_lookup_bot",
            code="def action(state):\n    return 'STAY'",
        )

        self.bot_repo.soft_delete(bot.id)
        deleted = self.bot_repo.get_by_id(bot.id)

        self.assertIsNotNone(deleted)
        self.assertFalse(deleted.is_active)

    def test_validate_code_valid(self):
        ok, msg = self.bot_repo.validate_code("def action(state):\n    return 'STAY'")

        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_validate_code_missing_action(self):
        ok, msg = self.bot_repo.validate_code("def run(state):\n    return 'STAY'")

        self.assertFalse(ok)
        self.assertNotEqual(msg, "")


if __name__ == "__main__":
    unittest.main()
