import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { MOCK, MOCK_GAME_INFO, startMockSimulation } from '../dev/mock'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080'
const WS_BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8080').replace(/^http/, 'ws')

const CELL = 6          // px per grid cell
const MAP_PX = CELL * 100  // 600px canvas

// ── Types ──────────────────────────────────────────────────────────────

interface BotState {
  id: string
  x: number
  y: number
  energy: number
  score: number
  alive: boolean
  shield_active: boolean
}

interface Mineral {
  x: number
  y: number
  rare: boolean
}

interface LeaderEntry {
  rank: number
  id: string
  score: number
}

interface TickData {
  tick: number
  bots: BotState[]
  minerals: Mineral[]
  zone_boundary: number
  alive_count: number
  leaderboard: LeaderEntry[]
}

interface RankingEntry {
  rank: number
  id: string
  score: number
  kills: number
  minerals_mined: number
  survival_ticks: number
}

interface GameEndData {
  reason: string
  rankings: RankingEntry[]
}

interface EventLog {
  uid: number
  tick: number
  type: string
  actor_id: string
  target_id?: string
}

// ── Helpers ────────────────────────────────────────────────────────────

function hashColor(id: string): string {
  let h = 5381
  for (let i = 0; i < id.length; i++) h = ((h << 5) + h + id.charCodeAt(i)) | 0
  return `hsl(${Math.abs(h) % 360}, 65%, 58%)`
}

const REASON_LABEL: Record<string, string> = {
  last_standing: '최후의 1봇 생존!',
  max_ticks: '최대 틱(200) 도달',
  all_minerals_depleted: '모든 광물 소진',
}

const EVENT_STYLE: Record<string, string> = {
  kill: 'text-red-400',
  mine_success: 'text-yellow-400',
  death: 'text-gray-400',
  zone_damage: 'text-orange-400',
}

function formatEvent(ev: EventLog): string {
  switch (ev.type) {
    case 'kill':         return `${ev.actor_id} → ${ev.target_id ?? '?'} 킬`
    case 'mine_success': return `${ev.actor_id} 광물 채굴`
    case 'death':        return `${ev.actor_id} 사망`
    case 'zone_damage':  return `${ev.actor_id} 존 피해`
    default:             return `${ev.actor_id} ${ev.type}`
  }
}

// ── Canvas draw ────────────────────────────────────────────────────────

