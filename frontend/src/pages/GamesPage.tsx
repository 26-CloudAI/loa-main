import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useNavigate } from 'react-router-dom'
import { MOCK, MOCK_GAMES } from '../dev/mock'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080'

interface GameInfo {
  game_id: string
  status: 'waiting' | 'running' | 'finished' | 'error'
  current_tick: number
  total_bots: number
  alive_bots: number
  bot_ids: string[]
}

const STATUS_LABEL: Record<GameInfo['status'], string> = {
  waiting: '대기 중',
  running: '진행 중',
  finished: '종료',
  error: '오류',
}

const STATUS_COLOR: Record<GameInfo['status'], string> = {
  waiting: 'bg-yellow-500/20 text-yellow-300',
  running: 'bg-green-500/20 text-green-300',
  finished: 'bg-gray-500/20 text-gray-400',
  error: 'bg-red-500/20 text-red-400',
}

export default function GamesPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [games, setGames] = useState<GameInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  async function fetchGames() {
    // ── mock mode ──────────────────────────────────────────────
    if (MOCK) {
      setGames(MOCK_GAMES as GameInfo[])
      setLoading(false)
      return
    }
    // ──────────────────────────────────────────────────────────
    try {
      const res = await fetch(`${API_BASE}/api/games`)
      if (!res.ok) throw new Error(`서버 오류 (${res.status})`)
      const data = await res.json()
      setGames(data)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '게임 목록을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchGames()
    const id = setInterval(fetchGames, 3000)
    return () => clearInterval(id)
  }, [])

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* 헤더 */}
      <header className="border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <span className="font-bold text-lg">League of Agents</span>
        <div className="flex items-center gap-3">
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
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            로그아웃
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* 타이틀 + 새 게임 버튼 */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold">게임 목록</h2>
          <button
            onClick={() => navigate('/games/new')}
            className="bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors"
          >
            + 새 게임 만들기
          </button>
        </div>

        {/* 상태 */}
        {error && (
          <div className="mb-4 text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <span className="text-gray-500 text-sm">불러오는 중...</span>
          </div>
        ) : games.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 gap-4 text-center">
            <p className="text-gray-500 text-sm">진행 중인 게임이 없습니다.</p>
            <button
              onClick={() => navigate('/games/new')}
              className="text-indigo-400 hover:text-indigo-300 text-sm underline underline-offset-2 transition-colors"
            >
              첫 번째 게임을 만들어보세요
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {games.map((game) => (
              <GameCard key={game.game_id} game={game} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

function GameCard({ game }: { game: GameInfo }) {
  const navigate = useNavigate()
  const shortId = game.game_id.slice(0, 8)

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4 flex items-center justify-between gap-4">
      {/* 왼쪽: 아이디 + 상태 */}
      <div className="flex items-center gap-3 min-w-0">
        <span className="font-mono text-sm text-gray-300">{shortId}…</span>
        <span
          className={`text-xs rounded-full px-2 py-0.5 font-medium ${STATUS_COLOR[game.status]}`}
        >
          {STATUS_LABEL[game.status]}
        </span>
      </div>

      {/* 가운데: 진행 정보 */}
      <div className="hidden sm:flex items-center gap-6 text-sm text-gray-400 flex-1 justify-center">
        <span>
          틱{' '}
          <span className="text-white font-medium">{game.current_tick}</span>
          {' / 200'}
        </span>
        <span>
          봇{' '}
          <span className="text-white font-medium">{game.alive_bots}</span>
          {' / '}
          {game.total_bots}
        </span>
      </div>

      {/* 오른쪽: 관전 버튼 */}
      <button
        onClick={() => navigate(`/games/${game.game_id}/watch`)}
        className="shrink-0 text-sm bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg px-3 py-1.5 transition-colors"
      >
        관전하기
      </button>
    </div>
  )
}
