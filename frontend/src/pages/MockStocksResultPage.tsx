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
  name: string | null
  status: string
  end_reason: string | null
  rankings: RankingEntry[]
}

function formatKRW(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  return value.toLocaleString()
}

function rowOpacity(rank: number): number {
  if (rank <= 3) return 1
  return Math.max(0.3, 1 - (rank - 3) * 0.18)
}

export default function MockStocksResultPage() {
  const { game_id } = useParams<{ game_id: string }>()
  const navigate = useNavigate()
  const [result, setResult] = useState<GameResult | null>(null)
  const [gameName, setGameName] = useState<string | null>(null)
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

    fetch(`${STOCKS_API}/api/games/history`)
      .then(r => r.ok ? r.json() : [])
      .then((games: any[]) => {
        const match = Array.isArray(games) ? games.find((g: any) => g.game_id === game_id) : null
        if (match?.name) setGameName(match.name)
      })
      .catch(() => {})
  }, [game_id])

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0D0F14',
      color: '#E8EAF0',
      backgroundImage: 'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
      backgroundSize: '24px 24px',
    }}>
      <header className="sticky top-0 z-20 h-14 px-6 flex items-center gap-4" style={{ background: 'rgba(13,15,20,.92)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>
        <button onClick={() => navigate('/games/list')} className="text-gray-400 hover:text-white transition-colors text-sm">
          ◀ 뒤로
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold text-lg">📈 모의주식 결과</span>
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8">
        {loading && <p className="text-gray-400">불러오는 중…</p>}
        {error && <div className="text-red-400 bg-red-500/10 rounded-lg px-4 py-3">{error}</div>}

        {result && (
          <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6 flex flex-col gap-5">
            <div className="text-center">
              <p className="text-xs text-gray-500 mb-1">
                {result.name ?? gameName ?? game_id?.slice(0, 8)}
              </p>
              <h2 className="text-xl font-bold">
                {result.status === 'finished' ? '게임 종료' : '진행 중'}
              </h2>
              {result.status !== 'finished' && (
                <p className="mt-1 text-sm text-gray-400">아직 진행 중인 게임입니다.</p>
              )}
            </div>

            {result.rankings.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs border-b border-gray-700">
                    <th className="py-1.5 text-center w-12">순위</th>
                    <th className="py-1.5 text-left">봇</th>
                    <th className="py-1.5 text-right">최종 자산</th>
                    <th className="py-1.5 text-right">수익률</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rankings.map((entry) => {
                    const profitPositive = (entry.profit_rate ?? 0) >= 0
                    const opacity = rowOpacity(entry.rank)
                    return (
                      <tr
                        key={entry.bot_id}
                        className="border-b border-gray-700/50 last:border-0"
                        style={{ opacity }}
                      >
                        <td className="py-1.5 font-bold text-gray-300 text-center">
                          {entry.rank === 1 ? '🥇' : entry.rank === 2 ? '🥈' : entry.rank === 3 ? '🥉' : `${entry.rank}`}
                        </td>
                        <td className="py-1.5 text-white font-medium">
                          {entry.bot_name ?? entry.bot_id}
                          {entry.is_ai_filler && <span className="ml-2 text-xs text-gray-500">AI</span>}
                        </td>
                        <td className="py-1.5 text-right text-gray-200 font-mono">
                          {formatKRW(entry.final_total_value)}
                        </td>
                        <td className={`py-1.5 text-right font-medium ${profitPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                          {profitPositive ? '+' : ''}{(entry.profit_rate ?? 0).toFixed(2)}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <p className="text-gray-500 text-sm text-center py-4">결과 데이터가 없습니다.</p>
            )}

            <div className="flex gap-3">
              <button
                onClick={() => navigate('/games/list')}
                className="flex-1 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded-lg py-2 transition-colors"
              >
                게임 목록
              </button>
              <button
                onClick={() => navigate(`/games/${game_id}/mock-stocks/replay`)}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg py-2 transition-colors"
              >
                🎬 리플레이
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
