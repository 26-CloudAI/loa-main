import { createContext, useContext, useState, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { MOCK, MOCK_USER, MOCK_TOKEN } from '../dev/mock'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import { auth } from '../firebaseConfig'
import { signInWithEmailAndPassword, signOut, onIdTokenChanged, createUserWithEmailAndPassword, updateProfile } from 'firebase/auth'

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
  signup: (email: string, username: string, password: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const registering = useRef(false)

  useEffect(() => {
    if (MOCK) {
      setUser(MOCK_USER)
      setToken(MOCK_TOKEN)
      return
    }

    // Firebase 인증 상태 및 토큰 갱신 감지 (로그인/로그아웃/1시간마다 자동 갱신)
    const unsubscribe = onIdTokenChanged(auth, async (firebaseUser) => {
      if (registering.current) return  // 회원가입 진행 중에는 무시
      if (firebaseUser) {
        const idToken = await firebaseUser.getIdToken()
        setToken(idToken)
        setUser({
          id: 0,
          username: firebaseUser.email ?? '',
          display_name: firebaseUser.displayName ?? firebaseUser.email ?? '',
          email: firebaseUser.email ?? '',
          role: 'user',
        })
      } else {
        setToken(null)
        setUser(null)
      }
    })

    return () => unsubscribe()
  }, [])

  async function login(email: string, password: string) {
    if (MOCK) {
      await new Promise((r) => setTimeout(r, 400))
      setToken(MOCK_TOKEN)
      setUser(MOCK_USER)
      return
    }
    await signInWithEmailAndPassword(auth, email, password)
    // onIdTokenChanged가 자동으로 token/user 상태를 업데이트함
  }

  async function signup(email: string, username: string, password: string) {
    registering.current = true
    try {
      const credential = await createUserWithEmailAndPassword(auth, email, password)
      const firebaseUser = credential.user
      await updateProfile(firebaseUser, { displayName: username })

      const idToken = await firebaseUser.getIdToken()
      const apiBase = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080'
      const res = await fetch(`${apiBase}/api/users/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${idToken}`,
        },
        body: JSON.stringify({ username }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        const message = data.detail ?? '회원가입에 실패했습니다.'
        registering.current = false  // 가드 해제 후 signOut → onIdTokenChanged가 null 처리
        await signOut(auth)          // Firebase 계정 유지, 로그아웃만
        throw new Error(message)
      }

      // 성공: 직접 token/user 세팅
      setToken(idToken)
      setUser({
        id: 0,
        username: username,
        display_name: username,
        email: firebaseUser.email ?? '',
        role: 'user',
      })
    } finally {
      registering.current = false
    }
  }

  async function logout() {
    if (MOCK) {
      setToken(null)
      setUser(null)
      return
    }
    await signOut(auth)
    // onIdTokenChanged가 자동으로 null 상태로 업데이트함
  }

  return (
    <AuthContext.Provider value={{ user, token, login, logout, signup }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
