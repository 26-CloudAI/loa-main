from dataclasses import dataclass, field


@dataclass
class StockSpec:
    symbol: str
    name: str
    sector: str
    initial_price: float
    mu: float     # 턴당 기대수익률
    sigma: float  # 턴당 변동성


# 15개 종목 — 섹터별 μ/σ 상이
STOCKS: list[StockSpec] = [
    StockSpec("NeoChips",      "네오칩스",      "반도체",          50_000,  0.0010, 0.040),
    StockSpec("CodeBase",      "코드베이스",    "소프트웨어",      80_000,  0.0020, 0.020),
    StockSpec("FusionGrid",    "퓨전그리드",    "신재생에너지",    35_000,  0.0010, 0.025),
    StockSpec("GenomX",        "제놈엑스",      "바이오",         120_000,  0.0020, 0.050),
    StockSpec("PlayVerse",     "플레이버스",    "게임/메타버스",   45_000,  0.0010, 0.035),
    StockSpec("VoltMotors",    "볼트모터스",    "전기차",          95_000,  0.0015, 0.040),
    StockSpec("EtherBank",     "이더뱅크",      "금융",            60_000,  0.0005, 0.015),
    StockSpec("TrendHub",      "트렌드허브",    "이커머스",        70_000,  0.0010, 0.025),
    StockSpec("OrbitalLink",   "오비탈링크",    "우주항공",        85_000,  0.0020, 0.045),
    StockSpec("GreenHarvest",  "그린하베스트",  "농업/푸드테크",   25_000,  0.0005, 0.018),
    StockSpec("QuantumLeap",   "퀀텀리프",      "양자컴퓨팅",     200_000,  0.0030, 0.060),
    StockSpec("DataMine",      "데이터마인",    "빅데이터/AI",     65_000,  0.0020, 0.030),
    StockSpec("BlueWave",      "블루웨이브",    "해운/물류",       30_000,  0.0005, 0.025),
    StockSpec("SteelGuardian", "스틸가디언",    "철강/방산",       40_000,  0.0005, 0.022),
    StockSpec("CoreREITs",     "코어리츠",      "부동산",          55_000,  0.0005, 0.012),
]


@dataclass
class NewsConfig:
    interval_min: int = 10      # 뉴스 발생 최소 간격 (턴)
    interval_max: int = 20      # 뉴스 발생 최대 간격 (턴)
    effect_duration_min: int = 5   # 뉴스 효과 지속 최소 (턴)
    effect_duration_max: int = 10  # 뉴스 효과 지속 최대 (턴)
    delta_mu_min: float = 0.005    # μ 변화량 최솟값
    delta_mu_max: float = 0.015    # μ 변화량 최댓값


@dataclass
class CreditConfig:
    initial_score: int = 1_000
    short_min_score: int = 800     # 공매도 가능 최소 신용 점수
    short_max_asset_ratio: float = 0.50  # 공매도 한도: 총 자산의 50%
    fee_standard: float = 0.0015   # 기본 수수료 0.15%
    fee_minimum: float = 0.0010    # 최저 수수료 0.10%
    fee_min_score: int = 1_200     # 최저 수수료 적용 신용 점수


@dataclass
class GameConfig:
    total_ticks: int = 200
    tick_interval: float = 0.1
    starting_cash: float = 100_000_000.0   # 1억 원
    max_bots: int = 20
    min_bots: int = 2
    cash_interest_rate: float = 0.0001     # 대기(HOLD) 시 현금 이자 0.01%/턴
    delisting_threshold: float = 0.05      # 초기가의 5% 미만이면 상장폐지 경고
    delisting_ticks: int = 5               # 5턴 유지 시 상장 폐지
    history_window: int = 10               # 제공 히스토리 길이


@dataclass
class Config:
    stocks: list[StockSpec] = field(default_factory=lambda: list(STOCKS))
    news: NewsConfig = field(default_factory=NewsConfig)
    credit: CreditConfig = field(default_factory=CreditConfig)
    game: GameConfig = field(default_factory=GameConfig)


DEFAULT_CONFIG = Config()
