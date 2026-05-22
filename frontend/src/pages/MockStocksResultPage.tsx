import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'

const STOCKS_API = import.meta.env.VITE_STOCKS_API_BASE ?? 'http://localhost:8080/stocks'

interface RankingEntry {
  rank: number
  bot_id: string
  bot_name?: string
  is_ai_filler?: boolean
  final_total_value: number
  profit_rate: number
}

interface GameResult {
  game_id: string
  status: string
  final_tick: number | null
  end_reason: string | null
  finished_at: string | null
  rankings: RankingEntry[]
}

function formatKRW(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  return value.toLocaleString()
}

export default function MockStocksResultPage() {
  const { game_id } = useParams<{ game_id: string }>()
  const navigate = useNavigate()
  const [result, setResult] = useState<GameResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!game_id) return
    fetch(`${STOCKS_API}/api/games/${game_id}/result`)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status}`)
        return res.json() as Promise<GameResult>
      })
      .then((data) => setResult({
        ...data,
        rankings: Array.isArray(data.rankings) ? data.rankings : [],
      }))
      .catch((e) => setError(e instanceof Error ? e.message : '결과를 불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }, [game_id])

  const shortId = game_id?.slice(0, 8) ?? ''

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      {/* 헤더 */}
      <header className="sticky top-0 z-20 h-14 px-6 flex items-center gap-4" style={{ background: 'rgba(13,15,20,.92)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>
        <button
          onClick={() => navigate('/games/list')}
          className="text-gray-400 hover:text-white transition-colors text-sm"
        >
          ← 게임 목록
        </button>
        <span className="font-bold text-lg">League of Agents</span>
        <span className="ml-auto text-sm text-gray-500">모의주식 결과</span>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8">
        {/* 게임 ID + 메타 */}
        <div className="mb-6">
          <h2 className="text-xl font-semibold">게임 {shortId} 결과</h2>
          {result && (
            <div className="mt-1 flex gap-4 text-sm text-gray-400">
              {result.final_tick != null && <span>최종 틱 {result.final_tick}</span>}
              {result.end_reason && <span>종료 사유: {result.end_reason}</span>}
              {result.finished_at && (
                <span>{new Date(result.finished_at).toLocaleString('ko-KR')}</span>
              )}
            </div>
          )}
        </div>

        {/* 상태 */}
        {loading && (
          <div className="flex justify-center py-20">
            <span className="text-gray-500 text-sm">불러오는 중...</span>
          </div>
        )}
        {error && (
          <div className="text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {/* 랭킹 테이블 */}
        {result && result.rankings.length > 0 && (
          <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400 text-left">
                  <th className="px-4 py-3 w-16 text-center">순위</th>
                  <th className="px-4 py-3">봇</th>
                  <th className="px-4 py-3 text-right">최종 자산</th>
                  <th className="px-4 py-3 text-right">수익률</th>
                </tr>
              </thead>
              <tbody>
                {result.rankings.map((entry) => {
                  const isFiller = entry.is_ai_filler ?? false
                  const profitPositive = (entry.profit_rate ?? 0) >= 0
                  return (
                    <tr
                      key={entry.bot_id}
                      className={`border-b border-gray-700/50 last:border-0 ${isFiller ? 'opacity-50' : ''}`}
                    >
                      <td className="px-4 py-3 font-bold text-gray-300 text-center">
                        {entry.rank === 1 ? '🥇' : entry.rank === 2 ? '🥈' : entry.rank === 3 ? '🥉' : `${entry.rank}`}
                      </td>
                      <td className="px-4 py-3">
                        <span className={isFiller ? 'text-gray-400' : 'text-white font-medium'}>
                          {entry.bot_name ?? entry.bot_id}
                        </span>
                        {isFiller && (
                          <span className="ml-2 text-xs text-gray-600">AI</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-200 font-mono">
                        {formatKRW(entry.final_total_value)}
                      </td>
                      <td className={`px-4 py-3 text-right font-medium ${profitPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                        {profitPositive ? '+' : ''}{(entry.profit_rate ?? 0).toFixed(2)}%
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {result && result.rankings.length === 0 && !loading && (
          <p className="text-gray-500 text-sm text-center py-12">결과 데이터가 없습니다.</p>
        )}
      </main>
    </div>
  )
}
