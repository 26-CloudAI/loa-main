import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

const STOCKS_API = import.meta.env.VITE_STOCKS_API_BASE ?? 'http://localhost:8090'
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

interface TickData {
  tick: number
  finished: boolean
  market: { stocks: StockInfo[]; news: { symbol: string; headline: string; ticks_remaining: number }[] }
  leaderboard: LeaderEntry[]
  bots: Record<string, {
    cash: number
    credit_score: number
    total_value: number
    portfolio: Record<string, { quantity: number; avg_cost: number; value: number }>
    short_positions: Record<string, { quantity: number; avg_sell_price: number }>
  }>
}

// ── SVG 차트 ─────────────────────────────────────────────────────────────────

function StockChart({ history, color }: { history: number[]; symbol: string; color: string }) {
  if (history.length < 2) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm">
        데이터 수집 중...
      </div>
    )
  }

  const W = 600
  const H = 180
  const PAD = { top: 12, right: 16, bottom: 24, left: 56 }
  const iW = W - PAD.left - PAD.right
  const iH = H - PAD.top - PAD.bottom

  const minP = Math.min(...history)
  const maxP = Math.max(...history)
  const range = maxP - minP || 1

  const points = history.map((p, i) => {
    const x = PAD.left + (i / (history.length - 1)) * iW
    const y = PAD.top + (1 - (p - minP) / range) * iH
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  const pathD = `M${points.join('L')}`
  const lastY = parseFloat(points[points.length - 1].split(',')[1])
  const firstPrice = history[0]
  const lastPrice = history[history.length - 1]
  const totalChange = ((lastPrice - firstPrice) / firstPrice * 100)
  const isUp = lastPrice >= firstPrice

  // y축 레이블
  const yLabels = [0, 0.25, 0.5, 0.75, 1].map(t => ({
    y: PAD.top + (1 - t) * iH,
    val: minP + t * range,
  }))

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {/* 그리드 */}
      {yLabels.map(({ y, val }) => (
        <g key={val}>
          <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} stroke="#374151" strokeWidth="0.5" strokeDasharray="4,4" />
          <text x={PAD.left - 6} y={y + 4} textAnchor="end" fill="#6B7280" fontSize="10">
            {val >= 10000 ? `${(val / 10000).toFixed(0)}만` : val.toFixed(0)}
          </text>
        </g>
      ))}
      {/* 가격선 */}
      <path d={pathD} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" />
      {/* 마지막 가격 표시 */}
      <circle cx={PAD.left + iW} cy={lastY} r="3" fill={color} />
      <text x={PAD.left + iW + 6} y={lastY + 4} fill={color} fontSize="11" fontWeight="600">
        ₩{lastPrice.toLocaleString()}
      </text>
      {/* 등락률 */}
      <text x={PAD.left + iW} y={PAD.top - 2} textAnchor="end" fill={isUp ? '#34D399' : '#F87171'} fontSize="11" fontWeight="600">
        {isUp ? '▲' : '▼'} {Math.abs(totalChange).toFixed(2)}%
      </text>
    </svg>
  )
}

// ── 색상 팔레트 ───────────────────────────────────────────────────────────────

const CHART_COLORS = [
  '#6366F1','#10B981','#F59E0B','#EF4444','#8B5CF6',
  '#06B6D4','#F97316','#84CC16','#EC4899','#14B8A6',
  '#A78BFA','#FCD34D','#FB923C','#4ADE80','#38BDF8',
]

const RANK_COLORS = ['#FFD700','#C0C0C0','#CD7F32']

// ── 메인 페이지 ───────────────────────────────────────────────────────────────

