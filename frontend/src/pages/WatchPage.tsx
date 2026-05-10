import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MOCK, MOCK_GAME_INFO, startMockSimulation } from '../dev/mock'
import PhaserGame from '../game/PhaserGame'
import type { TickData, GameEvent } from '../game/BattleRoyaleScene'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'
const WS_BASE  = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale').replace(/^http/, 'ws')

// ── Types ──────────────────────────────────────────────────────────────

interface BotState {
  id: string; x: number; y: number
  energy: number; score: number; alive: boolean; shield_active: boolean
}
interface LeaderEntry { rank: number; id: string; score: number }
interface FullTickData extends TickData {
  leaderboard: LeaderEntry[]
}
interface RankingEntry {
  rank: number; id: string; score?: number; final_score?: number
  kills: number; minerals_mined: number; survival_ticks: number; survival_bonus?: number
}
interface GameEndData { reason: string; rankings: RankingEntry[] }
interface EventLog {
  uid: number; tick: number; type: string
  actor_id: string; target_id?: string; detail?: string
}

// ── Helpers ────────────────────────────────────────────────────────────

function hashColor(id: string): string {
  let h = 5381
  for (let i = 0; i < id.length; i++) h = ((h << 5) + h + id.charCodeAt(i)) | 0
  return `hsl(${Math.abs(h) % 360}, 65%, 58%)`
}

function getBotIcon(botId: string, isMyBot: boolean, myBotIcon: string): string {
  if (isMyBot) return myBotIcon
  const id = botId.toLowerCase()
  if (id.includes('초식') || id.includes('herbivore')) return '🌿'
  if (id.includes('미친개') || id.includes('maddog'))  return '🐺'
  if (id.includes('존버')   || id.includes('camper'))  return '🏕️'
  return '🤖'
}

