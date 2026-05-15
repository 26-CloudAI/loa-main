import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080'

type Tab = 'login' | 'signup'

export default function AuthPage() {
  const [tab, setTab] = useState<Tab>('login')
  const { login, signup } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-900 flex flex-col items-center justify-center px-4">
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
      <div className="w-full max-w-sm bg-gray-800 rounded-2xl shadow-xl overflow-hidden">
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
            <SignupForm signup={signup} onSuccess={() => navigate('/games')} />
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

  async function handleSubmit(e: { preventDefault(): void }) {
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
          className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent placeholder-gray-600"
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
          className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent placeholder-gray-600"
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

/* ── 회원가입 폼 ── */
type UsernameStatus = 'idle' | 'checking' | 'available' | 'taken' | 'error'

function SignupForm({
  signup,
  onSuccess,
}: {
  signup: (email: string, username: string, password: string) => Promise<void>
  onSuccess: () => void
}) {
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [usernameStatus, setUsernameStatus] = useState<UsernameStatus>('idle')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)

    const trimmed = username.trim()
    if (trimmed.length < 3) {
      setUsernameStatus('idle')
      return
    }

    setUsernameStatus('checking')
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/users/check-username?username=${encodeURIComponent(trimmed)}`
        )
        if (!res.ok) throw new Error()
        const data = await res.json()
        setUsernameStatus(data.available ? 'available' : 'taken')
      } catch {
        setUsernameStatus('error')
      }
    }, 500)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [username])

  async function handleSubmit(e: { preventDefault(): void }) {
    e.preventDefault()
    if (usernameStatus === 'taken') return
    setError('')
    setLoading(true)
    try {
      await signup(email, username, password)
      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : '회원가입에 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }

  const usernameHint: Record<UsernameStatus, { text: string; color: string } | null> = {
    idle: null,
    checking: { text: '확인 중...', color: 'text-gray-400' },
    available: { text: '사용 가능한 이름입니다', color: 'text-green-400' },
    taken: { text: '이미 사용 중인 이름입니다', color: 'text-red-400' },
    error: { text: '중복 확인에 실패했습니다', color: 'text-yellow-400' },
  }
  const hint = usernameHint[usernameStatus]

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
          className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent placeholder-gray-600"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">사용자 이름</label>
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          minLength={3}
          maxLength={30}
          pattern="[a-zA-Z0-9_]+"
          title="3~30자, 영문/숫자/밑줄만 사용 가능"
          placeholder="my_bot_master"
          className={`bg-gray-900 border text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent placeholder-gray-600 ${
            usernameStatus === 'taken'
              ? 'border-red-500'
              : usernameStatus === 'available'
              ? 'border-green-500'
              : 'border-gray-700'
          }`}
        />
        {hint && (
          <p className={`text-xs ${hint.color}`}>{hint.text}</p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">비밀번호</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={6}
          placeholder="••••••••"
          className="bg-gray-900 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent placeholder-gray-600"
        />
      </div>

      {error && (
        <p className="text-red-400 text-xs text-center">{error}</p>
      )}

      <button
        type="submit"
        disabled={loading || usernameStatus === 'taken'}
        className="mt-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-2 transition-colors"
      >
        {loading ? '가입 중...' : '회원가입'}
      </button>
    </form>
  )
}
