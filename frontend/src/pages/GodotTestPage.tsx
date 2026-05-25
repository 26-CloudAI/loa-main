import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import GodotGame from '../game/GodotGame'

// Godot(iframe) → postMessage 로 받는 메시지 타입
interface LbRow { name: string; score: number; alive: boolean }
interface LogLine { id: number; text: string; color: string }
interface RankRow {
  id: string; name: string; rank: number; score: number
  kills: number; minerals_mined: number; survival_ticks: number; alive: boolean
}

// 기존 배틀로얄과 동일한 종료 사유 라벨
const REASON_LABEL: Record<string, string> = {
  last_standing: '최후의 1봇 생존!',
  max_ticks: '최대 틱(200) 도달',
  all_minerals_depleted: '모든 광물 소진',
}

// 봇별 고정 색상 팔레트 (이름 등장 순서대로 배정)
const BOT_PALETTE = ['#f87171', '#4ade80', '#facc15', '#fb923c', '#60a5fa', '#c084fc', '#22d3ee', '#f472b6']

/**
 * 새 Godot 배틀로얄 관전 페이지 (방식 B).
 * - 좌: 게임 iframe (Godot)
 * - 우: React 패널 (시간/생존/리더보드 + 전투 로그)
 * Godot 이 window.parent.postMessage 로 보내는 데이터를 수신해 렌더.
 */
export default function GodotTestPage() {
  const navigate = useNavigate()
  const [time, setTime] = useState(180)
  const [phase, setPhase] = useState(1)
  const [alive, setAlive] = useState(0)
  const [lb, setLb] = useState<LbRow[]>([])
  const [logs, setLogs] = useState<LogLine[]>([])
  const [result, setResult] = useState<{ reason: string; rankings: RankRow[] } | null>(null)
  const [showModal, setShowModal] = useState(true)
  const logId = useRef(0)
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
      if (!msg || typeof msg !== 'object' || !msg.type) return
      switch (msg.type) {
        case 'hud':
          setTime(Math.max(0, Math.floor(msg.time ?? 0)))
          setPhase(msg.phase ?? 1)
          setAlive(msg.alive ?? 0)
          setLb(Array.isArray(msg.leaderboard) ? msg.leaderboard : [])
          break
        case 'log':
          setLogs(prev => {
            const next = [...prev, { id: logId.current++, text: String(msg.text ?? ''), color: '#' + (msg.color || 'ffffff') }]
            return next.slice(-12)
          })
          break
        case 'match_end':
          setResult({ reason: String(msg.reason ?? ''), rankings: Array.isArray(msg.rankings) ? msg.rankings : [] })
          setShowModal(true)
          break
      }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])

  const mm = String(Math.floor(time / 60)).padStart(2, '0')
  const ss = String(time % 60).padStart(2, '0')

  return (
    <div className="fixed inset-0 bg-gray-950 flex items-center justify-center gap-4 p-6">
      {/* 게임 화면 — 높이에 맞춘 정사각형 */}
      <div
        className="relative rounded-xl overflow-hidden ring-1 ring-gray-800 shadow-2xl h-full shrink-0"
        style={{ aspectRatio: '1 / 1', maxWidth: '100%' }}
      >
        <GodotGame matchId={new URLSearchParams(window.location.search).get('match') ?? undefined} />
      </div>

      {/* 패널 — 게임 바로 옆 (그룹이 함께 중앙 정렬) */}
      <aside className="w-80 shrink-0 h-full flex flex-col gap-3 overflow-hidden">
        {/* 상단 스탯 */}
        <div className="rounded-2xl bg-gray-800/80 px-4 py-3 flex items-center justify-between text-sm">
          <span className="font-semibold text-indigo-300">⏱ {mm}:{ss}</span>
          <span className="text-gray-400">ZONE P{phase}</span>
          <span className="text-emerald-400">생존 {alive}</span>
        </div>

        {/* 리더보드 */}
        <div className="rounded-2xl bg-gray-800/80 p-4">
          <h3 className="text-sm font-bold text-gray-200 mb-2">리더보드</h3>
          <ul className="space-y-1.5">
            {lb.map((row, i) => (
              <li key={row.name} className="flex items-center justify-between text-sm">
                <span className="truncate" style={{ color: botColor(row.name), opacity: row.alive ? 1 : 0.45 }}>
                  {i + 1}. {row.name}{row.alive ? '' : ' ☠'}
                </span>
                <span className="ml-2 tabular-nums text-gray-300" style={{ opacity: row.alive ? 1 : 0.45 }}>
                  {Math.round(row.score)}
                </span>
              </li>
            ))}
            {lb.length === 0 && <li className="text-xs text-gray-500">대기 중…</li>}
          </ul>
        </div>

        {/* 전투 로그 */}
        <div className="rounded-2xl bg-gray-800/80 p-4 flex-1 min-h-0 flex flex-col">
          <h3 className="text-sm font-bold text-gray-200 mb-2">전투 로그</h3>
          <ul className="space-y-1 overflow-y-auto text-xs leading-relaxed">
            {logs.map(l => (
              <li key={l.id} style={{ color: l.color }}>{l.text}</li>
            ))}
            {logs.length === 0 && <li className="text-gray-500">—</li>}
          </ul>
        </div>
      </aside>

      {/* 매치 종료 결과 모달 — 기존 배틀로얄과 동일 */}
      {result && showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-lg p-6 flex flex-col gap-5">
            <div className="text-center">
              <p className="text-xs text-gray-500 mb-1">게임 종료</p>
              <h2 className="text-xl font-bold text-gray-100">{REASON_LABEL[result.reason] ?? result.reason}</h2>
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
                  {result.rankings.map(r => (
                    <tr key={r.id} className="border-b border-gray-800/50">
                      <td className="py-1.5 text-gray-500">#{r.rank}</td>
                      <td className="py-1.5 font-medium truncate max-w-[120px]" style={{ color: botColor(r.name) }}>{r.name}</td>
                      <td className="py-1.5 text-right font-mono text-gray-200">{(r.score ?? 0).toFixed(1)}</td>
                      <td className="py-1.5 text-right text-gray-400">{r.kills}</td>
                      <td className="py-1.5 text-right text-gray-400">{r.minerals_mined}</td>
                      <td className="py-1.5 text-right text-gray-400">{r.survival_ticks}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex gap-3">
              <button onClick={() => setShowModal(false)}
                className="flex-1 border border-gray-700 hover:border-gray-500 text-gray-300 hover:text-white text-sm rounded-lg py-2 transition-colors">
                닫기
              </button>
              <button onClick={() => navigate('/games/list')}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg py-2 transition-colors">
                게임 목록으로
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
