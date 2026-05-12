import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'

interface RankingEntry {
  rank: number
  user_id: number
  username: string
  display_name: string
  elo: number
  wins: number
  losses: number
  games_played: number
  win_rate: number
}

function getTierLabel(elo: number): { label: string; color: string } {
  if (elo >= 2000) return { label: 'Grandmaster', color: 'text-red-400' }
  if (elo >= 1800) return { label: 'Master', color: 'text-purple-400' }
  if (elo >= 1600) return { label: 'Diamond', color: 'text-cyan-400' }
  if (elo >= 1450) return { label: 'Platinum', color: 'text-teal-400' }
  if (elo >= 1300) return { label: 'Gold', color: 'text-yellow-400' }
  if (elo >= 1150) return { label: 'Silver', color: 'text-gray-300' }
  if (elo >= 1000) return { label: 'Bronze', color: 'text-amber-600' }
  return { label: 'Iron', color: 'text-gray-500' }
}

export default function RankingPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [rankings, setRankings] = useState<RankingEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/api/rankings`)
      .then((r) => {
        if (!r.ok) throw new Error(`서버 오류 (${r.status})`)
        return r.json()
      })
      .then((data) => setRankings(data.rankings ?? []))
      .catch((e) => setError(e instanceof Error ? e.message : '랭킹을 불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="sticky top-0 z-20 h-14 border-b border-gray-800 bg-gray-950 px-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/games')}
            className="text-gray-400 hover:text-white text-sm transition-colors"
          >
            ◀ 게임 목록
          </button>
          <span className="text-gray-600">|</span>
          <span className="font-bold">리더보드</span>
        </div>
        <div className="flex items-center gap-4">
          {user && (
            <span className="text-sm text-gray-400">
              {user.display_name ?? user.username}
              <span className="ml-2 text-xs bg-indigo-600 rounded px-1 py-0.5">
                {user.role}
              </span>
            </span>
          )}
          <button
            onClick={handleLogout}
            className="text-sm bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-full px-4 py-1.5 transition-colors"
          >
            로그아웃
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold">리더보드</h2>
          <span className="text-sm text-gray-500">ELO 기준 전체 유저 랭킹</span>
        </div>

        {error && (
          <div className="mb-4 text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <span className="text-gray-500 text-sm">불러오는 중...</span>
          </div>
        ) : rankings.length === 0 ? (
          <div className="flex justify-center py-20">
            <p className="text-gray-500 text-sm">아직 랭킹 데이터가 없습니다.</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-gray-700">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-800 text-gray-400 text-center">
                  <th className="px-2 py-3">순위</th>
                  <th className="px-4 py-3">유저</th>
                  <th className="px-4 py-3">티어</th>
                  <th className="px-4 py-3">ELO</th>
                  <th className="px-4 py-3">전적</th>
                  <th className="px-4 py-3">승률</th>
                  <th className="px-4 py-3">코드 보기</th>
                </tr>
              </thead>
              <tbody>
                {rankings.map((entry, i) => {
                  const tier = getTierLabel(entry.elo)
                  const isMe = user && entry.username === user.username
                  return (
                    <tr
                      key={entry.user_id}
                      className={`border-t transition-colors ${
                        isMe
                          ? 'border-l-4 border-l-indigo-400 border-t-gray-700 bg-indigo-600/25'
                          : 'border-t-gray-700 hover:bg-gray-800/60'
                      }`}
                    >
                      <td className="px-4 py-3 font-mono text-gray-400 text-center">
                        {i < 3 ? (
                          <span
                            className={
                              i === 0
                                ? 'text-yellow-400 font-bold'
                                : i === 1
                                ? 'text-gray-300 font-bold'
                                : 'text-amber-600 font-bold'
                            }
                          >
                            {entry.rank}
                          </span>
                        ) : (
                          entry.rank
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <div className={`font-medium ${isMe ? 'text-indigo-300' : 'text-white'}`}>
                          {entry.display_name}
                        </div>
                        <div className="text-xs text-gray-500">{entry.username}</div>
                      </td>
                      <td className={`px-4 py-3 text-center font-medium ${tier.color}`}>
                        {tier.label}
                      </td>
                      <td className="px-4 py-3 text-center font-mono font-semibold text-white">
                        {entry.elo}
                      </td>
                      <td className="px-4 py-3 text-center text-gray-300">
                        <span className="text-green-400">{entry.wins}승</span>
                        {' / '}
                        <span className="text-red-400">{entry.losses}패</span>
                      </td>
                      <td className="px-4 py-3 text-center text-gray-300">
                        {(entry.win_rate * 100).toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => navigate(`/users/${entry.user_id}/bots`)}
                          className="text-xs text-indigo-400 hover:text-indigo-300 underline underline-offset-2 transition-colors"
                        >
                          봇 코드
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  )
}
