"""ResilientPgConnection — 끊긴 psycopg2 커넥션 자가복구 단위 테스트.

실제 PostgreSQL/도커 불필요. 가짜 커넥션으로 'connection already closed' 상황을 시뮬레이션해
래퍼가 다음 사용 시점에 투명하게 재연결하는지 검증.

실행: cd backend && python -m pytest battle_royale/tests/test_db_resilience.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))   # battle_royale/ → src.arena.*

from src.arena.db.schema import ResilientPgConnection  # noqa: E402


class _FakeError(Exception):
    """psycopg2.Error 대역."""


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, *a, **k):
        if self.conn.closed:
            raise _FakeError("connection already closed")
        self.conn.executed.append(a)


class _FakeConn:
    def __init__(self):
        self.closed = 0
        self.executed = []
        self.committed = False
        self.rolled_back = False

    def cursor(self, *a, **k):
        if self.closed:
            raise _FakeError("connection already closed")
        return _FakeCursor(self)

    def commit(self):
        if self.closed:
            raise _FakeError("connection already closed")
        self.committed = True

    def rollback(self):
        if self.closed:
            raise _FakeError("connection already closed")
        self.rolled_back = True

    def close(self):
        self.closed = 1


def _factory():
    """connect_fn + 생성된 커넥션 추적 리스트 반환."""
    conns = []

    def connect_fn():
        c = _FakeConn()
        conns.append(c)
        return c

    return connect_fn, conns


def test_uses_initial_then_reconnects_when_closed():
    """정상 사용 → 커넥션 idle 로 closed → 다음 사용 시 자동 재연결."""
    connect_fn, conns = _factory()
    rc = ResilientPgConnection(connect_fn, _FakeError, initial=connect_fn())
    assert len(conns) == 1
    rc.cursor()                       # 최초 커넥션 사용 OK
    assert len(conns) == 1

    conns[0].closed = 1               # idle 로 끊김
    cur = rc.cursor()                 # 다음 사용 → 자동 재연결
    assert len(conns) == 2            # 새 커넥션 생성됨
    assert rc.closed == 0             # 래퍼는 살아있음
    cur.execute("SELECT 1")
    rc.commit()
    assert conns[1].committed is True


def test_cursor_retries_when_error_at_use():
    """_live() 시점엔 closed=0 이지만 cursor() 호출 순간 끊김 에러 → 1회 재연결 후 재시도."""
    connect_fn, conns = _factory()
    rc = ResilientPgConnection(connect_fn, _FakeError)
    assert len(conns) == 1

    def boom(*a, **k):
        raise _FakeError("server closed the connection unexpectedly")

    conns[0].cursor = boom            # closed=0 인데 cursor() 가 터지는 상황
    cur = rc.cursor()                 # 에러 → 재연결 → 성공
    assert len(conns) == 2
    assert cur is not None


def test_rollback_and_close_safe_on_dead_conn():
    """죽은 커넥션에 rollback/close 호출해도 예외가 새지 않음."""
    connect_fn, conns = _factory()
    rc = ResilientPgConnection(connect_fn, _FakeError)
    conns[0].closed = 1
    rc.rollback()                     # no-op (이미 closed)
    rc.close()                        # no-op
    # 예외 없이 통과하면 성공


def test_delegates_unknown_attrs_to_live_conn():
    """정의 안 한 속성(autocommit 등)은 살아있는 커넥션에 위임."""
    connect_fn, conns = _factory()
    conns_initial = connect_fn()
    conns_initial.autocommit = False
    rc = ResilientPgConnection(connect_fn, _FakeError, initial=conns_initial)
    assert rc.autocommit is False     # __getattr__ 위임
