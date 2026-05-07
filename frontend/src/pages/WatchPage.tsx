import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MOCK, MOCK_GAME_INFO, startMockSimulation } from '../dev/mock'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'
const WS_BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale').replace(/^http/, 'ws')

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
  zone_bounds: [number, number, number, number]  // [minX, minY, maxX, maxY]
  alive_count: number
  leaderboard: LeaderEntry[]
}

interface RankingEntry {
  rank: number
  id: string
  score?: number
  final_score?: number
  kills: number
  minerals_mined: number
  survival_ticks: number
  survival_bonus?: number
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
  detail?: string
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
  kill:          'text-red-400',
  death:         'text-gray-400',
  mine_success:  'text-yellow-300',
  mine_fail:     'text-gray-500',
  attack_hit:    'text-red-400',
  attack_miss:   'text-red-300',
  zone_damage:   'text-orange-400',
  guard_success: 'text-cyan-400',
  shield:        'text-cyan-400',
}

function FormatEvent({ ev, colorMap }: { ev: EventLog; colorMap: Map<string, string> }) {
  const Bot = ({ id }: { id: string }) => (
    <span style={{ color: colorMap.get(id) ?? '#d1d5db' }} className="font-semibold">{id}</span>
  )
  const a = ev.actor_id
  const t = ev.target_id ?? '?'
  const detail = ev.detail ? <span className="text-gray-500"> ({ev.detail})</span> : null
  switch (ev.type) {
    case 'kill':          return <span>💀 <Bot id={t} /> 이(가) <Bot id={a} />에게 사망</span>
    case 'death':         return <span>🪦 <Bot id={a} /> 사망{detail}</span>
    case 'mine_success':  return <span>⛏️ <Bot id={a} /> 광물 획득</span>
    case 'mine_fail':     return <span><Bot id={a} /> 채굴 실패</span>
    case 'attack_hit':    return <span>⚔️ <Bot id={a} /> → <Bot id={t} /> 적중</span>
    case 'attack_miss':   return <span><Bot id={a} /> 공격 빗나감</span>
    case 'zone_damage':   return <span>🌀 <Bot id={a} /> 자기장 피해</span>
    case 'guard_success': return <span>🛡️ <Bot id={a} /> 방어 성공{detail}</span>
    case 'shield':        return <span>🛡️ <Bot id={a} /> 실드 전개</span>
    default:              return <span><Bot id={a} /> {ev.detail ?? ev.type}</span>
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

  // Zone danger overlay — backend: zone_bounds = [minX, minY, maxX, maxY] (safe zone)
  const [minX, minY, maxX, maxY] = data.zone_bounds
  const safeW = (maxX - minX + 1) * CELL
  const safeH = (maxY - minY + 1) * CELL
  if (minX > 0 || minY > 0 || maxX < 99 || maxY < 99) {
    ctx.fillStyle = 'rgba(220, 38, 38, 0.18)'
    ctx.fillRect(0,                MAP_PX - (100 - maxY - 1) * CELL, MAP_PX,             (100 - maxY - 1) * CELL) // bottom
    ctx.fillRect(0,                0,                                  MAP_PX,             minY * CELL)             // top
    ctx.fillRect(0,                minY * CELL,                        minX * CELL,        safeH)                   // left
    ctx.fillRect((maxX + 1) * CELL, minY * CELL,                      MAP_PX - (maxX + 1) * CELL, safeH)          // right

    // Zone boundary line
    ctx.strokeStyle = 'rgba(239, 68, 68, 0.75)'
    ctx.lineWidth = 1
    ctx.strokeRect(minX * CELL + 0.5, minY * CELL + 0.5, safeW - 1, safeH - 1)
  }

  // Minerals
  for (const m of data.minerals) {
    const cx = m.x * CELL + CELL / 2
    const cy = m.y * CELL + CELL / 2
    ctx.fillStyle = m.rare ? '#a855f7' : '#ffffff'
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
  const { token } = useAuth()
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
  const [showModal,  setShowModal]  = useState(false)
  const [loadError,  setLoadError]  = useState('')
  const [gameName,   setGameName]   = useState<string | null>(null)

  // 1) Fetch initial game info
  useEffect(() => {
    if (!game_id) return;

    // ── mock mode ────────────────────────────────────────────
    if (MOCK) {
      setTotalBots(MOCK_GAME_INFO.total_bots)
      setGameStatus('running');
      return
    }
    // ────────────────────────────────────────────────────────

    fetch(`${API_BASE}/api/games/${game_id}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (r.status === 404) throw new Error('게임을 찾을 수 없습니다.')
        if (!r.ok) throw new Error(`서버 오류 (${r.status})`)
        return r.json()
      })
      .then(async (info) => {
        setTotalBots(info.total_bots ?? 0)
        setGameName(info.name ?? null)
        if (info.status === 'finished') {
          setGameStatus('finished')
          const res = await fetch(`${API_BASE}/api/games/${game_id}/result`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          })
          if (res.ok) {
            const result = await res.json()
            setGameEnd(result)
            setShowModal(true)
          }
        } else {
          setGameStatus(info.status ?? 'waiting')
        }
      })
      .catch((e) => {
        setLoadError(e.message)
        setGameStatus('error')
      })
  }, [game_id, token])

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
              uid:       eventUidRef.current++,
              tick:      currentTickRef.current,
              type:      ev.event_type,
              actor_id:  ev.actor_id,
              target_id: ev.target_id,
            }
            return [entry, ...prev].slice(0, 100)
          })
        },
        onEnd: (data) => {
          setGameStatus('finished')
          setWsStatus('disconnected')
          setGameEnd(data)
          setShowModal(true)
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
      const wsUrl = token
        ? `${WS_BASE}/ws/games/${game_id}?token=${encodeURIComponent(token)}`
        : `${WS_BASE}/ws/games/${game_id}`
      const ws = new WebSocket(wsUrl)
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
                uid:       eventUidRef.current++,
                tick:      currentTickRef.current,
                type:      ev.event_type,
                actor_id:  ev.actor_id,
                target_id: ev.target_id,
                detail:    ev.detail,
              }
              return [entry, ...prev].slice(0, 100)
            })
            break
          }
          case 'game_end': {
            setGameStatus('finished')
            setGameEnd(msg.data)
            setShowModal(true)
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
  }, [game_id, gameStatus, token])

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
      <div className="min-h-screen bg-gray-900 text-white flex flex-col items-center justify-center gap-4">
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
    <div className="h-screen bg-gray-900 text-white flex flex-col overflow-hidden">
      {/* Header */}
      <header className="sticky top-0 z-20 h-14 border-b border-gray-800 bg-gray-950 px-6 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate('/games')}
          className="text-gray-400 hover:text-white text-sm transition-colors"
        >
          ◀ 게임 목록
        </button>
        <span className="text-gray-600">|</span>
        {gameName ? (
          <span className="font-bold">{gameName}</span>
        ) : (
          <span className="font-bold">LOA - 게임 관전</span>
        )}
        <span className="text-gray-500 text-sm ml-1">게임 ID: {shortId}…</span>
      </header>

      {/* Main area */}
      <main className="flex flex-1 overflow-hidden p-4 gap-4 justify-center">
        {/* Canvas column */}
        <div className="shrink-0 flex flex-col gap-4 overflow-y-auto scrollbar-custom" style={{ width: MAP_PX }}>
          {/* Canvas */}
          <div className="relative shrink-0">
            <canvas
              ref={canvasRef}
              width={MAP_PX}
              height={MAP_PX}
              className="rounded-lg border border-gray-700 block"
              style={{ imageRendering: 'pixelated' }}
            />
            {gameStatus === 'waiting' && (
              <div className="absolute inset-0 flex items-center justify-center bg-gray-950/80 rounded-lg">
                <p className="text-gray-400 text-sm">게임 시작 대기 중…</p>
              </div>
            )}
            {gameStatus === null && (
              <div className="absolute inset-0 flex items-center justify-center bg-gray-950/80 rounded-lg">
                <p className="text-gray-500 text-sm">불러오는 중…</p>
              </div>
            )}
          </div>

          {/* Game result panel (below canvas) */}
          {gameEnd && (
            <GameResultPanel
              data={gameEnd}
              colorMap={colorMapRef.current}
            />
          )}
        </div>

        {/* Sidebar */}
        <aside
          className="flex flex-col gap-3 overflow-hidden h-full"
          style={{ width: 264, minWidth: 264 }}
        >
          {/* Tick / alive */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-col gap-1">
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
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-col gap-2 shrink-0">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">리더보드</h3>
            {(tickData?.bots.length ?? 0) === 0 ? (
              <p className="text-gray-600 text-xs">-</p>
            ) : (
              <div className="overflow-y-auto scrollbar-custom flex flex-col gap-1" style={{ maxHeight: 180 }}>
                {[...( tickData?.bots ?? [])]
                  .sort((a, b) => b.score - a.score)
                  .map((bot, i) => (
                    <div key={bot.id} className="flex items-center gap-2 text-sm">
                      <span className="text-gray-500 w-5 text-right shrink-0">#{i + 1}</span>
                      <span
                        className={`flex-1 truncate font-medium ${!bot.alive ? 'opacity-35 line-through' : ''}`}
                        style={{ color: colorMapRef.current.get(bot.id) ?? '#aaa' }}
                      >
                        {bot.id}
                      </span>
                      <span className="font-mono text-gray-300 shrink-0 text-xs">
                        {bot.score.toFixed(1)}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </div>

          {/* Event log */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-col gap-2 flex-1 min-h-0">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide shrink-0">
              이벤트 로그
            </h3>
            <div className="overflow-y-auto flex flex-col gap-1 flex-1 scrollbar-custom">
              {events.length === 0 ? (
                <p className="text-gray-600 text-xs">이벤트 없음</p>
              ) : (
                events.map((ev) => (
                  <div key={ev.uid} className="text-xs leading-relaxed border-b border-gray-800/50 pb-1">
                    <span className="text-orange-400 font-bold mr-1">{ev.tick}틱</span>
                    <span className={EVENT_STYLE[ev.type] ?? 'text-gray-300'}>
                      <FormatEvent ev={ev} colorMap={colorMapRef.current} />
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
      {gameEnd && showModal && (
        <GameEndModal
          data={gameEnd}
          colorMap={colorMapRef.current}
          onClose={() => setShowModal(false)}
          onGoList={() => navigate('/games')}
        />
      )}
    </div>
  )
}

// ── Game Result Panel (below canvas) ──────────────────────────────────

function GameResultPanel({
  data,
  colorMap,
}: {
  data: GameEndData
  colorMap: Map<string, string>
}) {
  const [openId, setOpenId] = useState<string | null>(null)
  const winner = data.rankings[0]

  return (
    <div className="flex flex-col gap-4 pb-4">
      {/* Winner banner */}
      <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/5 px-6 py-5 text-center flex flex-col gap-1">
        <p className="text-xs text-gray-500 uppercase tracking-widest">게임 종료 · {REASON_LABEL[data.reason] ?? data.reason}</p>
        <p className="text-3xl font-bold mt-1" style={{ color: colorMap.get(winner?.id) ?? '#facc15' }}>
          🏆 {winner?.id ?? '?'}
        </p>
        <p className="text-sm text-gray-400 mt-0.5">
          최종 점수 <span className="text-white font-mono font-semibold">{(winner?.final_score ?? winner?.score ?? 0).toFixed(1)}</span>점
        </p>
      </div>

      {/* Bot profile cards */}
      <div className="flex flex-col gap-2">
        {data.rankings.map((r) => {
          const color = colorMap.get(r.id) ?? '#888'
          const finalScore   = r.final_score ?? r.score ?? 0
          const killPts      = r.kills * 30
          const survivalPts  = r.survival_ticks * 0.1
          const bonusPts     = r.survival_bonus ?? 0
          const miningPts    = Math.max(0, finalScore - killPts - survivalPts - bonusPts)
          const isOpen = openId === r.id
          const isWinner = r.rank === 1

          return (
            <div
              key={r.id}
              className="rounded-xl border overflow-hidden cursor-pointer transition-colors"
              style={{ borderColor: isOpen ? color + '66' : '#1f2937' }}
              onClick={() => setOpenId(isOpen ? null : r.id)}
            >
              {/* Card header */}
              <div
                className="flex items-center gap-3 px-4 py-3"
                style={{ background: isOpen ? color + '12' : undefined }}
              >
                <span className="text-gray-500 text-sm w-6 shrink-0">#{r.rank}</span>
                {isWinner && <span className="text-base leading-none">🏆</span>}
                <span className="flex-1 font-semibold text-sm truncate" style={{ color }}>
                  {r.id}
                </span>
                <span className="font-mono text-sm text-white shrink-0">{finalScore.toFixed(1)}점</span>
                <span className="text-gray-600 text-xs ml-1">{isOpen ? '▲' : '▼'}</span>
              </div>

              {/* Expanded detail */}
              {isOpen && (
                <div className="px-4 pb-4 pt-1 flex flex-col gap-2 border-t border-gray-800">
                  <div className="grid grid-cols-2 gap-2 mt-1">
                    <DetailItem icon="⛏️" label="채굴" value={`${r.minerals_mined}회`} pts={miningPts} color="#facc15" />
                    <DetailItem icon="⚔️" label="킬" value={`${r.kills}회`} pts={killPts} color="#f87171" />
                    <DetailItem icon="⏱️" label="생존 틱" value={`${r.survival_ticks}틱`} pts={survivalPts} color="#4ade80" />
                    {bonusPts > 0 && (
                      <DetailItem icon="🏅" label="생존 보너스" value={`생존 순위`} pts={bonusPts} color="#a78bfa" />
                    )}
                    <div className={`rounded-lg bg-gray-800/60 px-3 py-2 flex flex-col gap-0.5 ${bonusPts > 0 ? '' : ''}`}>
                      <span className="text-gray-400 text-xs">합계</span>
                      <span className="font-mono font-bold text-white text-sm">{finalScore.toFixed(1)}점</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DetailItem({ icon, label, value, pts, color }: {
  icon: string; label: string; value: string; pts: number; color: string
}) {
  return (
    <div className="rounded-lg bg-gray-800/60 px-3 py-2 flex flex-col gap-0.5">
      <span className="text-gray-400 text-xs">{icon} {label}</span>
      <span className="text-xs text-gray-300">{value}</span>
      <span className="font-mono text-sm font-semibold" style={{ color }}>+{pts.toFixed(1)}점</span>
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
                  <td className="py-1.5 text-right font-mono">{(r.final_score ?? r.score ?? 0).toFixed(1)}</td>
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
