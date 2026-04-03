import { useAuth } from '../context/AuthContext'
import { useNavigate } from 'react-router-dom'

export default function GamesPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

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

      {/* 본문 플레이스홀더 */}
      <main className="flex items-center justify-center h-[calc(100vh-57px)]">
        <p className="text-gray-500 text-sm">게임 목록 화면 — 준비 중</p>
      </main>
    </div>
  )
}
