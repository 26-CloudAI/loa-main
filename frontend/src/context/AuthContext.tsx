import { createContext, useContext, useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import { MOCK, MOCK_USER, MOCK_TOKEN } from '../dev/mock'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080'

interface User {
  id: number
  username: string
  display_name: string
  email: string
  role: string
}

interface AuthContextValue {
  user: User | null
  token: string | null
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem('loa_token')
  )

  // 새로고침 시 저장된 토큰으로 user 복원
  useEffect(() => {
    if (!token || user) return
    if (MOCK) {
      setUser(MOCK_USER)
      return
    }
    fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.user) setUser(data.user)
        else {
          // 토큰이 만료됐으면 초기화
          localStorage.removeItem('loa_token')
          setToken(null)
        }
      })
      .catch(() => {})
  }, [token])

  async function login(email: string, password: string) {
    // ── mock mode ──────────────────────────────────────────────
    if (MOCK) {
      await new Promise((r) => setTimeout(r, 400))
      localStorage.setItem('loa_token', MOCK_TOKEN)
      setToken(MOCK_TOKEN)
      setUser(MOCK_USER)
      return
    }
    // ──────────────────────────────────────────────────────────
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail ?? '로그인에 실패했습니다.')
    }
    const data = await res.json()
    localStorage.setItem('loa_token', data.access_token)
    setToken(data.access_token)
    setUser(data.user)
  }

  async function logout() {
    if (token) {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {})
    }
    localStorage.removeItem('loa_token')
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, token, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
