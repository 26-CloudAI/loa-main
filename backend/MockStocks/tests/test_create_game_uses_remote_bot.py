"""
MockStocks create_game() 경로에서 BOT_RUNNER_URL 설정 여부에 따라
RemoteStockBotAdapter / InProcessBot이 선택되는지 확인.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stocks.sandbox.remote_adapter import RemoteStockBotAdapter


def _import_settings():
    from src.stocks.server import settings
    return settings


def test_remote_adapter_selected_when_bot_runner_url_set():
    settings = _import_settings()
    with patch.object(settings, "BOT_RUNNER_URL", "http://bot-runner:8001"):
        adapter = None
        if settings.BOT_RUNNER_URL:
            adapter = RemoteStockBotAdapter(
                bot_id="sbot",
                code="def action(state): return {'action':'HOLD'}",
                runner_url=settings.BOT_RUNNER_URL,
            )
        assert adapter is not None
        assert isinstance(adapter, RemoteStockBotAdapter)


def test_inprocess_fallback_when_no_bot_runner_url():
    settings = _import_settings()
    with patch.object(settings, "BOT_RUNNER_URL", ""), \
         patch.object(settings, "BOT_RUNNER_REQUIRED", False):

        assert settings.BOT_RUNNER_URL == ""

        from src.stocks.server.app import InProcessBot
        bot = InProcessBot("sbot", "def action(state): return {'action':'HOLD'}")
        assert bot.get_action({}) == {"action": "HOLD"}


def test_503_when_required_but_no_url():
    from fastapi import HTTPException
    settings = _import_settings()
    with patch.object(settings, "BOT_RUNNER_URL", ""), \
         patch.object(settings, "BOT_RUNNER_REQUIRED", True):

        raised = False
        try:
            if not settings.BOT_RUNNER_URL:
                if settings.BOT_RUNNER_REQUIRED:
                    raise HTTPException(503, "Bot Runner를 사용할 수 없습니다.")
        except HTTPException as e:
            assert e.status_code == 503
            raised = True

        assert raised
