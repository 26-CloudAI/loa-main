import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

const STOCKS_API = import.meta.env.VITE_STOCKS_API_BASE ?? 'http://localhost:8080/stocks'

// ── 타입 ──────────────────────────────────────────────────────────────────────

interface StockInfo {
  symbol: string
  name: string
  price: number
  initial_price: number
  change_pct: number
  delisted: boolean
  price_history: number[]
}

interface NewsItem {
  symbol: string
  headline: string
  ticks_remaining: number
  tick: number
}

interface LeaderEntry {
  rank: number
  id: string
  total_value: number
  credit_score: number
}

interface BotInfo {
  cash: number
  credit_score: number
  total_value: number
  portfolio: Record<string, { quantity: number; avg_cost: number; value: number }>
  short_positions: Record<string, { quantity: number; avg_sell_price: number }>
}

interface TickData {
  tick: number
  finished: boolean
  market: { stocks: StockInfo[]; news: { symbol: string; headline: string; ticks_remaining: number }[] }
  leaderboard: LeaderEntry[]
  bots: Record<string, BotInfo>
}

interface ReplayResultEntry {
  rank: number
  bot_id: string
  final_total_value: number
  profit_rate: number
  credit_score: number
}

interface ReplayResult {
  final_tick: number
  rankings: ReplayResultEntry[]
}

interface ReplayData {
  game_id: string
  total_frames: number
  frames: TickData[]
  result: ReplayResult | null
}

// ── 색상 팔레트 ───────────────────────────────────────────────────────────────

const CHART_COLORS = [
  '#6366F1','#10B981','#F59E0B','#EF4444','#8B5CF6',
  '#06B6D4','#F97316','#84CC16','#EC4899','#14B8A6',
  '#A78BFA','#FCD34D','#FB923C','#4ADE80','#38BDF8',
]
const RANK_COLORS = ['#FFD700','#C0C0C0','#CD7F32']

const SPEEDS = [0.5, 1, 2, 4]

// ── 봇 수익률 차트 ────────────────────────────────────────────────────────────

function BotProfitChart({ botValueHistory, botInitialValues, botColorMap, selectedBot }: {
  botValueHistory: Record<string, number[]>
  botInitialValues: Record<string, number>
  botColorMap: Record<string, string>
  selectedBot: string
}) {
  const W = 620; const H = 200
  const PAD = { top: 20, right: 72, bottom: 24, left: 52 }
  const iW = W - PAD.left - PAD.right
  const iH = H - PAD.top - PAD.bottom

  const bots = Object.keys(botValueHistory).filter(id => botInitialValues[id])
  const maxLen = bots.reduce((m, id) => Math.max(m, botValueHistory[id]?.length ?? 0), 0)
  if (bots.length === 0 || maxLen < 2) {
    return <div className="flex items-center justify-center h-full text-gray-600 text-sm">데이터 수집 중...</div>
  }

  const profitSeries: Record<string, number[]> = {}
  for (const id of bots) {
    const init = botInitialValues[id]
    profitSeries[id] = (botValueHistory[id] ?? []).map(v => ((v - init) / init) * 100)
  }

  const allVals = bots.flatMap(id => profitSeries[id])
  const minY = Math.min(0, ...allVals)
  const maxY = Math.max(0, ...allVals)
  const rangeY = maxY - minY || 1

  const toX = (i: number, len: number) => PAD.left + (i / Math.max(len - 1, 1)) * iW
  const toY = (v: number) => PAD.top + (1 - (v - minY) / rangeY) * iH

  const steps = 4
  const yLabels = Array.from({ length: steps + 1 }, (_, i) => {
    const t = i / steps
    return { y: PAD.top + (1 - t) * iH, val: minY + t * rangeY }
  })

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {yLabels.map(({ y, val }) => (
        <g key={val}>
          <line
            x1={PAD.left} y1={y} x2={W - PAD.right} y2={y}
            stroke={Math.abs(val) < 0.01 ? '#4B5563' : '#374151'}
            strokeWidth={Math.abs(val) < 0.01 ? 1 : 0.5}
            strokeDasharray={Math.abs(val) < 0.01 ? undefined : '3,3'}
          />
          <text x={PAD.left - 6} y={y + 4} textAnchor="end" fill="#6B7280" fontSize="10">
            {val >= 0 ? '+' : ''}{val.toFixed(1)}%
          </text>
        </g>
      ))}

      {bots.map(id => {
        const series = profitSeries[id]
        if (!series || series.length < 2) return null
        const isSelected = selectedBot === id
        const hasSelection = selectedBot !== ''
        const opacity = hasSelection ? (isSelected ? 1 : 0.15) : 0.85
        const color = botColorMap[id] ?? '#6366F1'
        const pts = series.map((v, i) =>
          `${toX(i, series.length).toFixed(1)},${toY(v).toFixed(1)}`
        ).join('L')
        const lx = toX(series.length - 1, series.length)
        const ly = toY(series[series.length - 1])
        const lv = series[series.length - 1]
        const showLabel = isSelected || !hasSelection

        return (
          <g key={id} style={{ opacity }}>
            <path d={`M${pts}`} fill="none" stroke={color} strokeWidth={isSelected ? 2.5 : 1.5} strokeLinejoin="round" />
            {showLabel && (
              <>
                <circle cx={lx} cy={ly} r={isSelected ? 4 : 2.5} fill={color} />
                <text x={lx + 7} y={ly + 4} fill={color} fontSize="10" fontWeight={isSelected ? 'bold' : 'normal'}>
                  {lv >= 0 ? '+' : ''}{lv.toFixed(2)}%
                </text>
              </>
            )}
          </g>
        )
      })}
    </svg>
  )
}

