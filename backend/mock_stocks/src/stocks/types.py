from dataclasses import dataclass, field
from enum import Enum


class OrderType(str, Enum):
    BUY     = "BUY"      # 매수
    SELL    = "SELL"     # 매도
    SHORT   = "SHORT"    # 공매도 (신용점수 800 이상 필요)
    COVER   = "COVER"    # 공매도 청산 (매수 상환)
    INQUIRY = "INQUIRY"  # 정보 탐색 (다음 틱에 힌트 제공)
    HOLD    = "HOLD"     # 대기 (현금 이자 발생)


@dataclass
class Order:
    action: OrderType
    symbol: str = ""
    quantity: int = 0


@dataclass
class LongPosition:
    quantity: int
    avg_cost: float        # 평균 매수 단가


@dataclass
class ShortPosition:
    quantity: int
    avg_sell_price: float  # 공매도 당시 평균 매도가
    margin: float          # 예치 증거금


@dataclass
class StockData:
    symbol: str
    name: str
    sector: str
    price: float
    initial_price: float
    price_history: list[float]   # 최근 N턴 가격
    change_pct: float            # 직전 턴 대비 변동률 (%)
    delisted: bool = False


@dataclass
class NewsEvent:
    symbol: str
    headline: str
    delta_mu: float    # μ 변화량 (양수=호재, 음수=악재)
    ticks_remaining: int


@dataclass
class BotState:
    bot_id: str
    cash: float
    credit_score: int
    long_positions: dict[str, LongPosition] = field(default_factory=dict)
    short_positions: dict[str, ShortPosition] = field(default_factory=dict)
    total_value: float = 0.0
    last_inquiry_hint: str = ""   # INQUIRY 행동 결과 힌트


@dataclass
class GameResult:
    final_tick: int
    rankings: list[dict]
