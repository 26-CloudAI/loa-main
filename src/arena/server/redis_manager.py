"""
AI Arena — Redis 매니저

역할:
  1. 게임 상태(틱 데이터)를 Redis에 저장/조회
  2. Pub/Sub 채널로 틱 데이터를 브로드캐스팅
  3. 게임 결과를 영구 저장

Redis가 없는 개발 환경을 위해 인메모리 폴백 구현체도 제공.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import AsyncIterator, Callable, Optional

from .config import RedisConfig

logger = logging.getLogger(__name__)


class StateStore(ABC):
    """게임 상태 저장소 추상 인터페이스."""

    @abstractmethod
    async def save_game_state(self, game_id: str, data: dict) -> None:
        """현재 게임 상태를 저장 (덮어쓰기)."""
        ...

    @abstractmethod
    async def get_game_state(self, game_id: str) -> Optional[dict]:
        """현재 게임 상태를 조회."""
        ...

    @abstractmethod
    async def save_game_result(self, game_id: str, result: dict) -> None:
        """게임 결과를 저장."""
        ...

    @abstractmethod
    async def get_game_result(self, game_id: str) -> Optional[dict]:
        """게임 결과를 조회."""
        ...

    @abstractmethod
    async def delete_game(self, game_id: str) -> None:
        """게임 데이터를 삭제."""
        ...

    @abstractmethod
    async def list_games(self) -> list[str]:
        """활성 게임 ID 목록."""
        ...


class PubSubBroker(ABC):
    """Pub/Sub 브로커 추상 인터페이스."""

    @abstractmethod
    async def publish(self, channel: str, message: dict) -> None:
        """채널에 메시지를 발행."""
        ...

    @abstractmethod
    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        """채널을 구독하고 메시지를 비동기 반복."""
        ...

    @abstractmethod
    async def unsubscribe(self, channel: str) -> None:
        """채널 구독 해제."""
        ...


# ──────────────────────────────────────────────
#  Redis 구현체
# ──────────────────────────────────────────────

class RedisStateStore(StateStore):
    """Redis 기반 상태 저장소."""

    def __init__(self, config: RedisConfig):
        self.config = config
        self._redis = None

    async def connect(self):
        try:
            import redis.asyncio as aioredis
        except ImportError:
            raise RuntimeError(
                "redis 패키지가 필요합니다. 'pip install redis' 실행하세요."
            )
        self._redis = aioredis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            password=self.config.password,
            decode_responses=True,
        )
        await self._redis.ping()
        logger.info("Redis 연결 성공: %s:%d", self.config.host, self.config.port)

    async def close(self):
        if self._redis:
            await self._redis.close()

    def _key(self, *parts: str) -> str:
        return self.config.key_prefix + ":".join(parts)

    async def save_game_state(self, game_id: str, data: dict) -> None:
        key = self._key("game", game_id, "state")
        await self._redis.set(key, json.dumps(data), ex=self.config.game_state_ttl)

    async def get_game_state(self, game_id: str) -> Optional[dict]:
        key = self._key("game", game_id, "state")
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    async def save_game_result(self, game_id: str, result: dict) -> None:
        key = self._key("game", game_id, "result")
        await self._redis.set(key, json.dumps(result), ex=self.config.game_result_ttl)

    async def get_game_result(self, game_id: str) -> Optional[dict]:
        key = self._key("game", game_id, "result")
        raw = await self._redis.get(key)
        return json.loads(raw) if raw else None

    async def delete_game(self, game_id: str) -> None:
        keys = [
            self._key("game", game_id, "state"),
            self._key("game", game_id, "result"),
        ]
        await self._redis.delete(*keys)

    async def list_games(self) -> list[str]:
        pattern = self._key("game", "*", "state")
        keys = []
        async for key in self._redis.scan_iter(match=pattern):
            # arena:game:{id}:state → id 추출
            parts = key.split(":")
            if len(parts) >= 4:
                keys.append(parts[2])
        return keys


class RedisPubSubBroker(PubSubBroker):
    """Redis Pub/Sub 기반 브로커."""

    def __init__(self, config: RedisConfig):
        self.config = config
        self._redis = None
        self._pubsub = None

    async def connect(self):
        try:
            import redis.asyncio as aioredis
        except ImportError:
            raise RuntimeError("redis 패키지가 필요합니다.")
        self._redis = aioredis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            password=self.config.password,
            decode_responses=True,
        )

    async def close(self):
        if self._redis:
            await self._redis.close()

    async def publish(self, channel: str, message: dict) -> None:
        await self._redis.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)

        try:
            async for raw_message in pubsub.listen():
                if raw_message["type"] != "message":
                    continue
                try:
                    data = json.loads(raw_message["data"])
                    yield data
                except json.JSONDecodeError:
                    logger.warning("Pub/Sub JSON 파싱 실패: %s", raw_message["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def unsubscribe(self, channel: str) -> None:
        pass  # subscribe의 finally에서 처리


# ──────────────────────────────────────────────
#  인메모리 폴백 (개발/테스트용)
# ──────────────────────────────────────────────

class InMemoryStateStore(StateStore):
    """Redis 없이 동작하는 인메모리 저장소."""

    def __init__(self):
        self._states: dict[str, dict] = {}
        self._results: dict[str, dict] = {}

    async def save_game_state(self, game_id: str, data: dict) -> None:
        self._states[game_id] = data

    async def get_game_state(self, game_id: str) -> Optional[dict]:
        return self._states.get(game_id)

    async def save_game_result(self, game_id: str, result: dict) -> None:
        self._results[game_id] = result

    async def get_game_result(self, game_id: str) -> Optional[dict]:
        return self._results.get(game_id)

    async def delete_game(self, game_id: str) -> None:
        self._states.pop(game_id, None)
        self._results.pop(game_id, None)

    async def list_games(self) -> list[str]:
        return list(self._states.keys())


class InMemoryPubSubBroker(PubSubBroker):
    """Redis 없이 동작하는 인메모리 Pub/Sub."""

    def __init__(self):
        # 채널 → 구독자 큐 목록
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    async def publish(self, channel: str, message: dict) -> None:
        for queue in self._subscribers.get(channel, []):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # 느린 구독자 → 가장 오래된 메시지 드롭
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    pass

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers[channel].append(queue)
        try:
            while True:
                message = await queue.get()
                yield message
        finally:
            self._subscribers[channel].remove(queue)

    async def unsubscribe(self, channel: str) -> None:
        pass


# ──────────────────────────────────────────────
#  팩토리
# ──────────────────────────────────────────────

async def create_state_store(config: RedisConfig, use_redis: bool = True) -> StateStore:
    """환경에 맞는 StateStore를 생성한다."""
    if not use_redis:
        logger.info("인메모리 StateStore 사용 (개발 모드)")
        return InMemoryStateStore()

    try:
        store = RedisStateStore(config)
        await store.connect()
        return store
    except Exception as e:
        logger.warning("Redis 연결 실패, 인메모리 폴백: %s", e)
        return InMemoryStateStore()


async def create_pubsub_broker(config: RedisConfig, use_redis: bool = True) -> PubSubBroker:
    """환경에 맞는 PubSubBroker를 생성한다."""
    if not use_redis:
        logger.info("인메모리 PubSubBroker 사용 (개발 모드)")
        return InMemoryPubSubBroker()

    try:
        broker = RedisPubSubBroker(config)
        await broker.connect()
        return broker
    except Exception as e:
        logger.warning("Redis Pub/Sub 연결 실패, 인메모리 폴백: %s", e)
        return InMemoryPubSubBroker()