// ── 종목 미니 차트 ────────────────────────────────────────────────────────────

function StockMiniChart({ history, color }: { history: number[]; color: string }) {
  if (history.length < 2) return <div className="w-full h-10 bg-gray-700/20 rounded" />
  const W = 100; const H = 40; const P = 3
  const minP = Math.min(...history); const maxP = Math.max(...history)
  const range = maxP - minP || 1
  const pts = history.map((p, i) =>
    `${(P + (i / (history.length - 1)) * (W - P * 2)).toFixed(1)},${(P + (1 - (p - minP) / range) * (H - P * 2)).toFixed(1)}`
  ).join('L')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-10" preserveAspectRatio="none">
      <path d={`M${pts}`} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

// ── 종목 풀 차트 ──────────────────────────────────────────────────────────────

function StockFullChart({ history, color }: { history: number[]; color: string }) {
  if (history.length < 2) {
    return <div className="flex items-center justify-center h-full text-gray-600 text-sm">데이터 수집 중...</div>
  }
  const W = 580; const H = 150
  const PAD = { top: 12, right: 64, bottom: 24, left: 52 }
  const iW = W - PAD.left - PAD.right; const iH = H - PAD.top - PAD.bottom
  const minP = Math.min(...history); const maxP = Math.max(...history)
  const range = maxP - minP || 1
  const pts = history.map((p, i) => {
    const x = PAD.left + (i / (history.length - 1)) * iW
    const y = PAD.top + (1 - (p - minP) / range) * iH
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  const lastY = parseFloat(pts[pts.length - 1].split(',')[1])
  const pct = ((history[history.length - 1] - history[0]) / history[0]) * 100
  const yLabels = [0, 0.25, 0.5, 0.75, 1].map(t => ({ y: PAD.top + (1 - t) * iH, val: minP + t * range }))

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {yLabels.map(({ y, val }) => (
        <g key={val}>
          <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} stroke="#374151" strokeWidth="0.5" strokeDasharray="4,4" />
          <text x={PAD.left - 6} y={y + 4} textAnchor="end" fill="#6B7280" fontSize="10">
            {val >= 10000 ? `${(val / 10000).toFixed(0)}만` : val.toFixed(0)}
          </text>
        </g>
      ))}
      <path d={`M${pts.join('L')}`} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" />
      <circle cx={PAD.left + iW} cy={lastY} r="3" fill={color} />
      <text x={PAD.left + iW + 6} y={lastY + 4} fill={color} fontSize="11" fontWeight="600">
        ₩{history[history.length - 1].toLocaleString()}
      </text>
      <text x={PAD.left + iW} y={PAD.top - 2} textAnchor="end" fill={pct >= 0 ? '#34D399' : '#F87171'} fontSize="11" fontWeight="600">
        {pct >= 0 ? '▲' : '▼'} {Math.abs(pct).toFixed(2)}%
      </text>
    </svg>
  )
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────────

export default function MockStocksReplayPage() {
  const { game_id } = useParams<{ game_id: string }>()
  const navigate = useNavigate()

  const [replayData,       setReplayData]       = useState<ReplayData | null>(null)
  const [frameIdx,         setFrameIdx]         = useState(0)
  const [isPlaying,        setIsPlaying]        = useState(false)
  const [speedIdx,         setSpeedIdx]         = useState(1)
  const [loading,          setLoading]          = useState(true)
  const [loadError,        setLoadError]        = useState('')

  const [currentSnapshot,  setCurrentSnapshot]  = useState<TickData | null>(null)
  const [priceHistory,     setPriceHistory]     = useState<Record<string, number[]>>({})
  const [botValueHistory,  setBotValueHistory]  = useState<Record<string, number[]>>({})
  const [news,             setNews]             = useState<NewsItem[]>([])
  const [botColorMap,      setBotColorMap]      = useState<Record<string, string>>({})
  const [selectedBot,      setSelectedBot]      = useState('')
  const [selectedStock,    setSelectedStock]    = useState<string | null>(null)
  const [showFinalResult,  setShowFinalResult]  = useState(false)

  const botInitialValues = useRef<Record<string, number>>({})
  const botColorAssigned = useRef<Record<string, string>>({})
  const playTimerRef     = useRef<ReturnType<typeof setInterval> | null>(null)

  // 리플레이 데이터 로드
  useEffect(() => {
    if (!game_id) return
    setLoading(true)
    fetch(`${STOCKS_API}/api/games/${game_id}/replay`)
      .then(r => {
        if (!r.ok) throw new Error(`리플레이를 불러올 수 없습니다. (${r.status})`)
        return r.json()
      })
      .then((data: ReplayData) => {
        setReplayData(data)
        // 첫 프레임 적용
        if (data.frames.length > 0) {
          applyFrame(data.frames, 0, {})
        }
        setLoading(false)
      })
      .catch(e => {
        setLoadError(e.message)
        setLoading(false)
      })
  }, [game_id])

  // 프레임 적용: 0..idx 순회하며 히스토리 재구성
  const applyFrame = useCallback((
    frames: TickData[],
    idx: number,
    _prevColorMap: Record<string, string>,
  ) => {
    if (!frames || frames.length === 0) return

    const newPriceHistory: Record<string, number[]> = {}
    const newBotValueHistory: Record<string, number[]> = {}
    const newNews: NewsItem[] = []
    const seenNewsKeys = new Set<string>()
    const newBotInitial: Record<string, number> = {}
    const newBotColorAssigned: Record<string, string> = { ...botColorAssigned.current }

    for (let i = 0; i <= idx; i++) {
      const f = frames[i]
      if (!f) continue

      // 주가 히스토리
      for (const s of f.market.stocks) {
        if (!newPriceHistory[s.symbol]) newPriceHistory[s.symbol] = []
        newPriceHistory[s.symbol].push(s.price)
      }

      // 봇 총자산 히스토리 + 색상 할당
      for (const [id, info] of Object.entries(f.bots)) {
        if (!newBotValueHistory[id]) newBotValueHistory[id] = []
        newBotValueHistory[id].push(info.total_value)
        if (!(id in newBotInitial)) {
          newBotInitial[id] = info.total_value
        }
        if (!(id in newBotColorAssigned)) {
          newBotColorAssigned[id] = CHART_COLORS[Object.keys(newBotColorAssigned).length % CHART_COLORS.length]
        }
      }

      // 뉴스 (중복 제거, 현재 틱까지만)
      for (const n of f.market.news) {
        const key = `${n.symbol}::${n.headline}`
        if (!seenNewsKeys.has(key)) {
          seenNewsKeys.add(key)
          newNews.push({ ...n, tick: f.tick })
        }
      }
    }

    botInitialValues.current = newBotInitial
    botColorAssigned.current = newBotColorAssigned

    setPriceHistory(newPriceHistory)
    setBotValueHistory(newBotValueHistory)
    setBotColorMap({ ...newBotColorAssigned })
    setNews(newNews.reverse().slice(0, 60))
    setCurrentSnapshot(frames[idx])
  }, [])

  // 자동 재생
  useEffect(() => {
    if (!isPlaying || !replayData) return
    const ms = 1000 / SPEEDS[speedIdx]
    playTimerRef.current = setInterval(() => {
      setFrameIdx(prev => {
        const next = prev + 1
        if (next >= replayData.total_frames) {
          setIsPlaying(false)
          if (replayData.result) setShowFinalResult(true)
          return prev
        }
        applyFrame(replayData.frames, next, botColorAssigned.current)
        return next
      })
    }, ms)
    return () => {
      if (playTimerRef.current) clearInterval(playTimerRef.current)
    }
  }, [isPlaying, speedIdx, replayData, applyFrame])

  function seekTo(idx: number) {
    if (!replayData) return
    const clamped = Math.max(0, Math.min(idx, replayData.total_frames - 1))
    setFrameIdx(clamped)
    applyFrame(replayData.frames, clamped, botColorAssigned.current)
    if (clamped >= replayData.total_frames - 1 && replayData.result) {
      setShowFinalResult(true)
    }
  }

  function togglePlay() {
    if (!replayData) return
    if (frameIdx >= replayData.total_frames - 1) {
      seekTo(0)
      setShowFinalResult(false)
      setIsPlaying(true)
      return
    }
    setIsPlaying(prev => !prev)
  }

  const totalFrames = replayData?.total_frames ?? 0
  const tick = currentSnapshot?.tick ?? 0
  const stocks = (currentSnapshot?.market?.stocks ?? []).filter(s => !s.delisted)
  const leaderboard = currentSnapshot?.leaderboard ?? []
  const botData = currentSnapshot?.bots ?? {}
  const maxValue = leaderboard[0]?.total_value || 1
  const stockColorMap = Object.fromEntries(
    stocks.map((s, i) => [s.symbol, CHART_COLORS[i % CHART_COLORS.length]])
  )
  const selectedBotInfo = selectedBot ? botData[selectedBot] : null

  // 로딩 / 에러 화면
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 text-white flex flex-col items-center justify-center gap-4">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-gray-400 text-sm">리플레이 데이터 로딩 중...</p>
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="min-h-screen bg-gray-900 text-white flex flex-col items-center justify-center gap-4">
        <p className="text-red-400">{loadError}</p>
        <button onClick={() => navigate('/games/list')}
          className="text-sm text-indigo-400 hover:text-indigo-300 underline underline-offset-2">
          게임 목록으로
        </button>
      </div>
    )
  }

  return (
    <div className="h-screen bg-gray-900 text-white flex flex-col overflow-hidden">

      {/* ── 헤더 ── */}
      <header className="sticky top-0 z-20 h-14 px-6 flex items-center gap-4 shrink-0" style={{ background: 'rgba(13,15,20,.92)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>
        <button onClick={() => navigate('/games/list')} className="text-gray-400 hover:text-white text-sm transition-colors">
          ◀ 게임 목록
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">📈 모의주식</span>
        <span className="text-gray-500 text-xs font-mono">#{game_id}</span>
        <span className="ml-1 text-xs font-medium bg-indigo-600/30 text-indigo-300 border border-indigo-600/50 rounded-full px-2 py-0.5">
          🎬 리플레이
        </span>

        <div className="flex items-center gap-3 ml-auto">
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono text-gray-300">{tick} / 200</span>
            <div className="w-32 h-1.5 bg-gray-700 rounded-full overflow-hidden">
              <div className="h-full bg-indigo-500 rounded-full transition-all" style={{ width: `${(tick / 200) * 100}%` }} />
            </div>
          </div>
        </div>
      </header>

      {/* ── 메인 그리드 ── */}
      <main className="flex-1 grid overflow-hidden" style={{ gridTemplateColumns: '1fr 296px' }}>

        {/* ── 좌측 패널 ── */}
        <div className="flex flex-col p-4 gap-3 overflow-hidden">

          {/* 봇 수익률 그래프 */}
          <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-2 overflow-hidden" style={{ flex: '3 1 0', minHeight: 0 }}>
            <div className="flex items-center gap-3 shrink-0 flex-wrap">
              <h3 className="text-sm font-semibold shrink-0">🤖 봇 수익률</h3>
              <div className="flex flex-wrap gap-1.5">
                {Object.keys(botColorMap).map(id => {
                  const color = botColorMap[id]
                  const isSelected = selectedBot === id
                  const dimmed = selectedBot !== '' && !isSelected
                  return (
                    <button
                      key={id}
                      onClick={() => setSelectedBot(prev => prev === id ? '' : id)}
                      className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border transition-all duration-150"
                      style={{
                        borderColor: color,
                        backgroundColor: isSelected ? color : 'transparent',
                        color: isSelected ? '#111827' : color,
                        opacity: dimmed ? 0.35 : 1,
                      }}
                    >
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: isSelected ? '#111827' : color }} />
                      {id}
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="flex-1 min-h-0">
              <BotProfitChart
                botValueHistory={botValueHistory}
                botInitialValues={botInitialValues.current}
                botColorMap={botColorMap}
                selectedBot={selectedBot}
              />
            </div>
          </div>

          {/* 재생 컨트롤 */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-col gap-2 shrink-0">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1">
                <button onClick={() => { setIsPlaying(false); seekTo(0) }}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-700 hover:bg-gray-600 text-sm transition-colors" title="처음으로">⏮</button>
                <button onClick={() => { setIsPlaying(false); seekTo(frameIdx - 10) }}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-700 hover:bg-gray-600 text-sm transition-colors" title="10 프레임 뒤로">⏪</button>
                <button onClick={togglePlay}
                  className="w-10 h-8 flex items-center justify-center rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-bold transition-colors"
                  title={isPlaying ? '일시정지' : '재생'}>
                  {isPlaying ? '⏸' : '▶'}
                </button>
                <button onClick={() => { setIsPlaying(false); seekTo(frameIdx + 10) }}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-700 hover:bg-gray-600 text-sm transition-colors" title="10 프레임 앞으로">⏩</button>
                <button onClick={() => { setIsPlaying(false); seekTo(totalFrames - 1) }}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-700 hover:bg-gray-600 text-sm transition-colors" title="끝으로">⏭</button>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-xs text-gray-500 mr-1">속도</span>
                {SPEEDS.map((s, i) => (
                  <button key={s} onClick={() => setSpeedIdx(i)}
                    className={`text-xs px-2 py-1 rounded transition-colors ${speedIdx === i ? 'bg-indigo-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}>
                    {s}×
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <input type="range" min={0} max={Math.max(0, totalFrames - 1)} value={frameIdx}
                onChange={e => { setIsPlaying(false); seekTo(Number(e.target.value)) }}
                className="w-full accent-indigo-500" />
              <div className="flex justify-between text-xs text-gray-500">
                <span>틱 {tick}</span>
                <span>전체 {totalFrames} 프레임</span>
              </div>
            </div>
          </div>

          {/* 종목 현황 */}
          <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-2 overflow-hidden" style={{ flex: '2 1 0', minHeight: 0 }}>
            {selectedStock ? (
              <>
                <div className="flex items-center gap-2 shrink-0">
                  <button onClick={() => setSelectedStock(null)} className="text-gray-400 hover:text-white text-xs transition-colors">◀ 전체</button>
                  <span className="text-gray-600 text-xs">|</span>
                  {(() => {
                    const s = stocks.find(s => s.symbol === selectedStock)
                    if (!s) return <span className="font-semibold text-sm">{selectedStock}</span>
                    return (
                      <>
                        <span className="font-semibold text-sm">{selectedStock}</span>
                        <span className="text-gray-400 text-xs">{s.name}</span>
                        <span className="font-mono font-bold text-sm">₩{s.price.toLocaleString()}</span>
                        <span className={`text-xs ${s.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {s.change_pct >= 0 ? '▲' : '▼'}{Math.abs(s.change_pct).toFixed(2)}%
                        </span>
                      </>
                    )
                  })()}
                </div>
                <div className="flex-1 min-h-0">
                  <StockFullChart history={priceHistory[selectedStock] ?? []} color={stockColorMap[selectedStock] ?? '#6366F1'} />
                </div>
              </>
            ) : (
              <>
                <h3 className="text-sm font-semibold shrink-0">
                  📊 종목 현황 <span className="text-gray-500 text-xs font-normal ml-2">클릭하면 상세 보기</span>
                </h3>
                <div className="grid gap-1.5 overflow-y-auto flex-1 min-h-0 scrollbar-custom" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))' }}>
                  {stocks.map(s => {
                    const color = stockColorMap[s.symbol]
                    const isUp  = s.change_pct >= 0
                    return (
                      <button key={s.symbol} onClick={() => setSelectedStock(s.symbol)}
                        className="rounded-lg px-2.5 pt-2 pb-1.5 text-left flex flex-col gap-1 transition-all duration-300"
                        style={{ backgroundColor: 'rgba(55,65,81,0.5)' }}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold truncate" style={{ color }}>{s.symbol}</span>
                          <span className={`text-[10px] font-bold ${isUp ? 'text-green-400' : 'text-red-400'}`}>
                            {isUp ? '▲' : '▼'}{Math.abs(s.change_pct).toFixed(1)}%
                          </span>
                        </div>
                        <StockMiniChart history={priceHistory[s.symbol] ?? []} color={color} />
                        <div className="text-[10px] text-gray-400 font-mono">₩{s.price.toLocaleString()}</div>
                      </button>
                    )
                  })}
                </div>
              </>
            )}
          </div>
        </div>

        {/* ── 우측 패널 ── */}
        <div className="border-l border-gray-800 flex flex-col overflow-hidden">

          {/* 리더보드 */}
          <div className="p-3 border-b border-gray-800 shrink-0">
            <h3 className="text-sm font-semibold text-gray-300 mb-2">🏆 리더보드</h3>
            <div className="flex flex-col gap-1">
              {leaderboard.map((entry, i) => {
                const pct       = (entry.total_value / maxValue) * 100
                const rankColor = RANK_COLORS[i] ?? '#6366F1'
                const botColor  = botColorMap[entry.id]
                return (
                  <button key={entry.id}
                    onClick={() => setSelectedBot(prev => prev === entry.id ? '' : entry.id)}
                    className={`flex flex-col gap-1 text-left rounded-lg px-2 py-1.5 transition-colors ${selectedBot === entry.id ? 'bg-gray-700' : 'hover:bg-gray-800'}`}
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5">
                        <span style={{ color: rankColor }} className="font-bold w-4 text-center shrink-0">
                          {i < 3 ? ['🥇','🥈','🥉'][i] : `${entry.rank}`}
                        </span>
                        {botColor && <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: botColor }} />}
                        <span className="truncate max-w-[100px]">{entry.id}</span>
                      </span>
                      <span className="font-mono text-gray-300 text-[11px] shrink-0">
                        {(entry.total_value / 1e8).toFixed(3)}억
                      </span>
                    </div>
                    <div className="w-full h-0.5 bg-gray-700 rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-300" style={{ width: `${pct}%`, backgroundColor: rankColor }} />
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* 봇 상세 (선택 시) */}
          {selectedBotInfo && (
            <div className="p-3 border-b border-gray-800 overflow-y-auto shrink-0 scrollbar-custom" style={{ maxHeight: 220 }}>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-semibold" style={{ color: botColorMap[selectedBot] ?? '#6366F1' }}>{selectedBot}</h3>
                <button onClick={() => setSelectedBot('')} className="text-gray-500 hover:text-white text-xs">✕</button>
              </div>
              <div className="grid grid-cols-2 gap-1.5 text-xs mb-3">
                <div className="bg-gray-700/50 rounded px-2 py-1.5">
                  <p className="text-gray-500 text-[10px] mb-0.5">현금</p>
                  <p className="font-mono text-white">{(selectedBotInfo.cash / 1e8).toFixed(2)}억</p>
                </div>
                <div className="bg-gray-700/50 rounded px-2 py-1.5">
                  <p className="text-gray-500 text-[10px] mb-0.5">총자산</p>
                  <p className="font-mono text-white">{(selectedBotInfo.total_value / 1e8).toFixed(2)}억</p>
                </div>
                <div className="bg-gray-700/50 rounded px-2 py-1.5 col-span-2">
                  <p className="text-gray-500 text-[10px] mb-0.5">신용점수</p>
                  <p className="font-mono text-white">{selectedBotInfo.credit_score}점</p>
                </div>
              </div>
              {Object.keys(selectedBotInfo.portfolio).length > 0 && (
                <div className="mb-2">
                  <p className="text-[10px] text-gray-500 mb-1">보유 종목</p>
                  {Object.entries(selectedBotInfo.portfolio).map(([sym, pos]) => (
                    <div key={sym} className="flex justify-between items-center text-[11px] py-0.5 border-b border-gray-700/40">
                      <span className="font-medium" style={{ color: stockColorMap[sym] ?? '#6366F1' }}>{sym}</span>
                      <span className="text-gray-400">{pos.quantity}주</span>
                      <span className="font-mono text-gray-300">₩{(pos.value / 1e6).toFixed(1)}M</span>
                    </div>
                  ))}
                </div>
              )}
              {Object.keys(selectedBotInfo.short_positions).length > 0 && (
                <div>
                  <p className="text-[10px] text-gray-500 mb-1">공매도 포지션</p>
                  {Object.entries(selectedBotInfo.short_positions).map(([sym, pos]) => (
                    <div key={sym} className="flex justify-between items-center text-[11px] py-0.5 border-b border-gray-700/40">
                      <span className="text-red-400">{sym}</span>
                      <span className="text-gray-400">{pos.quantity}주</span>
                      <span className="font-mono text-red-300">@{pos.avg_sell_price.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 뉴스 피드 (현재 틱까지 누적) */}
          <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2 min-h-0 scrollbar-custom">
            <h3 className="text-sm font-semibold text-gray-300 shrink-0">📰 뉴스</h3>
            {news.length === 0 && <p className="text-gray-600 text-xs">뉴스 없음</p>}
            {news.map((item, i) => {
              const isGemini = item.headline.startsWith('[G]')
              return (
                <div key={i} className={`rounded-lg px-3 py-2 text-xs border ${isGemini ? 'bg-green-500/10 border-green-500/30' : 'bg-gray-800 border-gray-700'}`}>
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className={`font-semibold ${isGemini ? 'text-green-400' : 'text-indigo-400'}`}>{item.symbol}</span>
                    <span className="text-gray-600">T{item.tick}</span>
                    {isGemini && <span className="text-green-400 text-[10px] bg-green-400/20 px-1 rounded">AI</span>}
                  </div>
                  <p className={`leading-snug ${isGemini ? 'text-green-100' : 'text-gray-300'}`}>
                    {item.headline}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
      </main>

      {/* ── 최종 결과 오버레이 ── */}
      {showFinalResult && replayData?.result && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-gray-800 border border-gray-700 rounded-2xl p-8 w-full max-w-md shadow-2xl mx-4">
            <h2 className="text-2xl font-bold text-center mb-1">🏁 리플레이 종료</h2>
            <p className="text-gray-400 text-sm text-center mb-6">최종 순위</p>
            <div className="flex flex-col gap-3">
              {replayData.result.rankings.slice(0, 5).map((entry, i) => (
                <div key={entry.bot_id} className="flex items-center gap-3 bg-gray-700/50 rounded-xl px-4 py-3">
                  <span className="text-2xl">{['🥇','🥈','🥉'][i] ?? `${entry.rank}.`}</span>
                  <div className="flex-1">
                    <p className="font-semibold">{entry.bot_id}</p>
                    <p className="text-xs text-gray-400">
                      수익률 {entry.profit_rate >= 0 ? '+' : ''}{entry.profit_rate.toFixed(2)}%
                    </p>
                  </div>
                  <span className="font-mono font-bold text-green-400">
                    ₩{entry.final_total_value.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-6 flex flex-col gap-2">
              <button
                onClick={() => { setShowFinalResult(false); seekTo(0); setIsPlaying(false) }}
                className="w-full bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl py-3 text-sm font-medium transition-colors"
              >
                처음부터 다시 보기
              </button>
              <button
                onClick={() => setShowFinalResult(false)}
                className="w-full bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-xl py-2.5 text-sm font-medium transition-colors"
              >
                닫기
              </button>
              <button
                onClick={() => navigate('/games/list')}
                className="w-full bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-xl py-2.5 text-sm font-medium transition-colors"
              >
                게임 목록으로
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
