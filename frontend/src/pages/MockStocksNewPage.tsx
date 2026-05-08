import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const STOCKS_API = import.meta.env.VITE_STOCKS_API_BASE ?? 'http://localhost:8080/stocks'
const MAX_CODE_BYTES = 50 * 1024

const DEFAULT_CODE = `def action(state: dict) -> dict:
    tick      = state["tick"]
    my        = state["my_bot"]
    cash      = my["cash"]
    total     = my["total_value"]
    portfolio = my["portfolio"]
    stocks    = {s["symbol"]: s for s in state["market"]["stocks"]}
    news      = state["market"]["news"]

    # 뉴스 호재 종목 매수
    bullish = ["계약", "실적", "파트너십", "출시", "[G]"]
    for item in news:
        sym = item["symbol"]
        if any(k in item["headline"] for k in bullish):
            stock = stocks.get(sym, {})
            if stock.get("delisted") or sym in portfolio:
                continue
            price = stock["price"]
            qty = int(cash * 0.15 / (price * 1.002))
            if qty > 0 and cash >= price * qty * 1.002:
                return {"action": "BUY", "symbol": sym, "quantity": qty}

    # 손실 -15% 이하 손절
    for sym, pos in portfolio.items():
        if pos["pnl_pct"] <= -15:
            return {"action": "SELL", "symbol": sym, "quantity": pos["quantity"]}

    # 수익 +20% 이상 절반 익절
    for sym, pos in portfolio.items():
        if pos["pnl_pct"] >= 20:
            qty = pos["quantity"] // 2
            if qty > 0:
                return {"action": "SELL", "symbol": sym, "quantity": qty}

    return {"action": "HOLD"}
`

function byteSize(s: string) {
  return new TextEncoder().encode(s).length
}

function RulesModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative z-10 bg-gray-800 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700 shrink-0">
          <h2 className="font-bold text-lg">📋 모의주식 룰 & 코드 가이드</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-white text-xl leading-none">✕</button>
        </div>
        <div className="overflow-y-auto px-6 py-5 flex flex-col gap-5 text-sm">
          <div>
            <h3 className="font-semibold mb-2">🎮 게임 개요</h3>
            <p className="text-gray-300 leading-relaxed">
              200턴 동안 초기 자본 1억 원으로 15개 종목에 투자해 최고 수익률을 목표로 합니다.
              매 틱 <code className="text-green-400">action(state)</code>를 호출하며 딕셔너리를 반환합니다.
            </p>
          </div>
          <div>
            <h3 className="font-semibold mb-2">⚙️ action 함수 구조</h3>
            <pre className="bg-gray-950 rounded-lg px-4 py-3 text-xs text-green-300 font-mono overflow-x-auto">{`def action(state: dict) -> dict:
    tick      = state["tick"]         # 현재 턴 (1~200)
    my        = state["my_bot"]       # 내 봇 정보
    cash      = my["cash"]            # 보유 현금
    total     = my["total_value"]     # 총 자산
    portfolio = my["portfolio"]       # 보유 주식
    shorts    = my["short_positions"] # 공매도 포지션
    stocks    = state["market"]["stocks"]
    news      = state["market"]["news"]
    return {"action": "HOLD"}`}</pre>
          </div>
          <div>
            <h3 className="font-semibold mb-2">🕹️ 반환 가능한 액션</h3>
            <div className="grid grid-cols-1 gap-2">
              {[
                ['BUY', '{"action": "BUY", "symbol": "NeoChips", "quantity": 10}', '현재가 즉시 체결'],
                ['SELL', '{"action": "SELL", "symbol": "NeoChips", "quantity": 5}', '보유 수량 범위 내'],
                ['SHORT', '{"action": "SHORT", "symbol": "NeoChips", "quantity": 10}', '신용점수 800+ 필요'],
                ['COVER', '{"action": "COVER", "symbol": "NeoChips", "quantity": 10}', '공매도 청산'],
                ['INQUIRY', '{"action": "INQUIRY"}', '다음 뉴스 힌트 수령'],
                ['HOLD', '{"action": "HOLD"}', '현금 0.01%/턴 이자'],
              ].map(([name, code, desc]) => (
                <div key={name} className="bg-gray-800/50 rounded-lg px-3 py-2">
                  <p className="font-mono text-green-400 text-xs">{code}</p>
                  <p className="text-gray-400 text-xs mt-0.5">{desc}</p>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h3 className="font-semibold mb-2">📰 뉴스 & Gemini AI</h3>
            <p className="text-gray-300 leading-relaxed">
              10~20턴마다 Gemini AI가 실시간으로 뉴스를 생성합니다.
              <span className="text-green-400 font-semibold"> [G]</span> 접두사가 붙은 뉴스는 AI가 생성한 것입니다.
              뉴스는 해당 종목의 주가에 5~10턴 동안 영향을 줍니다.
            </p>
          </div>
          <div>
            <h3 className="font-semibold mb-2">🏆 승리 조건</h3>
            <p className="text-gray-300">200턴 후 <b>총 자산 (현금 + 주식 평가액 + 공매도 손익)</b>이 가장 높은 봇이 우승.</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function MockStocksNewPage() {
  const navigate = useNavigate()
  const { token } = useAuth()

  const [botId, setBotId] = useState('')
  const [code, setCode] = useState(DEFAULT_CODE)
  const [fillWithAi, setFillWithAi] = useState(true)
  const [minBots, setMinBots] = useState<number | ''>(4)
  const [tickInterval, setTickInterval] = useState(0.1)
  const [seed, setSeed] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [showRules, setShowRules] = useState(false)

  // 뉴스 사전 생성 상태
  const [prepareId, setPrepareId] = useState<string | null>(null)
  const [newsReady, setNewsReady] = useState(false)
  const [newsCount, setNewsCount] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 마운트 시 뉴스 사전 생성 시작
  useEffect(() => {
    let cancelled = false

    async function startPrepare() {
      try {
        const res = await fetch(`${STOCKS_API}/api/stocks/prepare`, { method: 'POST' })
        if (!res.ok) return
        const { prepare_id } = await res.json()
        if (cancelled) return
        setPrepareId(prepare_id)

        // 준비 완료될 때까지 폴링
        pollRef.current = setInterval(async () => {
          try {
            const r = await fetch(`${STOCKS_API}/api/stocks/prepare/${prepare_id}`)
            if (!r.ok) return
            const { ready, count } = await r.json()
            if (ready) {
              setNewsReady(true)
              setNewsCount(count)
              if (pollRef.current) clearInterval(pollRef.current)
            }
          } catch { /* 무시 */ }
        }, 1000)
      } catch { /* 무시 */ }
    }

    startPrepare()
    return () => {
      cancelled = true
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const codeBytes = byteSize(code)
  const codeOverLimit = codeBytes > MAX_CODE_BYTES
  const canSubmit = !submitting && code.trim().length > 0 && !codeOverLimit

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError('')

    try {
      const res = await fetch(`${STOCKS_API}/api/games`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          bots: [{ bot_id: botId.trim() || 'my_bot', code }],
          tick_interval: tickInterval,
          fill_with_ai: fillWithAi,
          min_bots: minBots || 2,
          seed: seed !== '' ? parseInt(seed, 10) : null,
          prepare_id: prepareId,
        }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail ?? `서버 오류 (${res.status})`)
      }

      const game = await res.json()
      navigate(`/games/${game.game_id}/mock-stocks/watch?bot=${encodeURIComponent(botId.trim() || 'my_bot')}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '게임 생성에 실패했습니다.')
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {showRules && <RulesModal onClose={() => setShowRules(false)} />}

      <header className="sticky top-0 z-20 h-14 border-b border-gray-800 bg-gray-950 px-6 flex items-center gap-3">
        <button onClick={() => navigate('/games/new')} className="text-gray-400 hover:text-white text-sm transition-colors">
          ◀ 모드 선택
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">📈 모의주식 — 새 게임</span>

        {/* 뉴스 준비 상태 */}
        <div className="ml-4 flex items-center gap-2 text-xs">
          {newsReady ? (
            <span className="flex items-center gap-1.5 text-green-400 bg-green-400/10 px-2.5 py-1 rounded-full border border-green-400/30">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              뉴스 {newsCount}개 준비 완료
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-yellow-400 bg-yellow-400/10 px-2.5 py-1 rounded-full border border-yellow-400/30">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
              Gemini 뉴스 생성 중...
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={() => setShowRules(true)}
          className="ml-auto text-xs font-medium text-green-400 hover:text-green-300 border border-green-500/40 hover:border-green-400 rounded-lg px-3 py-1.5 transition-colors"
        >
          📋 룰 확인
        </button>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8">
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">

          {/* 봇 이름 */}
          <section className="flex flex-col gap-2">
            <label className="text-sm font-medium text-gray-300">
              봇 이름 <span className="text-gray-500 font-normal">(게임 내 표시 ID)</span>
            </label>
            <input
              type="text"
              value={botId}
              onChange={(e) => setBotId(e.target.value)}
              placeholder="my_bot"
              maxLength={32}
              className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-green-500 placeholder-gray-600 w-64"
            />
          </section>

          {/* 코드 에디터 */}
          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-gray-300">봇 코드 (Python)</label>
              <span className={`text-xs font-mono ${codeOverLimit ? 'text-red-400' : 'text-gray-500'}`}>
                {(codeBytes / 1024).toFixed(1)} KB / 50 KB
                {codeOverLimit && ' — 초과'}
              </span>
            </div>
            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              spellCheck={false}
              rows={20}
              className={`bg-gray-900 text-green-300 font-mono text-sm rounded-lg px-4 py-3 outline-none resize-y border ${
                codeOverLimit
                  ? 'border-red-500 focus:ring-2 focus:ring-red-500'
                  : 'border-gray-700 focus:ring-2 focus:ring-green-500'
              } w-full`}
            />
          </section>

          {/* 게임 옵션 */}
          <section className="bg-gray-800 border border-gray-700 rounded-xl px-5 py-4 flex flex-col gap-4">
            <h3 className="text-sm font-medium text-gray-300">게임 옵션</h3>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white">AI로 빈 슬롯 채우기</p>
                <p className="text-xs text-gray-500">장기봇 · 단기봇 · 랜덤봇으로 채웁니다</p>
              </div>
              <button
                type="button"
                onClick={() => setFillWithAi((v) => !v)}
                className={`relative w-11 h-6 rounded-full transition-colors ${fillWithAi ? 'bg-green-600' : 'bg-gray-700'}`}
              >
                <span className={`absolute top-1 left-0 w-4 h-4 bg-white rounded-full shadow transition-transform ${fillWithAi ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white">최소 봇 수</p>
                <p className="text-xs text-gray-500">2 ~ 20</p>
              </div>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                value={minBots}
                onChange={(e) => {
                  const raw = e.target.value.replace(/[^0-9]/g, '')
                  if (raw === '') { setMinBots(''); return }
                  setMinBots(Math.min(20, Number(raw)))
                }}
                onBlur={() => setMinBots((v) => (v === '' || v < 2 ? 2 : v))}
                className="bg-gray-600 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-green-500 w-16 text-center"
              />
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-white">틱 간격 (속도)</p>
                  <p className="text-xs text-gray-500">값이 작을수록 빠름</p>
                </div>
                <span className="text-sm text-green-400 font-mono">{tickInterval.toFixed(2)}s</span>
              </div>
              <input
                type="range"
                min={0.01}
                max={1.0}
                step={0.01}
                value={tickInterval}
                onChange={(e) => setTickInterval(parseFloat(e.target.value))}
                className="w-full accent-green-500"
              />
              <div className="flex justify-between text-xs text-gray-600">
                <span>0.01s (빠름)</span>
                <span>1.0s (느림)</span>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white">시드 (재현용, 선택)</p>
                <p className="text-xs text-gray-500">비우면 랜덤</p>
              </div>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                value={seed}
                onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ''))}
                placeholder="랜덤"
                className="bg-gray-600 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-green-500 w-20 text-center placeholder-gray-400"
              />
            </div>
          </section>

          {error && (
            <div className="text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">{error}</div>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-3 transition-colors"
          >
            {submitting ? '게임 생성 중...' : '게임 시작'}
          </button>
        </form>
      </main>
    </div>
  )
}
