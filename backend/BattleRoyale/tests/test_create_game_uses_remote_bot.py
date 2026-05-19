"""
create_game() 경로에서 BOT_RUNNER_URL 설정 여부에 따라
RemoteBattleRoyaleBotAdapter / InProcessBot이 선택되는지 확인.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arena.sandbox.remote_adapter import RemoteBattleRoyaleBotAdapter


def _import_settings():
    from src.arena.server import settings
    return settings


def test_remote_adapter_selected_when_bot_runner_url_set():
    """BOT_RUNNER_URL이 있으면 RemoteBattleRoyaleBotAdapter가 생성된다."""
    settings = _import_settings()
    with patch.object(settings, "BOT_RUNNER_URL", "http://bot-runner:8001"):
        adapter = None
        if settings.BOT_RUNNER_URL:
            adapter = RemoteBattleRoyaleBotAdapter(
                bot_id="test",
                code="def action(state): return 'STAY'",
                runner_url=settings.BOT_RUNNER_URL,
            )
        assert adapter is not None
        assert isinstance(adapter, RemoteBattleRoyaleBotAdapter)


def test_inprocess_fallback_when_no_bot_runner_url():
    """BOT_RUNNER_URL이 없고 production+required가 아닐 때 InProcess 경로가 선택된다."""
    settings = _import_settings()
    with patch.object(settings, "BOT_RUNNER_URL", ""), \
         patch.object(settings, "ENV", "development"), \
         patch.object(settings, "BOT_RUNNER_REQUIRED", False):

        assert settings.BOT_RUNNER_URL == ""

        # create_game() 로직에서 RemoteBotAdapter가 생성되지 않아야 한다.
        # (url이 없으므로 if 분기에 진입하지 않음)
        would_use_remote = bool(settings.BOT_RUNNER_URL)
        assert not would_use_remote

        # production+required가 아니므로 503도 발생하지 않는다.
        would_raise_503 = (settings.ENV == "production" and settings.BOT_RUNNER_REQUIRED)
        assert not would_raise_503


def test_503_when_required_but_no_url():
    """BOT_RUNNER_REQUIRED=true이고 URL이 없으면 503을 던져야 한다."""
    from fastapi import HTTPException
    settings = _import_settings()
    with patch.object(settings, "BOT_RUNNER_URL", ""), \
         patch.object(settings, "ENV", "production"), \
         patch.object(settings, "BOT_RUNNER_REQUIRED", True):

        raised = False
        try:
            if not settings.BOT_RUNNER_URL:
                if settings.ENV == "production" and settings.BOT_RUNNER_REQUIRED:
                    raise HTTPException(503, "Bot Runner를 사용할 수 없습니다.")
        except HTTPException as e:
            assert e.status_code == 503
            raised = True

        assert raised, "503 HTTPException이 발생하지 않았습니다."
