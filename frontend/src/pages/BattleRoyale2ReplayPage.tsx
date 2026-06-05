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
  const shortId = matchId ? matchId.slice(0, 8) : ''

  const [time, setTime] = useState(0)   // 경과 시간(카운트업)
  const [phase, setPhase] = useState(1)
  const [alive, setAlive] = useState(0)
  const [lb, setLb] = useState<LbRow[]>([])
  const [follow, setFollow] = useState<{ bot: string; nonce: number } | null>(null)

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
      setLb(Array.isArray(msg.leaderboard) ? msg.leaderboard : [])
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])

  const mm = String(Math.floor(time / 60)).padStart(2, '0')
  const ss = String(time % 60).padStart(2, '0')

  return (
    <div className="fixed inset-0 bg-gray-950 flex items-center justify-center gap-4 p-6">
      {/* 상단 바 */}
      <div className="absolute top-3 left-4 z-50 flex items-center gap-2 rounded-xl bg-gray-900/85 backdrop-blur px-3 py-1.5 ring-1 ring-gray-700 text-sm">
        <button
          onClick={() => navigate('/games')}
          className="flex items-center gap-1 text-gray-300 hover:text-white transition-colors font-medium"
        >
          ◀ 나가기
        </button>
        <span className="text-gray-600">|</span>
        <span className="flex items-center gap-1.5 font-semibold text-indigo-300">
          🎬 배틀로얄 2D 리플레이
          {shortId && <span className="text-gray-500 font-mono text-xs">#{shortId}</span>}
        </span>
      </div>

      {/* 게임 화면 (정사각형) — 리플레이 모드 */}
      <div
        className="relative rounded-xl overflow-hidden ring-1 ring-gray-800 shadow-2xl h-full shrink-0"
        style={{ aspectRatio: '1 / 1', maxWidth: '100%' }}
      >
        <GodotGame matchId={matchId || undefined} replay apiBase={BR2_API_BASE} token={token} follow={follow} />
      </div>

      {/* 우측 패널 — 상태 + 리더보드(클릭 시점전환) */}
      <aside className="w-72 shrink-0 h-full flex flex-col gap-3 overflow-hidden">
        <div className="rounded-2xl bg-gray-800/80 px-4 py-3 flex items-center justify-between text-sm">
          <span className="font-semibold text-indigo-300">⏱ {mm}:{ss}</span>
          <span className="text-gray-400">ZONE P{phase}</span>
          <span className="text-emerald-400">생존 {alive}</span>
        </div>

        <div className="rounded-2xl bg-gray-800/80 p-4">
          <h3 className="text-sm font-bold text-gray-200 mb-2">리더보드</h3>
          <ul className="space-y-1.5">
            {lb.map((row, i) => (
              <li
                key={row.name}
                onClick={() => setFollow({ bot: row.name, nonce: Date.now() })}
                title="클릭하면 이 봇 시점으로"
                className="flex items-center justify-between text-sm cursor-pointer rounded px-1 hover:bg-white/5"
              >
                <span className="truncate" style={{ color: botColor(row.name), opacity: row.alive ? 1 : 0.45 }}>
                  {i + 1}. {row.name}{row.alive ? '' : ' ☠'}
                </span>
                <span className="ml-2 tabular-nums text-gray-300" style={{ opacity: row.alive ? 1 : 0.45 }}>
                  {Math.round(row.score)}
                </span>
              </li>
            ))}
            {lb.length === 0 && <li className="text-xs text-gray-500">로딩 중…</li>}
          </ul>
        </div>

        <p className="text-xs text-gray-600 px-1">재생·배속 컨트롤은 게임 화면 안에 있습니다.</p>
      </aside>
    </div>
  )
}