function drawCanvas(
  ctx: CanvasRenderingContext2D,
  data: TickData,
  colorMap: Map<string, string>,
) {
  // Background
  ctx.fillStyle = '#0a0a0f'
  ctx.fillRect(0, 0, MAP_PX, MAP_PX)

  // Zone danger overlay (4 border strips)
  const zb = data.zone_boundary
  if (zb > 0) {
    ctx.fillStyle = 'rgba(220, 38, 38, 0.18)'
    ctx.fillRect(0,                  0,                  MAP_PX,      zb * CELL)           // top
    ctx.fillRect(0,                  (100 - zb) * CELL,  MAP_PX,      zb * CELL)           // bottom
    ctx.fillRect(0,                  zb * CELL,          zb * CELL,   (100 - 2 * zb) * CELL) // left
    ctx.fillRect((100 - zb) * CELL,  zb * CELL,          zb * CELL,   (100 - 2 * zb) * CELL) // right

    // Zone boundary line
    ctx.strokeStyle = 'rgba(239, 68, 68, 0.75)'
    ctx.lineWidth = 1
    ctx.strokeRect(
      zb * CELL + 0.5,
      zb * CELL + 0.5,
      (100 - 2 * zb) * CELL - 1,
      (100 - 2 * zb) * CELL - 1,
    )
  }

  // Minerals
  for (const m of data.minerals) {
    const cx = m.x * CELL + CELL / 2
    const cy = m.y * CELL + CELL / 2
    ctx.fillStyle = m.rare ? '#fb923c' : '#facc15'
    ctx.beginPath()
    ctx.arc(cx, cy, m.rare ? CELL * 0.42 : CELL * 0.28, 0, Math.PI * 2)
    ctx.fill()
  }

  // Bots
  for (const bot of data.bots) {
    const cx = bot.x * CELL + CELL / 2
    const cy = bot.y * CELL + CELL / 2
    const r = CELL * 0.4

    if (!bot.alive) {
      ctx.globalAlpha = 0.3
      ctx.fillStyle = '#555'
      ctx.beginPath()
      ctx.arc(cx, cy, r, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = 1
      continue
    }

    const color = colorMap.get(bot.id) ?? '#888888'

    // Shield ring
    if (bot.shield_active) {
      ctx.strokeStyle = 'rgba(99, 179, 237, 0.85)'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.arc(cx, cy, r + 2, 0, Math.PI * 2)
      ctx.stroke()
    }

    // Bot circle
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(cx, cy, r, 0, Math.PI * 2)
    ctx.fill()

    // Energy bar (below bot)
    const ratio = Math.min(1, Math.max(0, bot.energy / 100))
    const bw = CELL * 0.9
    const bh = 1.5
    const bx = cx - bw / 2
    const by = cy + r + 1.5
    ctx.fillStyle = '#1a1a2e'
    ctx.fillRect(bx, by, bw, bh)
    ctx.fillStyle = ratio > 0.5 ? '#4ade80' : ratio > 0.2 ? '#facc15' : '#f87171'
    ctx.fillRect(bx, by, bw * ratio, bh)
  }
}

// ── Main Component ─────────────────────────────────────────────────────

export default function WatchPage() {
  const { game_id } = useParams<{ game_id: string }>()
  const navigate = useNavigate()

  const canvasRef        = useRef<HTMLCanvasElement>(null)
  const wsRef            = useRef<WebSocket | null>(null)
  const hasConnectedRef  = useRef(false)
  const colorMapRef      = useRef<Map<string, string>>(new Map())
  const currentTickRef   = useRef(0)
  const eventUidRef      = useRef(0)

  type GameStatus = 'waiting' | 'running' | 'finished' | 'error' | null
  const [gameStatus, setGameStatus] = useState<GameStatus>(null)
  const [wsStatus,   setWsStatus]   = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('connecting')
  const [tickData,   setTickData]   = useState<TickData | null>(null)
  const [totalBots,  setTotalBots]  = useState(0)
  const [events,     setEvents]     = useState<EventLog[]>([])
  const [gameEnd,    setGameEnd]    = useState<GameEndData | null>(null)
  const [loadError,  setLoadError]  = useState('')

  // 1) Fetch initial game info
  useEffect(() => {
    if (!game_id) return

    // ── mock mode ────────────────────────────────────────────
    if (MOCK) {
      setTotalBots(MOCK_GAME_INFO.total_bots)
      setGameStatus('running')
      return
    }
    // ────────────────────────────────────────────────────────

    fetch(`${API_BASE}/api/games/${game_id}`)
      .then((r) => {
        if (r.status === 404) throw new Error('게임을 찾을 수 없습니다.')
        if (!r.ok) throw new Error(`서버 오류 (${r.status})`)
        return r.json()
      })
      .then(async (info) => {
        setTotalBots(info.total_bots ?? 0)
        if (info.status === 'finished') {
          setGameStatus('finished')
          const res = await fetch(`${API_BASE}/api/games/${game_id}/result`)
          if (res.ok) {
            const result = await res.json()
            setGameEnd(result)
          }
        } else {
          setGameStatus(info.status ?? 'waiting')
        }
      })
      .catch((e) => {
        setLoadError(e.message)
        setGameStatus('error')
      })
  }, [game_id])

  // 2) Connect WebSocket (only once, when game is waiting or running)
  useEffect(() => {
    if (!game_id) return
    if (gameStatus === null || gameStatus === 'error' || gameStatus === 'finished') return
    if (hasConnectedRef.current) return
    hasConnectedRef.current = true

    // ── mock mode: tick 시뮬레이터 실행 ─────────────────────
    if (MOCK) {
      setWsStatus('connected')
      MOCK_GAME_INFO.bot_ids.forEach((id) => {
        colorMapRef.current.set(id, hashColor(id))
      })
      const stop = startMockSimulation({
        onTick: (data) => {
          currentTickRef.current = data.tick
          setTickData(data as TickData)
        },
        onEvent: (ev) => {
          setEvents((prev) => {
            const entry: EventLog = {
              uid: eventUidRef.current++,
              tick: currentTickRef.current,
              type: ev.event_type,
              actor_id: ev.actor_id,
              target_id: ev.target_id,
            }
            return [entry, ...prev].slice(0, 50)
          })
        },
        onEnd: (data) => {
          setGameStatus('finished')
          setWsStatus('disconnected')
          setGameEnd(data)
        },
      })
      return stop
    }
    // ────────────────────────────────────────────────────────

    let cancelled = false
    let retryCount = 0
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    function connect() {
      if (cancelled) return
      setWsStatus('connecting')
      const ws = new WebSocket(`${WS_BASE}/ws/games/${game_id}`)
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) { ws.close(); return }
        setWsStatus('connected')
        retryCount = 0
      }

      ws.onmessage = (e) => {
        if (cancelled) return
        const msg = JSON.parse(e.data as string)

        switch (msg.type) {
          case 'game_start': {
            setGameStatus('running')
            const botIds: string[] = msg.data?.bot_ids ?? []
            if (botIds.length > 0) setTotalBots(botIds.length)
            botIds.forEach((id) => {
              if (!colorMapRef.current.has(id))
                colorMapRef.current.set(id, hashColor(id))
            })
            break
          }
          case 'tick': {
            const td: TickData = msg.data
            currentTickRef.current = td.tick
            td.bots.forEach((b) => {
              if (!colorMapRef.current.has(b.id))
                colorMapRef.current.set(b.id, hashColor(b.id))
            })
            setTickData(td)
            break
          }
          case 'event': {
            const ev = msg.data
            setEvents((prev) => {
              const entry: EventLog = {
                uid:      eventUidRef.current++,
                tick:     currentTickRef.current,
                type:     ev.event_type,
                actor_id: ev.actor_id,
                target_id: ev.target_id,
              }
              return [entry, ...prev].slice(0, 50)
            })
            break
          }
          case 'game_end': {
            setGameStatus('finished')
            setGameEnd(msg.data)
            ws.close()
            break
          }
        }
      }

      ws.onclose = () => {
        if (cancelled) return
        setWsStatus('disconnected')
        if (retryCount < 3) {
          const delay = Math.pow(2, retryCount) * 500
          retryCount++
          retryTimer = setTimeout(connect, delay)
        } else {
          setWsStatus('error')
        }
      }

      ws.onerror = () => ws.close()
    }

    connect()

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
      wsRef.current?.close()
    }
  }, [game_id, gameStatus])

  // 3) Draw canvas on each tick
  useEffect(() => {
    if (!tickData || !canvasRef.current) return
    const ctx = canvasRef.current.getContext('2d')
    if (!ctx) return
    drawCanvas(ctx, tickData, colorMapRef.current)
  }, [tickData])

  // ── Render helpers ─────────────────────────────────────────────────

  const shortId = game_id?.slice(0, 8) ?? ''

  const wsLabel =
    gameStatus === 'finished' ? { text: 'FINISHED', cls: 'text-blue-400' }
    : wsStatus === 'connected'    ? { text: '연결됨',    cls: 'text-green-400' }
    : wsStatus === 'connecting'   ? { text: '연결 중…', cls: 'text-yellow-400' }
    : wsStatus === 'disconnected' ? { text: '재연결 중…', cls: 'text-orange-400' }
    :                               { text: '연결 실패',  cls: 'text-red-400' }

  const gameStatusLabel =
    gameStatus === 'running'  ? { text: 'RUNNING',  cls: 'bg-green-500/20 text-green-300' }
    : gameStatus === 'waiting'  ? { text: 'WAITING',  cls: 'bg-yellow-500/20 text-yellow-300' }
    : gameStatus === 'finished' ? { text: 'FINISHED', cls: 'bg-blue-500/20 text-blue-300' }
    : gameStatus === 'error'    ? { text: 'ERROR',    cls: 'bg-red-500/20 text-red-400' }
    :                             { text: '로딩 중',   cls: 'bg-gray-500/20 text-gray-400' }

  // ── Error / loading states ─────────────────────────────────────────

  if (gameStatus === 'error') {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center gap-4">
        <p className="text-red-400">{loadError || '게임을 찾을 수 없습니다.'}</p>
        <button
          onClick={() => navigate('/games')}
          className="text-sm text-indigo-400 hover:text-indigo-300 underline underline-offset-2"
        >
          게임 목록으로
        </button>
      </div>
    )
  }

  // ── Main render ────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate('/games')}
          className="text-gray-400 hover:text-white text-sm transition-colors"
        >
          ◀ 게임 목록
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">LOA - 게임 관전</span>
        <span className="text-gray-500 text-sm ml-1">게임 ID: {shortId}…</span>
      </header>

      {/* Main area */}
      <main className="flex flex-1 overflow-hidden p-4 gap-4">
        {/* Canvas */}
        <div className="shrink-0 relative">
          <canvas
            ref={canvasRef}
            width={MAP_PX}
            height={MAP_PX}
            className="rounded-lg border border-gray-800 block"
            style={{ imageRendering: 'pixelated' }}
          />
          {/* Waiting overlay */}
          {gameStatus === 'waiting' && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-950/80 rounded-lg">
              <p className="text-gray-400 text-sm">게임 시작 대기 중…</p>
            </div>
          )}
          {/* Loading overlay */}
          {gameStatus === null && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-950/80 rounded-lg">
              <p className="text-gray-500 text-sm">불러오는 중…</p>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <aside
          className="flex flex-col gap-3 overflow-hidden"
          style={{ width: 264, minWidth: 264 }}
        >
          {/* Tick / alive */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 flex flex-col gap-1">
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">틱</span>
              <span className="font-mono font-medium">
                {tickData?.tick ?? 0}
                <span className="text-gray-600"> / 200</span>
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">생존</span>
              <span className="font-mono font-medium">
                {tickData?.alive_count ?? 0}
                <span className="text-gray-600"> / {totalBots}</span>
              </span>
            </div>
          </div>

          {/* Leaderboard */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 flex flex-col gap-2">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">리더보드</h3>
            {(tickData?.leaderboard.length ?? 0) === 0 ? (
              <p className="text-gray-600 text-xs">-</p>
            ) : (
              tickData?.leaderboard.map((entry) => (
                <div key={entry.id} className="flex items-center gap-2 text-sm">
                  <span className="text-gray-500 w-5 text-right shrink-0">#{entry.rank}</span>
                  <span
                    className="flex-1 truncate font-medium"
                    style={{ color: colorMapRef.current.get(entry.id) ?? '#aaa' }}
                  >
                    {entry.id}
                  </span>
                  <span className="font-mono text-gray-300 shrink-0">
                    {entry.score.toFixed(1)}
                  </span>
                </div>
              ))
            )}
          </div>

          {/* Event log */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 flex flex-col gap-2 flex-1 min-h-0">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide shrink-0">
              이벤트 로그
            </h3>
            <div className="overflow-y-auto flex flex-col gap-1 flex-1">
              {events.length === 0 ? (
                <p className="text-gray-600 text-xs">이벤트 없음</p>
              ) : (
                events.map((ev) => (
                  <div key={ev.uid} className="text-xs leading-relaxed">
                    <span className="text-gray-600 mr-1">[{ev.tick}]</span>
                    <span className={EVENT_STYLE[ev.type] ?? 'text-gray-300'}>
                      {formatEvent(ev)}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </aside>
      </main>

      {/* Footer status bar */}
      <footer className="border-t border-gray-800 px-6 py-2 flex items-center gap-4 text-xs shrink-0">
        <span>
          연결 상태:{' '}
          <span className={`font-medium ${gameStatusLabel.cls}`}>
            {gameStatusLabel.text}
          </span>
        </span>
        <span>
          WebSocket:{' '}
          <span className={`font-medium ${wsLabel.cls}`}>{wsLabel.text}</span>
        </span>
      </footer>

      {/* Game end modal */}
      {gameEnd && (
        <GameEndModal
          data={gameEnd}
          colorMap={colorMapRef.current}
          onClose={() => setGameEnd(null)}
          onGoList={() => navigate('/games')}
        />
      )}
    </div>
  )
}

// ── Game End Modal ─────────────────────────────────────────────────────

function GameEndModal({
  data,
  colorMap,
  onClose,
  onGoList,
}: {
  data: GameEndData
  colorMap: Map<string, string>
  onClose: () => void
  onGoList: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-lg p-6 flex flex-col gap-5">
        {/* Title */}
        <div className="text-center">
          <p className="text-xs text-gray-500 mb-1">게임 종료</p>
          <h2 className="text-xl font-bold">
            {REASON_LABEL[data.reason] ?? data.reason}
          </h2>
        </div>

        {/* Rankings table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs border-b border-gray-800">
                <th className="py-1.5 text-left w-8">순위</th>
                <th className="py-1.5 text-left">봇</th>
                <th className="py-1.5 text-right">점수</th>
                <th className="py-1.5 text-right">킬</th>
                <th className="py-1.5 text-right">채굴</th>
                <th className="py-1.5 text-right">생존</th>
              </tr>
            </thead>
            <tbody>
              {data.rankings.map((r) => (
                <tr key={r.id} className="border-b border-gray-800/50">
                  <td className="py-1.5 text-gray-500">#{r.rank}</td>
                  <td
                    className="py-1.5 font-medium truncate max-w-[120px]"
                    style={{ color: colorMap.get(r.id) ?? '#ccc' }}
                  >
                    {r.id}
                  </td>
                  <td className="py-1.5 text-right font-mono">{r.score.toFixed(1)}</td>
                  <td className="py-1.5 text-right text-gray-400">{r.kills}</td>
                  <td className="py-1.5 text-right text-gray-400">{r.minerals_mined}</td>
                  <td className="py-1.5 text-right text-gray-400">{r.survival_ticks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-700 hover:border-gray-500 text-gray-300 hover:text-white text-sm rounded-lg py-2 transition-colors"
          >
            닫기
          </button>
          <button
            onClick={onGoList}
            className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg py-2 transition-colors"
          >
            게임 목록으로
          </button>
        </div>
      </div>
    </div>
  )
}
