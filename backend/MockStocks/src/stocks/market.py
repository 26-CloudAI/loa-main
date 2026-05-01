"""
MockStocks — 주식 시장 시뮬레이터

- 종목별 고유 μ/σ 로 GBM 적용
- 10~20턴마다 Gemini AI가 뉴스 이벤트 생성 (키 없으면 템플릿 폴백)
- 상장폐지: 초기가의 5% 미만 5턴 유지 시 퇴출
"""

import json
import logging
import random
from .config import Config, DEFAULT_CONFIG, StockSpec
from .types import StockData, NewsEvent

logger = logging.getLogger(__name__)

# Gemini API 키 로드 (없으면 None)
try:
    from gemini_key import GEMINI_API_KEY as _GEMINI_KEY
    if _GEMINI_KEY == "여기에_Gemini_API_키_입력":
        _GEMINI_KEY = None
except ImportError:
    _GEMINI_KEY = None

# 폴백용 템플릿 (Gemini 미사용 시)
_NEWS_TEMPLATES = [
    ("{name}, 신규 대형 계약 체결 발표 — 주가 강세 전망", +1),
    ("{name}, 예상치 상회하는 실적 발표", +1),
    ("{name} 경영진 대규모 자사주 매입 결정", +1),
    ("{name}, 글로벌 파트너십 체결", +1),
    ("{name}, 혁신 제품 출시로 시장 주목", +1),
    ("{name}, 분기 실적 부진 — 매출 감소", -1),
    ("{name} 핵심 임원 대거 사임 소식", -1),
    ("{name}, 규제 당국 조사 착수", -1),
    ("{name} 회계 부정 의혹 제기", -1),
    ("{name}, 주요 고객사 이탈로 수익 악화 우려", -1),
]


def _call_gemini(prompt: str, timeout: int = 30) -> str | None:
    """Gemini REST API 단일 호출. 응답 텍스트 반환, 실패 시 None."""
    if not _GEMINI_KEY:
        return None
    try:
        import urllib.request
        url = (
            "https://generativelanguage.googleapis.com/v1beta"
            f"/models/gemini-2.5-flash:generateContent?key={_GEMINI_KEY}"
        )
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}]
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.warning("Gemini API 호출 실패: %s", e)
        return None


def _extract_json(text: str, expect_array: bool = False) -> str:
    """응답에서 JSON 부분만 추출."""
    if "```" in text:
        for part in text.split("```"):
            part = part.strip().lstrip("json").strip()
            start = "[" if expect_array else "{"
            if part.startswith(start):
                return part
    return text.strip()


