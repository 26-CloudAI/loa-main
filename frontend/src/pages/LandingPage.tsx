import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

type Tab = 'login' | 'signup'

export default function LandingPage() {
  const [tab, setTab] = useState<Tab>('login')
  const { login } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col items-center justify-center px-4">
      {/* 로고 / 타이틀 */}
      <div className="mb-8 text-center">
        <h1 className="text-4xl font-bold text-white tracking-tight">
          League of Agents
        </h1>
        <p className="mt-2 text-gray-400 text-sm">
          Python 봇을 제출하고 AI 배틀 아레나에서 겨뤄보세요
        </p>
      </div>

      {/* 카드 */}
      <div className="w-full max-w-sm bg-gray-900 rounded-2xl shadow-xl overflow-hidden">
        {/* 탭 */}
        <div className="flex border-b border-gray-700">
          <button
            onClick={() => setTab('login')}
            className={`flex-1 py-3 text-sm font-medium transition-colors ${
              tab === 'login'
                ? 'text-white border-b-2 border-indigo-500'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            로그인
          </button>
          <button
            onClick={() => setTab('signup')}
            className={`flex-1 py-3 text-sm font-medium transition-colors ${
              tab === 'signup'
                ? 'text-white border-b-2 border-indigo-500'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            회원가입
          </button>
        </div>

        <div className="p-6">
          {tab === 'login' ? (
            <LoginForm onSuccess={() => navigate('/games')} login={login} />
          ) : (
            <SignupForm />
          )}
        </div>
      </div>
    </div>
  )
}

/* ── 로그인 폼 ── */
function LoginForm({
  onSuccess,
  login,
}: {
  onSuccess: () => void
  login: (email: string, password: string) => Promise<void>
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : '로그인에 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">이메일</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          placeholder="alice@arena.dev"
          className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-600"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">비밀번호</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          placeholder="••••••••"
          className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-600"
        />
      </div>

      {error && (
        <p className="text-red-400 text-xs text-center">{error}</p>
      )}

      <button
        type="submit"
        disabled={loading}
        className="mt-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-2 transition-colors"
      >
        {loading ? '로그인 중...' : '로그인'}
      </button>
    </form>
  )
}

/* ── 회원가입 폼 (백엔드 미구현 — UI 플레이스홀더) ── */
function SignupForm() {
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    alert('회원가입 기능은 준비 중입니다.')
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">이메일</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          placeholder="you@arena.dev"
          className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-600"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">사용자 이름</label>
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          placeholder="my_bot_master"
          className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-600"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">비밀번호</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          placeholder="••••••••"
          className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-600"
        />
      </div>

      <p className="text-yellow-500 text-xs text-center bg-yellow-500/10 rounded-lg py-2 px-3">
        회원가입은 현재 준비 중입니다.
      </p>

      <button
        type="submit"
        disabled
        className="mt-1 bg-indigo-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-2"
      >
        회원가입
      </button>
    </form>
  )
}
