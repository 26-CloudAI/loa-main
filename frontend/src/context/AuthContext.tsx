import { createContext, useContext, useState, useEffect } from 'react'
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

  useEffect(() => {
    if (MOCK) {
      setUser(MOCK_USER)
      setToken(MOCK_TOKEN)
      return
    }

    // Firebase 인증 상태 및 토큰 갱신 감지 (로그인/로그아웃/1시간마다 자동 갱신)
    const unsubscribe = onIdTokenChanged(auth, async (firebaseUser) => {
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
      await firebaseUser.delete()
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail ?? '회원가입에 실패했습니다.')
    }
    // onIdTokenChanged가 자동으로 token/user 상태를 업데이트함
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
