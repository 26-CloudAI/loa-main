import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import GodotGame from '../game/GodotGame'
import { BR2_API_BASE } from '../br2'
import { useAuth } from '../context/AuthContext'

interface LbRow { name: string; score: number; alive: boolean }

// 봇 이름 → 고정 색상 (관전 페이지와 동일 팔레트)
const BOT_PALETTE = ['#f87171', '#4ade80', '#facc15', '#fb923c', '#60a5fa', '#c084fc', '#22d3ee', '#f472b6']

/**
 * BR2(Godot) 리플레이 페이지.
 * Godot 을 replay 모드로 띄우면 {BR2_API_BASE}/api/games/{id}/replay 를 받아
 * frame_player 로 재생한다(재생/일시정지/배속 컨트롤은 Godot 캔버스 안에 표시).
 * 우측 리더보드 봇 클릭 시 해당 봇 시점으로 전환(관전 페이지와 동일 — Godot _poll_follow).
 */
export default function BattleRoyale2ReplayPage() {
  const navigate = useNavigate()
  const { game_id } = useParams()
  const { token } = useAuth()
  const matchId = game_id ?? ''

  const [gameName, setGameName] = useState<string | null>(null)
  const [time, setTime] = useState(0)   // 경과 시간(카운트업)
  const [phase, setPhase] = useState(1)
  const [alive, setAlive] = useState(0)
  const [lb, setLb] = useState<LbRow[]>([])
  const [follow, setFollow] = useState<{ bot: string; nonce: number } | null>(null)

  useEffect(() => {
    if (!matchId) return
    fetch(`${BR2_API_BASE}/api/games/${matchId}/result`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.name) setGameName(data.name) })
      .catch(() => {})
  }, [matchId, token])

  // 봇 이름 → 고정 색상 (등장 순서대로 팔레트 배정)
  const colorMapRef = useRef<Map<string, string>>(new Map())
  function botColor(name: string): string {
    const m = colorMapRef.current
    if (!m.has(name)) m.set(name, BOT_PALETTE[m.size % BOT_PALETTE.length])
    return m.get(name)!
  }

  useEffect(() => {
    function onMsg(e: MessageEvent) {
      let msg: any = e.data
      if (typeof msg === 'string') {
        try { msg = JSON.parse(msg) } catch { return }
      }
      if (!msg || typeof msg !== 'object' || msg.type !== 'hud') return
      setTime(Math.max(0, Math.floor(msg.time ?? 0)))
      setPhase(msg.phase ?? 1)
      setAlive(msg.alive ?? 0)
      const newLb = Array.isArray(msg.leaderboard) ? msg.leaderboard : []
      setLb(newLb)
      // 리더보드 첫 수신 시 1등 봇 자동 선택
      setFollow(prev => prev ?? (newLb[0] ? { bot: newLb[0].name, nonce: Date.now() } : null))
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])

  const mm = String(Math.floor(time / 60)).padStart(2, '0')
  const ss = String(time % 60).padStart(2, '0')

  return (
    <div className="fixed inset-0 bg-gray-950 flex flex-col">
      {/* 상단 바 */}
      <div className="shrink-0 h-11 px-4 flex items-center gap-2 bg-gray-900/90 backdrop-blur border-b border-gray-800 text-sm z-50">
        <button
          onClick={() => navigate('/games/list')}
          className="flex items-center gap-1 text-gray-300 hover:text-white transition-colors font-medium"
        >
          ◀ 나가기
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">🎬 {gameName ? `${gameName} 리플레이` : '리플레이'}</span>
      </div>

      {/* 게임 영역 */}
      <div className="flex-1 flex items-center justify-center gap-4 p-4 min-h-0">

        {/* 게임 화면 (정사각형) — 리플레이 모드 */}
        <div
          className="relative rounded-xl overflow-hidden ring-1 ring-gray-800 shadow-2xl h-full shrink-0"
          style={{ aspectRatio: '1 / 1', maxWidth: '100%' }}
        >
          <GodotGame matchId={matchId || undefined} replay apiBase={BR2_API_BASE} token={token} follow={follow} />
        </div>

        {/* 우측 패널 */}
        <aside className="w-72 shrink-0 h-full flex flex-col gap-3 overflow-hidden">
          {/* 시간/상태 */}
          <div className="rounded-2xl bg-gray-800/80 px-4 py-3 flex items-center justify-between text-sm">
            <span className="font-semibold text-indigo-300">⏱ {mm}:{ss}</span>
            <span className="text-gray-400">ZONE P{phase}</span>
            <span className="text-emerald-400">생존 {alive}</span>
          </div>

          {/* 시점 선택 + 리더보드 통합 */}
          <div className="rounded-2xl bg-gray-800/80 p-4 flex flex-col gap-2">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-sm font-bold text-gray-200">리더보드</h3>
              <span className="text-xs text-gray-500">클릭하여 시점 변경</span>
            </div>


            <ul className="space-y-0.5">
              {lb.map((row, i) => {
                const color = botColor(row.name)
                const isActive = follow?.bot === row.name
                return (
                  <li
                    key={row.name}
                    onClick={() => setFollow({ bot: row.name, nonce: Date.now() })}
                    className="flex items-center justify-between text-sm cursor-pointer rounded-lg px-2 py-1.5 transition-colors"
                    style={{
                      background: isActive ? color + '18' : 'transparent',
                      outline: isActive ? `1px solid ${color}50` : 'none',
                    }}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ background: row.alive ? color : '#4b5563' }}
                      />
                      <span className="truncate" style={{ color: row.alive ? color : '#6b7280', opacity: row.alive ? 1 : 0.55 }}>
                        {i + 1}. {row.name}{row.alive ? '' : ' ☠'}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0 ml-2">
                      <span className="tabular-nums text-gray-400 text-xs" style={{ opacity: row.alive ? 1 : 0.45 }}>
                        {Math.round(row.score)}
                      </span>
                      {isActive && <span className="text-xs" style={{ color }}>◀</span>}
                    </div>
                  </li>
                )
              })}
              {lb.length === 0 && <li className="text-xs text-gray-500 px-2">로딩 중…</li>}
            </ul>
          </div>

          <p className="text-xs text-gray-600 px-1">재생·배속 컨트롤은 게임 화면 안에 있습니다.</p>
        </aside>

      </div>
    </div>
  )
}
