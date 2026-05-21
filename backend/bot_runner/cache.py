"""
Thread-safe LRU cache for validated bot source code.

Key   : code_hash (SHA-256 hex, computed by the game server's RemoteBotAdapter)
Value : source code string (policy-checked, ready to compile)

Note: Python 3.14+ does not support pickling code objects across processes,
so we cache source strings and compile inside each child process.
"""

from __future__ import annotations

import threading

from cachetools import LRUCache

_cache: LRUCache = LRUCache(maxsize=512)
_lock = threading.Lock()


def get(code_hash: str) -> str | None:
    with _lock:
        return _cache.get(code_hash)


def put(code_hash: str, source: str) -> None:
    with _lock:
        _cache[code_hash] = source
