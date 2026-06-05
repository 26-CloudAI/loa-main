import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { BR2_API_BASE } from '../br2'

interface RankRow {
  rank: number | null
  bot_name: string
  is_ai_filler: boolean
  score: number | null
  kills: number
  minerals_mined: number
  survival_ticks: number
}
interface ResultData {
  game_id: string
  name: string | null
  status: string
  end_reason: string | null
  finished_at: string | null
  final_tick: number | null
  rankings: RankRow[]
}

const REASON_LABEL: Record<string, string> = {
  last_standing: '최후의 1봇 생존',
  max_ticks: '시간 만료',
}
const BOT_PALETTE = ['#f87171', '#4ade80', '#facc15', '#fb923c', '#60a5fa', '#c084fc', '#22d3ee', '#f472b6']

export default function BattleRoyale2ResultPage() {
  const navigate = useNavigate()
  const { game_id } = useParams()
  const { token } = useAuth()
  const [data, setData] = useState<ResultData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!game_id) return
    let alive = true
    async function load() {
      try {
        const res = await fetch(`${BR2_API_BASE}/api/games/${game_id}/result`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        if (!res.ok) throw new Error(`결과를 불러오지 못했습니다 (${res.status})`)
        const json = await res.json()
        if (alive) { setData(json); setError('') }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : '오류')
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return () => { alive = false }
  }, [game_id, token])

  function botColor(i: number): string { return BOT_PALETTE[i % BOT_PALETTE.length] }

  return (
    <div className="min-h-screen bg-gray-950 text-white px-4 py-8">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <button onClick={() => navigate(-1)} className="text-gray-400 hover:text-white text-sm">◀ 뒤로</button>
          <span className="text-gray-600">|</span>
          <span className="font-bold">⚔️ 배틀로얄 2D 결과</span>
        </div>

        {loading && <p className="text-gray-400">불러오는 중…</p>}
        {error && <div className="text-red-400 bg-red-500/10 rounded-lg px-4 py-3">{error}</div>}

        {data && (
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 flex flex-col gap-5">
            <div className="text-center">
              <p className="text-xs text-gray-500 mb-1">{data.name ?? data.game_id.slice(0, 8)}</p>
              <h2 className="text-xl font-bold">
                {data.status === 'finished'
                  ? (REASON_LABEL[data.end_reason ?? ''] ?? data.end_reason ?? '게임 종료')
                  : '진행 중'}
              </h2>
            </div>

            {data.status !== 'finished' && (
              <p className="text-center text-gray-400 text-sm">아직 진행 중인 게임입니다.</p>
            )}

            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="py-1.5 text-left w-10">순위</th>
                  <th className="py-1.5 text-left">봇</th>
                  <th className="py-1.5 text-right">점수</th>
                  <th className="py-1.5 text-right">킬</th>
                  <th className="py-1.5 text-right">코인</th>
                  <th className="py-1.5 text-right">생존틱</th>
                </tr>
              </thead>
              <tbody>
                {data.rankings.map((r, i) => (
                  <tr key={r.bot_name} className="border-b border-gray-800/50">
                    <td className="py-1.5 text-gray-500">{r.rank != null ? `#${r.rank}` : '-'}</td>
                    <td className="py-1.5 font-medium truncate max-w-[160px]" style={{ color: botColor(i) }}>
                      {r.bot_name}{r.is_ai_filler ? ' (AI)' : ''}
                    </td>
                    <td className="py-1.5 text-right font-mono text-gray-200">{(r.score ?? 0).toFixed(1)}</td>
                    <td className="py-1.5 text-right text-gray-400">{r.kills}</td>
                    <td className="py-1.5 text-right text-gray-400">{r.minerals_mined}</td>
                    <td className="py-1.5 text-right text-gray-400">{r.survival_ticks}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="flex gap-3">
              <button onClick={() => navigate('/games/list')}
                className="flex-1 border border-gray-700 hover:border-gray-500 text-gray-300 hover:text-white text-sm rounded-lg py-2">
                게임 목록
              </button>
              <button onClick={() => navigate(`/games/${game_id}/battleroyale/watch`)}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg py-2">
                다시 관전
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