const REASON_LABEL: Record<string, string> = {
  last_standing:         '최후의 1봇 생존!',
  max_ticks:             '최대 틱(200) 도달',
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
  const a      = ev.actor_id
  const t      = ev.target_id ?? '?'
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

// ── Main Component ─────────────────────────────────────────────────────

export default function WatchPage() {
  const { game_id } = useParams<{ game_id: string }>()
  const { token }   = useAuth()
  const navigate    = useNavigate()

  const wsRef           = useRef<WebSocket | null>(null)
  const hasConnectedRef = useRef(false)
  const colorMapRef     = useRef<Map<string, string>>(new Map())
  const currentTickRef  = useRef(0)
  const eventUidRef     = useRef(0)
  // Shared event queue — WatchPage pushes, Phaser scene drains each frame
  const eventQueueRef   = useRef<GameEvent[]>([])

  type GameStatus = 'waiting' | 'running' | 'finished' | 'error' | null
  const [gameStatus, setGameStatus] = useState<GameStatus>(null)
  const [wsStatus,   setWsStatus]   = useState<'connecting'|'connected'|'disconnected'|'error'>('connecting')
  const [tickData,   setTickData]   = useState<FullTickData | null>(null)
  const [totalBots,  setTotalBots]  = useState(0)
  const [events,     setEvents]     = useState<EventLog[]>([])
  const [gameEnd,    setGameEnd]    = useState<GameEndData | null>(null)
  const [showModal,  setShowModal]  = useState(false)
  const [loadError,  setLoadError]  = useState('')
  const [gameName,   setGameName]   = useState<string | null>(null)

  // 내 봇 ID/아이콘 — localStorage에서 읽어 고정 (아이콘 귀속용)
  const [myBotId] = useState<string>(() => {
    try {
      const raw = localStorage.getItem('loa_bot_icon')
      if (raw) return (JSON.parse(raw) as { botId: string; icon: string }).botId
    } catch { /* ignore */ }
    return 'my_bot'
  })
  const [myBotIcon] = useState<string>(() => {
    try {
      const raw = localStorage.getItem('loa_bot_icon')
      if (raw) return (JSON.parse(raw) as { botId: string; icon: string }).icon
    } catch { /* ignore */ }
    return '⭐'
  })
  // 카메라 추적 대상 — 드롭박스로 변경 가능, 초기값은 내 봇
  const [followBotId, setFollowBotId] = useState<string>(myBotId)
  const [zoomLevel, setZoomLevel] = useState(3)

  const botIds = tickData ? tickData.bots.map(b => b.id) : []

  // 1) Fetch initial game info
  useEffect(() => {
    if (!game_id) return
    if (MOCK) {
      setTotalBots(MOCK_GAME_INFO.total_bots)
      setFollowBotId(MOCK_GAME_INFO.bot_ids[0] ?? myBotId)
      setGameStatus('running')
      return
    }
    fetch(`${API_BASE}/api/games/${game_id}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => {
        if (r.status === 404) throw new Error('게임을 찾을 수 없습니다.')
        if (!r.ok) throw new Error(`서버 오류 (${r.status})`)
        return r.json()
      })
      .then(async info => {
        setTotalBots(info.total_bots ?? 0)
        setGameName(info.name ?? null)
        if (info.status === 'finished') {
          setGameStatus('finished')
          const res = await fetch(`${API_BASE}/api/games/${game_id}/result`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          })
          if (res.ok) { setGameEnd(await res.json()); setShowModal(true) }
        } else {
          setGameStatus(info.status ?? 'waiting')
        }
      })
      .catch(e => { setLoadError(e.message); setGameStatus('error') })
  }, [game_id, token])

  // 2) Connect WebSocket
  useEffect(() => {
    if (!game_id) return
    if (gameStatus === null || gameStatus === 'error' || gameStatus === 'finished') return
    if (hasConnectedRef.current) return
    hasConnectedRef.current = true

    if (MOCK) {
      setWsStatus('connected')
      MOCK_GAME_INFO.bot_ids.forEach(id => colorMapRef.current.set(id, hashColor(id)))
      const stop = startMockSimulation({
        onTick: data => {
          currentTickRef.current = data.tick
          setTickData(data as FullTickData)
        },
        onEvent: ev => {
          const entry: EventLog = {
            uid: eventUidRef.current++, tick: currentTickRef.current,
            type: ev.event_type, actor_id: ev.actor_id, target_id: ev.target_id,
          }
          eventQueueRef.current.push({ type: ev.event_type, actor_id: ev.actor_id, target_id: ev.target_id })
          setEvents(prev => [entry, ...prev].slice(0, 100))
        },
        onEnd: data => {
          setGameStatus('finished'); setWsStatus('disconnected')
          setGameEnd(data); setShowModal(true)
        },
      })
      return stop
    }

    let cancelled = false, retryCount = 0
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    function connect() {
      if (cancelled) return
      setWsStatus('connecting')
      const wsUrl = token
        ? `${WS_BASE}/ws/games/${game_id}?token=${encodeURIComponent(token)}`
        : `${WS_BASE}/ws/games/${game_id}`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => { if (cancelled) { ws.close(); return }; setWsStatus('connected'); retryCount = 0 }

      ws.onmessage = e => {
        if (cancelled) return
        const msg = JSON.parse(e.data as string)
        switch (msg.type) {
          case 'game_start': {
            setGameStatus('running')
            const ids: string[] = msg.data?.bot_ids ?? []
            if (ids.length > 0) setTotalBots(ids.length)
            ids.forEach(id => { if (!colorMapRef.current.has(id)) colorMapRef.current.set(id, hashColor(id)) })
            break
          }
          case 'tick': {
            const td = msg.data as FullTickData
            currentTickRef.current = td.tick
            td.bots.forEach(b => { if (!colorMapRef.current.has(b.id)) colorMapRef.current.set(b.id, hashColor(b.id)) })
            setTickData(td)
            break
          }
          case 'event': {
            const ev = msg.data
            const entry: EventLog = {
              uid: eventUidRef.current++, tick: currentTickRef.current,
              type: ev.event_type, actor_id: ev.actor_id,
              target_id: ev.target_id, detail: ev.detail,
            }
            eventQueueRef.current.push({ type: ev.event_type, actor_id: ev.actor_id, target_id: ev.target_id })
            setEvents(prev => [entry, ...prev].slice(0, 100))
            break
          }
          case 'game_end':
            setGameStatus('finished'); setGameEnd(msg.data); setShowModal(true); ws.close()
            break
        }
      }

      ws.onclose = () => {
        if (cancelled) return
        setWsStatus('disconnected')
        if (retryCount < 3) { retryTimer = setTimeout(connect, Math.pow(2, retryCount++) * 500) }
        else setWsStatus('error')
      }
      ws.onerror = () => ws.close()
    }

    connect()
    return () => { cancelled = true; if (retryTimer) clearTimeout(retryTimer); wsRef.current?.close() }
  }, [game_id, gameStatus, token])

  // ── Status labels ──────────────────────────────────────────────────

  const wsLabel =
    gameStatus === 'finished'     ? { text: 'FINISHED',   cls: 'text-blue-400'   }
    : wsStatus === 'connected'    ? { text: '연결됨',     cls: 'text-green-400'  }
    : wsStatus === 'connecting'   ? { text: '연결 중…',   cls: 'text-yellow-400' }
    : wsStatus === 'disconnected' ? { text: '재연결 중…', cls: 'text-orange-400' }
    :                               { text: '연결 실패',  cls: 'text-red-400'    }

  const gameStatusLabel =
    gameStatus === 'running'  ? { text: 'RUNNING',  cls: 'bg-green-500/20 text-green-300'   }
    : gameStatus === 'waiting'  ? { text: 'WAITING',  cls: 'bg-yellow-500/20 text-yellow-300' }
    : gameStatus === 'finished' ? { text: 'FINISHED', cls: 'bg-blue-500/20 text-blue-300'    }
    : gameStatus === 'error'    ? { text: 'ERROR',    cls: 'bg-red-500/20 text-red-400'      }
    :                             { text: '로딩 중',  cls: 'bg-gray-500/20 text-gray-400'    }

  if (gameStatus === 'error') {
    return (
      <div className="min-h-screen bg-gray-900 text-white flex flex-col items-center justify-center gap-4">
        <p className="text-red-400">{loadError || '게임을 찾을 수 없습니다.'}</p>
        <button onClick={() => navigate('/games')}
          className="text-sm text-indigo-400 hover:text-indigo-300 underline underline-offset-2">
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
        <button onClick={() => navigate('/games')}
          className="text-gray-400 hover:text-white text-sm transition-colors">
          ◀ 게임 목록
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">{gameName ?? 'LOA - 게임 관전'}</span>
        <span className="text-gray-500 text-sm ml-1">게임 ID: {game_id?.slice(0, 8) ?? ''}…</span>
      </header>

      {/* Main area */}
      <main className="flex flex-1 overflow-hidden p-4 gap-4 justify-center">

        {/* Phaser game column */}
        <div className="shrink-0 flex flex-col gap-4 overflow-y-auto scrollbar-custom" style={{ width: 800 }}>
          <div className="relative shrink-0">
            <PhaserGame
              tickData={tickData}
              eventQueueRef={eventQueueRef}
              myBotId={myBotId}
              followBotId={followBotId}
              myBotIcon={myBotIcon}
              zoomLevel={zoomLevel}
              onFollowChange={setFollowBotId}
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

          {gameEnd && <GameResultPanel data={gameEnd} colorMap={colorMapRef.current} />}
        </div>

        {/* Sidebar */}
        <aside className="flex flex-col gap-3 overflow-hidden h-full" style={{ width: 280, minWidth: 280 }}>

          {/* Tick / alive */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-col gap-1 shrink-0">
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">틱</span>
              <span className="font-mono font-medium">
                {tickData?.tick ?? 0}<span className="text-gray-600"> / 200</span>
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">생존</span>
              <span className="font-mono font-medium">
                {tickData?.alive_count ?? 0}<span className="text-gray-600"> / {totalBots}</span>
              </span>
            </div>
          </div>

          {/* 뷰 설정 */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-col gap-3 shrink-0">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">뷰 설정</h3>

            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">추적할 봇 (카메라 고정)</label>
              <select
                value={followBotId}
                onChange={e => setFollowBotId(e.target.value)}
                className="bg-gray-700 border border-gray-600 text-white text-xs rounded-lg px-2 py-1.5 outline-none focus:border-indigo-500 w-full"
              >
                {botIds.length > 0
                  ? botIds.map(id => <option key={id} value={id}>{id}</option>)
                  : <option value={followBotId}>{followBotId}</option>
                }
              </select>
            </div>

            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span className="text-xl leading-none">{myBotIcon}</span>
              <span>내 봇 아이콘 (게임 생성 시 설정됨)</span>
            </div>

            <div className="flex flex-col gap-1">
              <div className="flex justify-between items-center">
                <label className="text-xs text-gray-500">줌 레벨</label>
                <span className="text-xs font-mono text-indigo-400 font-semibold">{zoomLevel}×</span>
              </div>
              <input
                type="range" min={1} max={5} step={1} value={zoomLevel}
                onChange={e => setZoomLevel(Number(e.target.value))}
                className="w-full accent-indigo-500"
              />
              <div className="flex justify-between text-[10px] text-gray-600">
                <span>전체 맵</span>
                <span>근접 추적</span>
              </div>
            </div>
          </div>

          {/* Leaderboard */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-col gap-2 shrink-0">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">리더보드</h3>
            {(tickData?.bots.length ?? 0) === 0 ? (
              <p className="text-gray-600 text-xs">-</p>
            ) : (
              <div className="overflow-y-auto scrollbar-custom flex flex-col gap-1" style={{ maxHeight: 140 }}>
                {[...(tickData?.bots ?? [])]
                  .sort((a: BotState, b: BotState) => b.score - a.score)
                  .map((bot: BotState, i: number) => (
                    <div key={bot.id} className="flex items-center gap-2 text-sm">
                      <span className="text-gray-500 w-5 text-right shrink-0 text-xs">#{i + 1}</span>
                      <span className="text-base leading-none shrink-0">
                        {getBotIcon(bot.id, bot.id === myBotId, myBotIcon)}
                      </span>
                      <span
                        className={`flex-1 truncate font-medium text-xs ${!bot.alive ? 'opacity-35 line-through' : ''}`}
                        style={{ color: bot.id === myBotId ? '#ffd700' : (colorMapRef.current.get(bot.id) ?? '#aaa') }}
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
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide shrink-0">이벤트 로그</h3>
            <div className="overflow-y-auto flex flex-col gap-1 flex-1 scrollbar-custom">
              {events.length === 0 ? (
                <p className="text-gray-600 text-xs">이벤트 없음</p>
              ) : (
                events.map(ev => (
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

      {/* Footer */}
      <footer className="border-t border-gray-800 px-6 py-2 flex items-center gap-4 text-xs shrink-0">
        <span>연결 상태:{' '}
          <span className={`font-medium ${gameStatusLabel.cls}`}>{gameStatusLabel.text}</span>
        </span>
        <span>WebSocket:{' '}
          <span className={`font-medium ${wsLabel.cls}`}>{wsLabel.text}</span>
        </span>
      </footer>

      {gameEnd && showModal && (
        <GameEndModal
          data={gameEnd} colorMap={colorMapRef.current}
          onClose={() => setShowModal(false)} onGoList={() => navigate('/games')}
        />
      )}
    </div>
  )
}

// ── Game Result Panel ──────────────────────────────────────────────────

function GameResultPanel({ data, colorMap }: { data: GameEndData; colorMap: Map<string, string> }) {
  const [openId, setOpenId] = useState<string | null>(null)
  const winner = data.rankings[0]

  return (
    <div className="flex flex-col gap-4 pb-4">
      <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/5 px-6 py-5 text-center flex flex-col gap-1">
        <p className="text-xs text-gray-500 uppercase tracking-widest">
          게임 종료 · {REASON_LABEL[data.reason] ?? data.reason}
        </p>
        <p className="text-3xl font-bold mt-1" style={{ color: colorMap.get(winner?.id) ?? '#facc15' }}>
          🏆 {winner?.id ?? '?'}
        </p>
        <p className="text-sm text-gray-400 mt-0.5">
          최종 점수{' '}
          <span className="text-white font-mono font-semibold">
            {(winner?.final_score ?? winner?.score ?? 0).toFixed(1)}
          </span>점
        </p>
      </div>

      <div className="flex flex-col gap-2">
        {data.rankings.map(r => {
          const color      = colorMap.get(r.id) ?? '#888'
          const finalScore = r.final_score ?? r.score ?? 0
          const killPts    = r.kills * 30
          const survPts    = r.survival_ticks * 0.1
          const bonusPts   = r.survival_bonus ?? 0
          const miningPts  = Math.max(0, finalScore - killPts - survPts - bonusPts)
          const isOpen     = openId === r.id
          const isWinner   = r.rank === 1

          return (
            <div key={r.id}
              className="rounded-xl border overflow-hidden cursor-pointer transition-colors"
              style={{ borderColor: isOpen ? color + '66' : '#1f2937' }}
              onClick={() => setOpenId(isOpen ? null : r.id)}
            >
              <div className="flex items-center gap-3 px-4 py-3"
                style={{ background: isOpen ? color + '12' : undefined }}>
                <span className="text-gray-500 text-sm w-6 shrink-0">#{r.rank}</span>
                {isWinner && <span className="text-base leading-none">🏆</span>}
                <span className="flex-1 font-semibold text-sm truncate" style={{ color }}>{r.id}</span>
                <span className="font-mono text-sm text-white shrink-0">{finalScore.toFixed(1)}점</span>
                <span className="text-gray-600 text-xs ml-1">{isOpen ? '▲' : '▼'}</span>
              </div>
              {isOpen && (
                <div className="px-4 pb-4 pt-1 flex flex-col gap-2 border-t border-gray-800">
                  <div className="grid grid-cols-2 gap-2 mt-1">
                    <DetailItem icon="⛏️" label="채굴"      value={`${r.minerals_mined}회`} pts={miningPts} color="#facc15" />
                    <DetailItem icon="⚔️" label="킬"        value={`${r.kills}회`}          pts={killPts}  color="#f87171" />
                    <DetailItem icon="⏱️" label="생존 틱"   value={`${r.survival_ticks}틱`} pts={survPts}  color="#4ade80" />
                    {bonusPts > 0 && (
                      <DetailItem icon="🏅" label="생존 보너스" value="생존 순위" pts={bonusPts} color="#a78bfa" />
                    )}
                    <div className="rounded-lg bg-gray-800/60 px-3 py-2 flex flex-col gap-0.5">
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
  data, colorMap, onClose, onGoList,
}: {
  data: GameEndData; colorMap: Map<string, string>; onClose: () => void; onGoList: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-lg p-6 flex flex-col gap-5">
        <div className="text-center">
          <p className="text-xs text-gray-500 mb-1">게임 종료</p>
          <h2 className="text-xl font-bold">{REASON_LABEL[data.reason] ?? data.reason}</h2>
        </div>
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
              {data.rankings.map(r => (
                <tr key={r.id} className="border-b border-gray-800/50">
                  <td className="py-1.5 text-gray-500">#{r.rank}</td>
                  <td className="py-1.5 font-medium truncate max-w-[120px]"
                    style={{ color: colorMap.get(r.id) ?? '#ccc' }}>{r.id}</td>
                  <td className="py-1.5 text-right font-mono">{(r.final_score ?? r.score ?? 0).toFixed(1)}</td>
                  <td className="py-1.5 text-right text-gray-400">{r.kills}</td>
                  <td className="py-1.5 text-right text-gray-400">{r.minerals_mined}</td>
                  <td className="py-1.5 text-right text-gray-400">{r.survival_ticks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex gap-3">
          <button onClick={onClose}
            className="flex-1 border border-gray-700 hover:border-gray-500 text-gray-300 hover:text-white text-sm rounded-lg py-2 transition-colors">
            닫기
          </button>
          <button onClick={onGoList}
            className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg py-2 transition-colors">
            게임 목록으로
          </button>        </div>
      </div>
    </div>
  )
}
