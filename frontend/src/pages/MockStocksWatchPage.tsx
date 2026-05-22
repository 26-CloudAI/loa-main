import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

const STOCKS_API = import.meta.env.VITE_STOCKS_API_BASE ?? 'http://localhost:8080/stocks'
const STOCKS_WS  = STOCKS_API.replace(/^http/, 'ws')

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

// ── 색상 팔레트 ───────────────────────────────────────────────────────────────

const CHART_COLORS = [
  '#6366F1','#10B981','#F59E0B','#EF4444','#8B5CF6',
  '#06B6D4','#F97316','#84CC16','#EC4899','#14B8A6',
  '#A78BFA','#FCD34D','#FB923C','#4ADE80','#38BDF8',
]
const RANK_COLORS = ['#FFD700','#C0C0C0','#CD7F32']

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
            <path
              d={`M${pts}`}
              fill="none"
              stroke={color}
              strokeWidth={isSelected ? 2.5 : 1.5}
              strokeLinejoin="round"
            />
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

export default function MockStocksWatchPage() {
  const { game_id } = useParams<{ game_id: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const ownerBotId = searchParams.get('bot') ?? ''

  const [tick, setTick]                   = useState(0)
  const [totalTicks]                      = useState(200)
  const [stocks, setStocks]               = useState<StockInfo[]>([])
  const [leaderboard, setLeaderboard]     = useState<LeaderEntry[]>([])
  const [news, setNews]                   = useState<NewsItem[]>([])
  const [priceHistory, setPriceHistory]   = useState<Record<string, number[]>>({})
  const [selectedStock, setSelectedStock] = useState<string | null>(null)
  const [gameOver, setGameOver]           = useState(false)
  const [wsStatus, setWsStatus]           = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const [selectedBot, setSelectedBot]     = useState<string>('')
  const [botData, setBotData]             = useState<Record<string, BotInfo>>({})
  const [botValueHistory, setBotValueHistory] = useState<Record<string, number[]>>({})
  const [botColorMap, setBotColorMap]     = useState<Record<string, string>>({})
  const [newsBanner, setNewsBanner]           = useState<NewsItem | null>(null)
  const [bannerVisible, setBannerVisible]     = useState(false)
  const [finalRankings, setFinalRankings]     = useState<LeaderEntry[]>([])
  const [gameOverDismissed, setGameOverDismissed] = useState(false)
  const [highlightedStocks, setHighlightedStocks] = useState<Set<string>>(new Set())

  const newsKeySet       = useRef<Set<string>>(new Set())
  const botInitialValues = useRef<Record<string, number>>({})
  const botColorAssigned = useRef<Record<string, string>>({})
  const bannerTimerRef   = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!game_id) return

    function processTickData(data: TickData) {
      setTick(data.tick)
      setLeaderboard(data.leaderboard)
      setBotData(data.bots)

      const stockList = data.market.stocks.filter(s => !s.delisted)
      setStocks(stockList)

      setPriceHistory(prev => {
        const next = { ...prev }
        for (const s of data.market.stocks) {
          next[s.symbol] = [...(next[s.symbol] ?? []), s.price]
        }
        return next
      })

      let colorChanged = false
      for (const [id, info] of Object.entries(data.bots)) {
        if (!(id in botColorAssigned.current)) {
          botColorAssigned.current[id] = CHART_COLORS[Object.keys(botColorAssigned.current).length % CHART_COLORS.length]
          colorChanged = true
        }
        if (!(id in botInitialValues.current)) {
          botInitialValues.current[id] = info.total_value
        }
      }
      if (colorChanged) {
        setBotColorMap({ ...botColorAssigned.current })
        // 첫 틱에 ownerBotId가 봇 목록에 있으면 기본 선택
        if (ownerBotId && ownerBotId in botColorAssigned.current) {
          setSelectedBot(prev => prev || ownerBotId)
        }
      }

      setBotValueHistory(prev => {
        const next = { ...prev }
        for (const [id, info] of Object.entries(data.bots)) {
          next[id] = [...(next[id] ?? []), info.total_value]
        }
        return next
      })

      if (data.finished) setGameOver(true)
    }

    function showBanner(item: NewsItem) {
      if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current)
      setNewsBanner(item)
      setBannerVisible(false)
      // 한 프레임 뒤에 visible → CSS transition 트리거
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setBannerVisible(true))
      })
      // 3.5초 후 fade-out
      bannerTimerRef.current = setTimeout(() => {
        setBannerVisible(false)
        bannerTimerRef.current = setTimeout(() => setNewsBanner(null), 500)
      }, 3500)
    }

    const ws = new WebSocket(`${STOCKS_WS}/ws/games/${game_id}`)

    ws.onopen  = () => setWsStatus('connected')
    ws.onclose = () => setWsStatus('disconnected')
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)

      if (msg.type === 'game_end') {
        setGameOver(true)
        if (msg.rankings) setFinalRankings(msg.rankings)
        return
      }
      if (msg.type !== 'tick') return

      const data: TickData = msg.data

      // 뉴스 감지 (일시정지 중에도 항상 처리)
      const newItems: NewsItem[] = []
      for (const n of data.market.news) {
        const key = `${n.symbol}::${n.headline}`
        if (!newsKeySet.current.has(key)) {
          newsKeySet.current.add(key)
          newItems.push({ ...n, tick: data.tick })
        }
      }
      if (newItems.length > 0) {
        setNews(prev => [...newItems, ...prev].slice(0, 60))

        // 뉴스 발생 종목 카드 강조 (다음 뉴스 전까지 유지)
        setHighlightedStocks(new Set(newItems.map(n => n.symbol)))
      }

      processTickData(data)

      // 새 뉴스 → 배너 표시
      if (newItems.length > 0) {
        showBanner(newItems[0])
      }
    }

    return () => {
      ws.close()
      if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current)
    }
  }, [game_id])

  const maxValue = leaderboard[0]?.total_value || 1
  const stockColorMap = Object.fromEntries(
    stocks.map((s, i) => [s.symbol, CHART_COLORS[i % CHART_COLORS.length]])
  )
  const selectedBotInfo  = selectedBot ? botData[selectedBot] : null
  const displayRankings  = gameOver && finalRankings.length > 0 ? finalRankings : leaderboard

  return (
    <div className="h-screen text-white flex flex-col overflow-hidden" style={{
      background: '#0D0F14',
      backgroundImage: 'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
      backgroundSize: '24px 24px',
    }}>

      {/* ── 헤더 ── */}
      <header className="sticky top-0 z-20 h-14 px-6 flex items-center gap-4 shrink-0" style={{ background: 'rgba(13,15,20,.92)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>
        <button onClick={() => navigate('/games/new')} className="text-gray-400 hover:text-white text-sm transition-colors">
          ◀ 나가기
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">📈 모의주식</span>
        <span className="text-gray-500 text-xs font-mono">#{game_id}</span>

        <div className="flex items-center gap-3 ml-auto">
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono text-gray-300">{tick} / {totalTicks}</span>
            <div className="w-32 h-1.5 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-green-500 rounded-full transition-all"
                style={{ width: `${(tick / totalTicks) * 100}%` }}
              />
            </div>
          </div>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            gameOver ? 'bg-yellow-500/20 text-yellow-400' :
            wsStatus === 'connected' ? 'bg-green-500/20 text-green-400'
                     : 'bg-gray-700 text-gray-400'
          }`}>
            {gameOver ? '게임 종료' : wsStatus === 'connected' ? '진행 중' : '연결 중...'}
          </span>
        </div>
      </header>

      {/* ── 메인 그리드 ── */}
      <main className="flex-1 grid overflow-hidden" style={{ gridTemplateColumns: '1fr 296px' }}>

        {/* ── 좌측 패널 ── */}
        <div className="flex flex-col p-4 gap-3 overflow-hidden">

          {/* 봇 수익률 그래프 (좌상단) */}
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
                      <span
                        className="w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ background: isSelected ? '#111827' : color }}
                      />
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

          {/* 뉴스 배너 */}
          <div
            className="rounded-lg overflow-hidden shrink-0 transition-all duration-500"
            style={{
              maxHeight: newsBanner ? 44 : 0,
              opacity: bannerVisible ? 1 : 0,
              transform: bannerVisible ? 'translateY(0)' : 'translateY(-6px)',
              transition: 'opacity 0.4s ease, transform 0.4s ease, max-height 0.3s ease',
            }}
          >
            {newsBanner && (() => {
              const isAI = newsBanner.headline.startsWith('[G]')
              const color = stockColorMap[newsBanner.symbol] ?? '#6366F1'
              return (
                <div
                  className="flex items-center gap-3 px-4 h-11 text-sm"
                  style={{ borderLeft: `3px solid ${color}`, backgroundColor: `${color}18` }}
                >
                  <span className="font-bold shrink-0" style={{ color }}>
                    {newsBanner.symbol}
                  </span>
                  {isAI && (
                    <span className="text-[10px] bg-green-400/20 text-green-400 px-1.5 py-0.5 rounded shrink-0">AI</span>
                  )}
                  <span className="text-gray-200 truncate">
                    {newsBanner.headline.replace(/^\[G\]\s*/, '')}
                  </span>
                  <span className="text-gray-600 text-xs shrink-0 ml-auto">T{newsBanner.tick}</span>
                </div>
              )
            })()}
          </div>

          {/* 종목 현황 (좌하단) */}
          <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-2 overflow-hidden" style={{ flex: '2 1 0', minHeight: 0 }}>
            {selectedStock ? (
              /* 개별 종목 풀 차트 */
              <>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => setSelectedStock(null)}
                    className="text-gray-400 hover:text-white text-xs transition-colors"
                  >
                    ◀ 전체
                  </button>
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
                  <StockFullChart
                    history={priceHistory[selectedStock] ?? []}
                    color={stockColorMap[selectedStock] ?? '#6366F1'}
                  />
                </div>
              </>
            ) : (
              /* 전체 종목 미니 그리드 */
              <>
                <h3 className="text-sm font-semibold shrink-0">
                  📊 종목 현황
                  <span className="text-gray-500 text-xs font-normal ml-2">클릭하면 상세 보기</span>
                </h3>
                <div className="grid gap-1.5 overflow-y-auto flex-1 min-h-0 scrollbar-custom" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))' }}>
                  {stocks.map(s => {
                    const color = stockColorMap[s.symbol]
                    const isUp  = s.change_pct >= 0
                    return (
                      <button
                        key={s.symbol}
                        onClick={() => setSelectedStock(s.symbol)}
                        className="rounded-lg px-2.5 pt-2 pb-1.5 text-left flex flex-col gap-1 transition-all duration-700"
                        style={{
                          backgroundColor: highlightedStocks.has(s.symbol)
                            ? `${color}30`
                            : 'rgba(55,65,81,0.5)',
                          boxShadow: highlightedStocks.has(s.symbol)
                            ? `0 0 0 1px ${color}60`
                            : 'none',
                        }}
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
                  <button
                    key={entry.id}
                    onClick={() => setSelectedBot(prev => prev === entry.id ? '' : entry.id)}
                    className={`flex flex-col gap-1 text-left rounded-lg px-2 py-1.5 transition-colors ${
                      selectedBot === entry.id ? 'bg-gray-700' : 'hover:bg-gray-800'
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5">
                        <span style={{ color: rankColor }} className="font-bold w-4 text-center shrink-0">
                          {i < 3 ? ['🥇','🥈','🥉'][i] : `${entry.rank}`}
                        </span>
                        {botColor && (
                          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: botColor }} />
                        )}
                        <span className="truncate max-w-[100px]">{entry.id}</span>
                      </span>
                      <span className="font-mono text-gray-300 text-[11px] shrink-0">
                        {(entry.total_value / 1e8).toFixed(3)}억
                      </span>
                    </div>
                    <div className="w-full h-0.5 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-300"
                        style={{ width: `${pct}%`, backgroundColor: rankColor }}
                      />
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
                <h3 className="text-xs font-semibold" style={{ color: botColorMap[selectedBot] ?? '#6366F1' }}>
                  {selectedBot}
                </h3>
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

          {/* 뉴스 피드 */}
          <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2 min-h-0 scrollbar-custom">
            <h3 className="text-sm font-semibold text-gray-300 shrink-0">📰 뉴스</h3>
            {news.length === 0 && (
              <p className="text-gray-600 text-xs">뉴스 대기 중...</p>
            )}
            {news.map((item, i) => {
              const isGemini = item.headline.startsWith('[G]')
              return (
                <div
                  key={i}
                  className={`rounded-lg px-3 py-2 text-xs border ${
                    isGemini ? 'bg-green-500/10 border-green-500/30' : 'bg-gray-800 border-gray-700'
                  }`}
                >
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className={`font-semibold ${isGemini ? 'text-green-400' : 'text-indigo-400'}`}>
                      {item.symbol}
                    </span>
                    <span className="text-gray-600">T{item.tick}</span>
                    {isGemini && (
                      <span className="text-green-400 text-[10px] bg-green-400/20 px-1 rounded">AI</span>
                    )}
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

      {/* ── 게임 종료 오버레이 ── */}
      {gameOver && displayRankings.length > 0 && !gameOverDismissed && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-gray-800 border border-gray-700 rounded-2xl p-8 w-full max-w-md shadow-2xl mx-4">
            <h2 className="text-2xl font-bold text-center mb-1">🏁 게임 종료</h2>
            <p className="text-gray-400 text-sm text-center mb-6">최종 순위</p>
            <div className="flex flex-col gap-3">
              {displayRankings.slice(0, 5).map((entry, i) => (
                <div key={entry.id} className="flex items-center gap-3 bg-gray-700/50 rounded-xl px-4 py-3">
                  <span className="text-2xl">{['🥇','🥈','🥉'][i] ?? `${entry.rank}.`}</span>
                  <div className="flex-1">
                    <p className="font-semibold">{entry.id}</p>
                    <p className="text-xs text-gray-400">신용점수 {entry.credit_score}점</p>
                  </div>
                  <span className="font-mono font-bold text-green-400">
                    ₩{entry.total_value.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-6 flex flex-col gap-2">
              <button
                onClick={() => navigate(`/games/${game_id}/mock-stocks/result`)}
                className="w-full bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl py-3 text-sm font-medium transition-colors"
              >
                결과 보기
              </button>
              <button
                onClick={() => navigate('/games/new')}
                className="w-full bg-green-600 hover:bg-green-500 text-white rounded-xl py-3 text-sm font-medium transition-colors"
              >
                새 게임 만들기
              </button>
              <div className="flex gap-2">
                <button
                  onClick={() => navigate('/')}
                  className="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-xl py-2.5 text-sm font-medium transition-colors"
                >
                  메인 홈
                </button>
                <button
                  onClick={() => setGameOverDismissed(true)}
                  className="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-xl py-2.5 text-sm font-medium transition-colors"
                >
                  관전 계속 보기
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