export default function MockStocksWatchPage() {
  const { game_id } = useParams<{ game_id: string }>()
  const navigate = useNavigate()

  const [tick, setTick] = useState(0)
  const [totalTicks] = useState(200)
  const [stocks, setStocks] = useState<StockInfo[]>([])
  const [leaderboard, setLeaderboard] = useState<LeaderEntry[]>([])
  const [news, setNews] = useState<NewsItem[]>([])
  const [priceHistory, setPriceHistory] = useState<Record<string, number[]>>({})
  const [selectedStock, setSelectedStock] = useState<string>('')
  const [gameOver, setGameOver] = useState(false)
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const [selectedBot, setSelectedBot] = useState<string>('')
  const [botData, setBotData] = useState<TickData['bots']>({})

  const wsRef = useRef<WebSocket | null>(null)
  const newsKeySet = useRef<Set<string>>(new Set())

  const handleTick = useCallback((data: TickData) => {
    setTick(data.tick)
    setLeaderboard(data.leaderboard)
    setBotData(data.bots)

    const stockList = data.market.stocks.filter(s => !s.delisted)
    setStocks(stockList)

    // 가격 히스토리 누적
    setPriceHistory(prev => {
      const next = { ...prev }
      for (const s of data.market.stocks) {
        if (!next[s.symbol]) next[s.symbol] = []
        next[s.symbol] = [...next[s.symbol], s.price]
      }
      return next
    })

    // selectedStock 기본값
    setSelectedStock(prev => prev || (stockList[0]?.symbol ?? ''))

    // 뉴스 누적 (중복 제거)
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
    }

    if (data.finished) setGameOver(true)
  }, [])

  useEffect(() => {
    if (!game_id) return

    const ws = new WebSocket(`${STOCKS_WS}/ws/games/${game_id}`)
    wsRef.current = ws

    ws.onopen = () => setWsStatus('connected')
    ws.onclose = () => setWsStatus('disconnected')
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'tick') handleTick(msg.data)
      if (msg.type === 'game_end') setGameOver(true)
    }

    return () => ws.close()
  }, [game_id, handleTick])

  const maxValue = leaderboard[0]?.total_value || 1
  const stockColorMap = Object.fromEntries(
    stocks.map((s, i) => [s.symbol, CHART_COLORS[i % CHART_COLORS.length]])
  )

  const selectedStockInfo = stocks.find(s => s.symbol === selectedStock)
  const selectedBotInfo = selectedBot ? botData[selectedBot] : null

  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col">
      {/* 헤더 */}
      <header className="border-b border-gray-800 px-6 py-3 flex items-center gap-4 shrink-0">
        <button onClick={() => navigate('/games/new')} className="text-gray-400 hover:text-white text-sm transition-colors">
          ◀ 나가기
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">📈 모의주식</span>
        <span className="text-gray-500 text-xs font-mono">#{game_id}</span>

        <div className="flex items-center gap-3 ml-auto">
          {/* 진행 바 */}
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono text-gray-300">{tick} / {totalTicks}</span>
            <div className="w-32 h-1.5 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-green-500 rounded-full transition-all"
                style={{ width: `${(tick / totalTicks) * 100}%` }}
              />
            </div>
          </div>

          {/* 상태 */}
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            gameOver ? 'bg-yellow-500/20 text-yellow-400' :
            wsStatus === 'connected' ? 'bg-green-500/20 text-green-400' : 'bg-gray-700 text-gray-400'
          }`}>
            {gameOver ? '게임 종료' : wsStatus === 'connected' ? '진행 중' : '연결 중...'}
          </span>
        </div>
      </header>

      <main className="flex-1 flex gap-0 overflow-hidden">
        {/* 왼쪽: 차트 + 포트폴리오 */}
        <div className="flex-1 flex flex-col p-4 gap-4 min-w-0">
          {/* 종목 탭 */}
          <div className="flex gap-1 flex-wrap">
            {stocks.map(s => (
              <button
                key={s.symbol}
                onClick={() => setSelectedStock(s.symbol)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  selectedStock === s.symbol
                    ? 'text-white'
                    : 'text-gray-400 bg-gray-800 hover:bg-gray-700'
                }`}
                style={selectedStock === s.symbol ? { backgroundColor: stockColorMap[s.symbol] } : {}}
              >
                {s.symbol}
                <span className={`ml-1 ${s.change_pct >= 0 ? 'text-green-300' : 'text-red-300'}`}>
                  {s.change_pct >= 0 ? '▲' : '▼'}{Math.abs(s.change_pct).toFixed(1)}%
                </span>
              </button>
            ))}
          </div>

          {/* 차트 */}
          <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-2" style={{ height: 240 }}>
            {selectedStockInfo && (
              <div className="flex items-center gap-3 text-sm shrink-0">
                <span className="font-bold">{selectedStockInfo.name}</span>
                <span className="text-gray-400 text-xs">{selectedStock}</span>
                <span className="font-mono font-bold">₩{selectedStockInfo.price.toLocaleString()}</span>
                <span className={`text-xs ${selectedStockInfo.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {selectedStockInfo.change_pct >= 0 ? '▲' : '▼'}{Math.abs(selectedStockInfo.change_pct).toFixed(2)}%
                </span>
              </div>
            )}
            <div className="flex-1 min-h-0">
              <StockChart
                history={priceHistory[selectedStock] ?? []}
                symbol={selectedStock}
                color={stockColorMap[selectedStock] ?? '#6366F1'}
              />
            </div>
          </div>

          {/* 포트폴리오 (봇 선택 시) */}
          {selectedBotInfo && (
            <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">{selectedBot} 포트폴리오</h3>
                <button onClick={() => setSelectedBot('')} className="text-gray-500 hover:text-white text-xs">✕</button>
              </div>
              <div className="flex gap-4 text-xs text-gray-400">
                <span>현금 <span className="text-white font-mono">₩{selectedBotInfo.cash.toLocaleString()}</span></span>
                <span>총자산 <span className="text-white font-mono">₩{selectedBotInfo.total_value.toLocaleString()}</span></span>
                <span>신용 <span className="text-white font-mono">{selectedBotInfo.credit_score}점</span></span>
              </div>
              {Object.keys(selectedBotInfo.portfolio).length > 0 && (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 text-left">
                      <th className="pb-1">종목</th>
                      <th className="pb-1 text-right">수량</th>
                      <th className="pb-1 text-right">평가액</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(selectedBotInfo.portfolio).map(([sym, pos]) => (
                      <tr key={sym} className="border-t border-gray-700">
                        <td className="py-1 text-indigo-300">{sym}</td>
                        <td className="py-1 text-right text-gray-300">{pos.quantity}</td>
                        <td className="py-1 text-right text-gray-300 font-mono">₩{pos.value.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {Object.keys(selectedBotInfo.short_positions).length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-1">공매도 포지션</p>
                  {Object.entries(selectedBotInfo.short_positions).map(([sym, pos]) => (
                    <div key={sym} className="text-xs text-red-300">
                      {sym}: {pos.quantity}주 @ ₩{pos.avg_sell_price.toLocaleString()}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 오른쪽 사이드바 */}
        <div className="w-72 border-l border-gray-800 flex flex-col overflow-hidden shrink-0">
          {/* 리더보드 */}
          <div className="p-4 flex flex-col gap-3 border-b border-gray-800">
            <h3 className="text-sm font-semibold text-gray-300">🏆 리더보드</h3>
            <div className="flex flex-col gap-2">
              {leaderboard.map((entry, i) => {
                const pct = (entry.total_value / maxValue) * 100
                const rankColor = RANK_COLORS[i] ?? '#6366F1'
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
                        <span style={{ color: rankColor }} className="font-bold w-4">
                          {i < 3 ? ['🥇','🥈','🥉'][i] : `${entry.rank}`}
                        </span>
                        <span className="truncate max-w-[110px]">{entry.id}</span>
                      </span>
                      <span className="font-mono text-gray-300">
                        {(entry.total_value / 1e8).toFixed(3)}억
                      </span>
                    </div>
                    <div className="w-full h-1 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${pct}%`, backgroundColor: rankColor }}
                      />
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* 뉴스 피드 */}
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
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
                    isGemini
                      ? 'bg-green-500/10 border-green-500/30'
                      : 'bg-gray-800 border-gray-700'
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

      {/* 게임 종료 오버레이 */}
      {gameOver && leaderboard.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-gray-800 border border-gray-700 rounded-2xl p-8 w-full max-w-md shadow-2xl">
            <h2 className="text-2xl font-bold text-center mb-1">🏁 게임 종료</h2>
            <p className="text-gray-400 text-sm text-center mb-6">최종 순위</p>
            <div className="flex flex-col gap-3">
              {leaderboard.slice(0, 5).map((entry, i) => (
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
            <button
              onClick={() => navigate('/games/new')}
              className="mt-6 w-full bg-green-600 hover:bg-green-500 text-white rounded-xl py-3 text-sm font-medium transition-colors"
            >
              새 게임 만들기
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