class Market:
    def __init__(self, config: Config = DEFAULT_CONFIG, seed: int | None = None):
        self._cfg = config
        self._rng = random.Random(seed)
        self._specs: dict[str, StockSpec] = {s.symbol: s for s in config.stocks}

        self._prices: dict[str, float] = {}
        self._history: dict[str, list[float]] = {}
        self._delisting_counter: dict[str, int] = {}
        self._delisted: set[str] = set()

        self._active_news: list[NewsEvent] = []
        self._news_queue: list[tuple[str, str, int]] = []  # (symbol, headline, direction)
        self._next_news_tick: int = 0
        self._current_tick: int = 0

        self._initialize()

    # ── 초기화 ────────────────────────────────────────────────────────────────

    def _initialize(self) -> None:
        for spec in self._cfg.stocks:
            price = round(spec.initial_price * self._rng.uniform(0.9, 1.1), 0)
            self._prices[spec.symbol] = price
            self._history[spec.symbol] = [price]
            self._delisting_counter[spec.symbol] = 0
        self._schedule_next_news()

    def _schedule_next_news(self) -> None:
        interval = self._rng.randint(
            self._cfg.news.interval_min,
            self._cfg.news.interval_max,
        )
        self._next_news_tick = self._current_tick + interval

    # ── 틱 갱신 ──────────────────────────────────────────────────────────────

    def update(self) -> None:
        self._current_tick += 1
        self._try_generate_news()
        self._update_prices()
        self._tick_news()
        self._check_delisting()

    def _update_prices(self) -> None:
        news_mu: dict[str, float] = {n.symbol: n.delta_mu for n in self._active_news}

        for spec in self._cfg.stocks:
            sym = spec.symbol
            if sym in self._delisted:
                self._prices[sym] = 0.0
                continue

            mu = spec.mu + news_mu.get(sym, 0.0)
            change = mu + spec.sigma * self._rng.gauss(0, 1)
            new_price = max(1.0, round(self._prices[sym] * (1 + change), 0))
            self._prices[sym] = new_price

            hist = self._history[sym]
            hist.append(new_price)
            if len(hist) > self._cfg.game.history_window + 1:
                hist.pop(0)

    def pregenerate_news_batch(self, count: int = 20) -> None:
        """게임 시작 전 Gemini로 뉴스 배열을 한 번에 생성해 큐에 저장."""
        if not _GEMINI_KEY:
            return

        lines = [f"- {s.symbol} ({s.name}, {s.sector})" for s in self._cfg.stocks]
        stocks_text = "\n".join(lines)

        prompt = f"""당신은 한국 주식 시장 뉴스를 생성하는 AI입니다.

종목 목록:
{stocks_text}

아래 조건으로 뉴스 이벤트 {count}개를 생성하세요:
- 헤드라인은 한국어, 언론 기사 제목 스타일 (30~55자)
- 다양한 종목이 골고루 등장하도록 (한 종목 연속 2회 이하)
- 호재(1)와 악재(-1)를 적절히 혼합
- 현실적이고 창의적인 내용

JSON 배열로만 응답하세요 (마크다운·설명 없이):
[{{"symbol": "심볼", "headline": "뉴스 헤드라인", "direction": 1}}, ...]"""

        text = _call_gemini(prompt, timeout=60)
        if not text:
            return

        try:
            text = _extract_json(text, expect_array=True)
            items = json.loads(text)
            valid_symbols = {s.symbol for s in self._cfg.stocks}
            for item in items:
                symbol = str(item["symbol"])
                headline = str(item["headline"])
                direction = int(item["direction"])
                if symbol in valid_symbols and direction in (1, -1):
                    self._news_queue.append((symbol, f"[G] {headline}", direction))
            logger.info("Gemini 뉴스 사전 생성 완료: %d개", len(self._news_queue))
        except Exception as e:
            logger.warning("Gemini 뉴스 배치 파싱 실패: %s", e)

    def _try_generate_news(self) -> None:
        if self._current_tick < self._next_news_tick:
            return

        active_specs = [s for s in self._cfg.stocks if s.symbol not in self._delisted]
        if not active_specs:
            return

        active_symbols = {s.symbol for s in active_specs}

        # 큐에서 꺼내기 (사전 생성된 Gemini 뉴스)
        symbol, headline, direction = None, None, None
        while self._news_queue:
            sym, hl, d = self._news_queue.pop(0)
            if sym in active_symbols:
                symbol, headline, direction = sym, hl, d
                break

        # 큐가 비었거나 유효한 항목 없으면 템플릿 폴백
        if symbol is None:
            spec = self._rng.choice(active_specs)
            template, direction = self._rng.choice(_NEWS_TEMPLATES)
            headline = template.format(name=spec.name)
            symbol = spec.symbol

        delta_mu = direction * self._rng.uniform(
            self._cfg.news.delta_mu_min,
            self._cfg.news.delta_mu_max,
        )
        duration = self._rng.randint(
            self._cfg.news.effect_duration_min,
            self._cfg.news.effect_duration_max,
        )
        self._active_news.append(NewsEvent(
            symbol=symbol,
            headline=headline,
            delta_mu=delta_mu,
            ticks_remaining=duration,
        ))
        self._schedule_next_news()

    def _tick_news(self) -> None:
        for news in self._active_news:
            news.ticks_remaining -= 1
        self._active_news = [n for n in self._active_news if n.ticks_remaining > 0]

    def _check_delisting(self) -> None:
        for spec in self._cfg.stocks:
            sym = spec.symbol
            if sym in self._delisted:
                continue
            threshold = spec.initial_price * self._cfg.game.delisting_threshold
            if self._prices[sym] < threshold:
                self._delisting_counter[sym] += 1
                if self._delisting_counter[sym] >= self._cfg.game.delisting_ticks:
                    self._delisted.add(sym)
                    self._prices[sym] = 0.0
            else:
                self._delisting_counter[sym] = 0

    # ── 조회 ──────────────────────────────────────────────────────────────────

    def get_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 0.0)

    def is_delisted(self, symbol: str) -> bool:
        return symbol in self._delisted

    def get_all_stock_data(self) -> list[StockData]:
        result = []
        for spec in self._cfg.stocks:
            sym = spec.symbol
            price = self._prices[sym]
            history = self._history[sym]
            prev = history[-2] if len(history) >= 2 else price
            change_pct = round((price - prev) / prev * 100, 2) if prev > 0 else 0.0
            result.append(StockData(
                symbol=sym,
                name=spec.name,
                sector=spec.sector,
                price=price,
                initial_price=spec.initial_price,
                price_history=list(history),
                change_pct=change_pct,
                delisted=(sym in self._delisted),
            ))
        return result

    def get_active_news(self) -> list[NewsEvent]:
        return list(self._active_news)

    def peek_next_news_hint(self) -> str:
        """INQUIRY 행동 시 제공하는 힌트 — 다음 뉴스 예정 종목 암시."""
        active = [s for s in self._cfg.stocks if s.symbol not in self._delisted]
        if not active:
            return "시장 정보 없음"
        ticks_until = max(0, self._next_news_tick - self._current_tick)
        spec = self._rng.choice(active)
        direction = self._rng.choice(["강세", "약세"])
        return f"약 {ticks_until}턴 후 {spec.sector} 섹터에 {direction} 이슈 예상"

    @property
    def symbols(self) -> list[str]:
        return [s.symbol for s in self._cfg.stocks]

    @property
    def active_symbols(self) -> list[str]:
        return [s.symbol for s in self._cfg.stocks if s.symbol not in self._delisted]
