import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'

interface BotInfo {
  id: number
  name: string
  description: string
  code: string
  version: number
  wins: number
  losses: number
  games_played: number
  win_rate: number
  updated_at: string
}

interface UserInfo {
  user_id: number
  username: string
  display_name: string
  elo: number
  wins: number
  losses: number
  games_played: number
}

export default function UserBotDetailPage() {
  const { user_id } = useParams<{ user_id: string }>()
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  const [userInfo, setUserInfo] = useState<UserInfo | null>(null)
  const [bots, setBots] = useState<BotInfo[]>([])
  const [selectedBot, setSelectedBot] = useState<BotInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user_id) return
    fetch(`${API_BASE}/api/users/${user_id}/bots`)
      .then((r) => {
        if (!r.ok) throw new Error(`서버 오류 (${r.status})`)
        return r.json()
      })
      .then((data) => {
        setUserInfo(data.user)
        setBots(data.bots ?? [])
        if (data.bots?.length > 0) setSelectedBot(data.bots[0])
      })
      .catch((e) => setError(e instanceof Error ? e.message : '봇 정보를 불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }, [user_id])

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="sticky top-0 z-20 h-14 border-b border-gray-800 bg-gray-950 px-6 flex items-center justify-between">
        <span
          className="font-bold text-lg cursor-pointer hover:text-indigo-300 transition-colors"
          onClick={() => navigate('/games')}
        >
          League of Agents
        </span>
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/rankings')}
            className="text-sm bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-full px-4 py-1.5 transition-colors"
          >
            리더보드
          </button>
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

      <main className="max-w-5xl mx-auto px-6 py-8">
        <button
          onClick={() => navigate('/rankings')}
          className="mb-6 flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors"
        >
          ← 리더보드로 돌아가기
        </button>

        {error && (
          <div className="mb-4 text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <span className="text-gray-500 text-sm">불러오는 중...</span>
          </div>
        ) : (
          <>
            {/* 유저 프로필 카드 */}
            {userInfo && (
              <div className="bg-gray-800 border border-gray-700 rounded-xl px-6 py-5 mb-6 flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold">{userInfo.display_name}</h2>
                  <p className="text-sm text-gray-500">{userInfo.username}</p>
                </div>
                <div className="flex items-center gap-6 text-sm">
                  <div className="text-center">
                    <div className="text-xl font-bold text-indigo-400">{userInfo.elo}</div>
                    <div className="text-xs text-gray-500">ELO</div>
                  </div>
                  <div className="text-center">
                    <div className="text-lg font-semibold text-green-400">{userInfo.wins}</div>
                    <div className="text-xs text-gray-500">승</div>
                  </div>
                  <div className="text-center">
                    <div className="text-lg font-semibold text-red-400">{userInfo.losses}</div>
                    <div className="text-xs text-gray-500">패</div>
                  </div>
                  <div className="text-center">
                    <div className="text-lg font-semibold text-gray-300">{userInfo.games_played}</div>
                    <div className="text-xs text-gray-500">총 게임</div>
                  </div>
                </div>
              </div>
            )}

            {bots.length === 0 ? (
              <div className="flex justify-center py-16">
                <p className="text-gray-500 text-sm">공개된 봇이 없습니다.</p>
              </div>
            ) : (
              <div className="flex gap-4 h-[600px]">
                {/* 봇 목록 */}
                <div className="w-56 shrink-0 flex flex-col gap-2 overflow-y-auto">
                  {bots.map((bot) => (
                    <button
                      key={bot.id}
                      onClick={() => setSelectedBot(bot)}
                      className={`text-left rounded-lg px-4 py-3 border transition-colors ${
                        selectedBot?.id === bot.id
                          ? 'bg-indigo-600/30 border-indigo-500 text-white'
                          : 'bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700'
                      }`}
                    >
                      <div className="font-medium text-sm truncate">{bot.name}</div>
                      <div className="text-xs text-gray-500 mt-0.5">v{bot.version}</div>
                      <div className="text-xs text-gray-500 mt-1">
                        <span className="text-green-400">{bot.wins}승</span>
                        {' / '}
                        <span className="text-red-400">{bot.losses}패</span>
                      </div>
                    </button>
                  ))}
                </div>

                {/* 코드 뷰어 */}
                {selectedBot && (
                  <div className="flex-1 flex flex-col bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
                    <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
                      <div>
                        <span className="font-medium">{selectedBot.name}</span>
                        <span className="ml-2 text-xs text-gray-500">v{selectedBot.version}</span>
                      </div>
                      <div className="text-xs text-gray-500">
                        승률 {(selectedBot.win_rate * 100).toFixed(1)}% ({selectedBot.games_played}게임)
                      </div>
                    </div>
                    {selectedBot.description && (
                      <div className="px-5 py-2 border-b border-gray-700 text-sm text-gray-400 bg-gray-850">
                        {selectedBot.description}
                      </div>
                    )}
                    <div className="flex-1 overflow-auto">
                      <pre className="px-5 py-4 text-xs font-mono text-gray-200 leading-relaxed whitespace-pre">
                        {selectedBot.code}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
