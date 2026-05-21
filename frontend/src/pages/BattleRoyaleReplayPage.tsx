import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import PhaserGame from '../game/PhaserGame'
import type { TickData, GameEvent } from '../game/BattleRoyaleScene'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'

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
interface ReplayEvent {
  event_type: string; actor_id: string; target_id?: string; detail?: string
}
interface ReplayFrame {
  tick_data: FullTickData; events: ReplayEvent[]
}
interface ReplayData {
  game_id: string; total_frames: number; frames: ReplayFrame[]; result: GameEndData | null
}

// ── Constants ──────────────────────────────────────────────────────────

const SPEEDS = [0.5, 1, 2, 4]

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

export default function BattleRoyaleReplayPage() {
  const { game_id } = useParams<{ game_id: string }>()
  const { token }   = useAuth()
  const navigate    = useNavigate()

  const colorMapRef    = useRef<Map<string, string>>(new Map())
  const eventUidRef    = useRef(0)
  const eventQueueRef  = useRef<GameEvent[]>([])
  const mainRef        = useRef<HTMLDivElement>(null)
  const playTimerRef   = useRef<ReturnType<typeof setInterval> | null>(null)

  const [replayData,  setReplayData]  = useState<ReplayData | null>(null)
  const [frameIdx,    setFrameIdx]    = useState(0)
  const [isPlaying,   setIsPlaying]   = useState(false)
  const [speedIdx,    setSpeedIdx]    = useState(1)  // 기본 1×
  const [tickData,    setTickData]    = useState<FullTickData | null>(null)
  const [events,      setEvents]      = useState<EventLog[]>([])
  const [loadError,   setLoadError]   = useState('')
  const [loading,     setLoading]     = useState(true)
  const [gameName,    setGameName]    = useState<string | null>(null)
  const [followBotId, setFollowBotId] = useState<string>('')
  const [zoomLevel,   setZoomLevel]   = useState(3)
  const [totalBots,   setTotalBots]   = useState(0)

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

  // 반응형 게임 사이즈
  const SIDEBAR_TOTAL = 280 + 16 + 32
  const CHROME_H = 56 + 36 + 32
  const [gameSize, setGameSize] = useState(() =>
    Math.max(300, Math.min(
      (typeof window !== 'undefined' ? window.innerWidth : 900) - SIDEBAR_TOTAL,
      (typeof window !== 'undefined' ? window.innerHeight : 900) - CHROME_H,
    ))
  )

  useEffect(() => {
    const main = mainRef.current
    if (!main) return
    const update = () => {
      const avH = main.clientHeight - 32
      const avW = main.clientWidth - SIDEBAR_TOTAL - 16
      setGameSize(Math.max(280, Math.min(avW, avH)))
    }
    const obs = new ResizeObserver(update)
    obs.observe(main)
    update()
    return () => obs.disconnect()
  }, [])

  // 리플레이 데이터 로드
  useEffect(() => {
    if (!game_id || !token) return
    setLoading(true)
    fetch(`${API_BASE}/api/games/${game_id}/replay`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => {
        if (!r.ok) throw new Error(`리플레이를 불러올 수 없습니다. (${r.status})`)
        return r.json()
      })
      .then((data: ReplayData) => {
        // colorMap 초기화
        for (const frame of data.frames) {
          for (const bot of frame.tick_data.bots ?? []) {
            if (!colorMapRef.current.has(bot.id)) {
              colorMapRef.current.set(bot.id, hashColor(bot.id))
            }
          }
        }
        setReplayData(data)
        setTotalBots(data.frames[0]?.tick_data?.bots?.length ?? 0)
        // 게임 이름 조회
        fetch(`${API_BASE}/api/games/${game_id}`, {
          headers: { Authorization: `Bearer ${token}` },
        }).then(r => r.ok ? r.json() : null).then(info => {
          if (info?.name) setGameName(info.name)
        }).catch(() => {})
        // 첫 프레임 적용
        applyFrame(data.frames, 0)
        setLoading(false)
      })
      .catch(e => {
        setLoadError(e.message)
        setLoading(false)
      })
  }, [game_id, token])

  // 프레임 적용: tick_data 세팅 + 이벤트 누적
  const applyFrame = useCallback((frames: ReplayFrame[], idx: number) => {
    if (!frames || frames.length === 0) return
    const frame = frames[idx]
    if (!frame) return

    setTickData(frame.tick_data)

    // followBotId가 없으면 첫 봇으로 초기화
    setFollowBotId(prev => {
      if (prev) return prev
      return frame.tick_data.bots?.[0]?.id ?? myBotId
    })

    // 0..idx 구간 이벤트 누적 (최대 100개, 역순)
    const accumulated: EventLog[] = []
    for (let i = 0; i <= idx; i++) {
      const f = frames[i]
      if (!f) continue
      for (const ev of f.events) {
        accumulated.push({
          uid: eventUidRef.current++,
          tick: f.tick_data.tick,
          type: ev.event_type,
          actor_id: ev.actor_id,
          target_id: ev.target_id,
          detail: ev.detail,
        })
      }
    }
    setEvents(accumulated.reverse().slice(0, 100))
  }, [myBotId])

  // 자동 재생
  useEffect(() => {
    if (!isPlaying || !replayData) return
    const ms = 1000 / SPEEDS[speedIdx]
    playTimerRef.current = setInterval(() => {
      setFrameIdx(prev => {
        const next = prev + 1
        if (next >= replayData.total_frames) {
          setIsPlaying(false)
          return prev
        }
        applyFrame(replayData.frames, next)
        return next
      })
    }, ms)
    return () => {
      if (playTimerRef.current) clearInterval(playTimerRef.current)
    }
  }, [isPlaying, speedIdx, replayData, applyFrame])

  // 스크러버 또는 버튼으로 수동 이동
  function seekTo(idx: number) {
    if (!replayData) return
    const clamped = Math.max(0, Math.min(idx, replayData.total_frames - 1))
    setFrameIdx(clamped)
    applyFrame(replayData.frames, clamped)
  }

  function togglePlay() {
    if (!replayData) return
    if (frameIdx >= replayData.total_frames - 1) {
      // 끝이면 처음부터 다시
      seekTo(0)
      setIsPlaying(true)
      return
    }
    setIsPlaying(prev => !prev)
  }

  const totalFrames = replayData?.total_frames ?? 0
  const isAtEnd = frameIdx >= totalFrames - 1
  const botIds = tickData ? tickData.bots.map((b: BotState) => b.id) : []
  const showResult = isAtEnd && !!replayData?.result

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
        <button onClick={() => navigate('/games')}
          className="text-sm text-indigo-400 hover:text-indigo-300 underline underline-offset-2">
          게임 목록으로
        </button>
      </div>
    )
  }

  return (
    <div className="h-screen bg-gray-900 text-white flex flex-col overflow-hidden">
      {/* Header */}
      <header className="sticky top-0 z-20 h-14 px-6 flex items-center gap-3 shrink-0" style={{ background: 'rgba(13,15,20,.92)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>
        <button onClick={() => navigate('/games')}
          className="text-gray-400 hover:text-white text-sm transition-colors">
          ◀ 게임 목록
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">{gameName ?? 'LOA - 리플레이'}</span>
        <span className="text-gray-500 text-sm ml-1">게임 ID: {game_id?.slice(0, 8) ?? ''}…</span>
        <span className="ml-2 text-xs font-medium bg-indigo-600/30 text-indigo-300 border border-indigo-600/50 rounded-full px-2 py-0.5">
          🎬 리플레이
        </span>
      </header>

      {/* Main area */}
      <main ref={mainRef} className="flex flex-1 overflow-hidden p-4 gap-4 min-w-0 justify-center">

        {/* Phaser game + controls column */}
        <div className="shrink-0 flex flex-col gap-3 overflow-y-auto scrollbar-custom" style={{ width: gameSize }}>
          {/* Phaser */}
          <div className="relative shrink-0">
            <PhaserGame
              tickData={tickData}
              eventQueueRef={eventQueueRef}
              myBotId={myBotId}
              followBotId={followBotId}
              myBotIcon={myBotIcon}
              zoomLevel={zoomLevel}
              onFollowChange={setFollowBotId}
              width={gameSize}
              height={gameSize}
            />
          </div>

          {/* 재생 컨트롤 */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-col gap-3 shrink-0">
            {/* 재생 버튼 행 */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1">
                {/* 처음으로 */}
                <button
                  onClick={() => { setIsPlaying(false); seekTo(0) }}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-700 hover:bg-gray-600 text-sm transition-colors"
                  title="처음으로"
                >⏮</button>
                {/* 10 프레임 뒤로 */}
                <button
                  onClick={() => { setIsPlaying(false); seekTo(frameIdx - 10) }}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-700 hover:bg-gray-600 text-sm transition-colors"
                  title="10 프레임 뒤로"
                >⏪</button>
                {/* 재생/정지 */}
                <button
                  onClick={togglePlay}
                  className="w-10 h-8 flex items-center justify-center rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-bold transition-colors"
                  title={isPlaying ? '일시정지' : '재생'}
                >
                  {isPlaying ? '⏸' : '▶'}
                </button>
                {/* 10 프레임 앞으로 */}
                <button
                  onClick={() => { setIsPlaying(false); seekTo(frameIdx + 10) }}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-700 hover:bg-gray-600 text-sm transition-colors"
                  title="10 프레임 앞으로"
                >⏩</button>
                {/* 끝으로 */}
                <button
                  onClick={() => { setIsPlaying(false); seekTo(totalFrames - 1) }}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-gray-700 hover:bg-gray-600 text-sm transition-colors"
                  title="끝으로"
                >⏭</button>
              </div>

              {/* 속도 선택 */}
              <div className="flex items-center gap-1">
                <span className="text-xs text-gray-500 mr-1">속도</span>
                {SPEEDS.map((s, i) => (
                  <button
                    key={s}
                    onClick={() => setSpeedIdx(i)}
                    className={`text-xs px-2 py-1 rounded transition-colors ${
                      speedIdx === i
                        ? 'bg-indigo-600 text-white'
                        : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                    }`}
                  >
                    {s}×
                  </button>
                ))}
              </div>
            </div>

            {/* 스크러버 */}
            <div className="flex flex-col gap-1">
              <input
                type="range"
                min={0}
                max={Math.max(0, totalFrames - 1)}
                value={frameIdx}
                onChange={e => { setIsPlaying(false); seekTo(Number(e.target.value)) }}
                className="w-full accent-indigo-500"
              />
              <div className="flex justify-between text-xs text-gray-500">
                <span>프레임 {frameIdx + 1}</span>
                <span>전체 {totalFrames}</span>
              </div>
            </div>
          </div>

          {/* 결과 패널 (마지막 프레임 도달 시) */}
          {showResult && replayData?.result && (
            <GameResultPanel data={replayData.result} colorMap={colorMapRef.current} />
          )}
        </div>

        {/* Sidebar */}
        <aside className="shrink-0 flex flex-col gap-3 overflow-hidden h-full" style={{ width: 280 }}>

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
              <span>내 봇 아이콘</span>
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
        <span className="text-gray-500">
          🎬 리플레이 모드 · 프레임 {frameIdx + 1} / {totalFrames}
        </span>
        <span className="text-gray-600">|</span>
        <span className="text-gray-500">속도 {SPEEDS[speedIdx]}×</span>
      </footer>
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
