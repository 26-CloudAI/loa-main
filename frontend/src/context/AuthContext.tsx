import { createContext, useContext, useState, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { MOCK, MOCK_USER, MOCK_TOKEN } from '../dev/mock'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import { auth } from '../firebaseConfig'
import {
  signInWithEmailAndPassword,
  signOut,
  onIdTokenChanged,
  createUserWithEmailAndPassword,
  updateProfile,
} from 'firebase/auth'

interface User {
  id: number
  username: string
  display_name: string
  email: string
  role: string
}

// loading      : Firebase 초기화 대기 중 또는 최초 fetchMe in-flight
// authenticated: 정상 로그인 + DB 등록 확인
// unauthenticated: 로그아웃 상태
// incomplete   : Firebase OK이지만 DB 미등록 또는 서버 오류
export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'incomplete'

interface AuthContextValue {
  user: User | null
  token: string | null
  authStatus: AuthStatus
  authError: string | null
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  signup: (email: string, username: string, password: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080'

type FetchMeResult =
  | { status: 'ok'; user: User }
  | { status: 'not_found' }
  | { status: 'unauthorized' }
  | { status: 'network_error' }

async function fetchMeWithRetry(idToken: string): Promise<FetchMeResult> {
  const delays = [500, 1000, 2000]

  for (let attempt = 0; attempt <= delays.length; attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, delays[attempt - 1]))
    }
    try {
      const res = await fetch(`${API_BASE}/api/me`, {
        headers: { Authorization: `Bearer ${idToken}` },
      })
      if (res.ok) {
        const data = await res.json()
        return {
          status: 'ok',
          user: {
            id: data.id,
            username: data.username,
            display_name: data.display_name,
            email: data.email,
            role: data.role,
          },
        }
      }
      if (res.status === 404) return { status: 'not_found' }
      if (res.status === 401 || res.status === 403) return { status: 'unauthorized' }
      // 5xx → 재시도
    } catch {
      // 네트워크 오류 → 재시도
    }
  }

  return { status: 'network_error' }
}

async function safeDeleteOrSignOut(firebaseUser: { delete: () => Promise<void> }) {
  try {
    await firebaseUser.delete()
  } catch {
    await signOut(auth).catch(() => {})
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [authStatus, setAuthStatus] = useState<AuthStatus>('loading')
  const [authError, setAuthError] = useState<string | null>(null)

  const registering = useRef(false)
  // signOut이 에러 처리 목적으로 호출될 때 onIdTokenChanged(null)이 incomplete를 유지하도록
  const errorSigningOut = useRef(false)
  // 토큰 갱신 시 LoadingScreen 플래시 방지:
  // 이미 인증된 상태에서 오는 onIdTokenChanged는 loading으로 전환하지 않음
  const userRef = useRef<User | null>(null)
  // 스탤 fetchMe 방지: 각 onIdTokenChanged 호출에 고유 ID 부여
  const fetchRequestId = useRef(0)

  useEffect(() => {
    userRef.current = user
  }, [user])

  useEffect(() => {
    if (MOCK) {
      setUser(MOCK_USER)
      setToken(MOCK_TOKEN)
      setAuthStatus('authenticated')
      return
    }

    const unsubscribe = onIdTokenChanged(auth, async (firebaseUser) => {
      if (registering.current) return  // 회원가입 진행 중에는 무시

      // 이 호출에 고유 ID 부여 — 완료 전 새 이벤트가 오면 결과 버림 (Issue 2 수정)
      const reqId = ++fetchRequestId.current

      if (firebaseUser) {
        const idToken = await firebaseUser.getIdToken()
        if (reqId !== fetchRequestId.current) return  // 이미 superseded

        setToken(idToken)

        // 유저가 없을 때만 loading 표시 — 토큰 갱신 시 LoadingScreen 플래시 방지 (Issue 1 수정)
        if (userRef.current === null) {
          setAuthStatus('loading')
        }

        const result = await fetchMeWithRetry(idToken)
        if (reqId !== fetchRequestId.current) return  // fetchMe 중 logout 등으로 superseded

        if (result.status === 'ok') {
          setUser(result.user)
          setAuthStatus('authenticated')
          setAuthError(null)
        } else if (result.status === 'not_found') {
          // Firebase에 계정이 있지만 DB 미등록 → signOut 후 incomplete 안내
          setAuthError('회원가입이 완료되지 않았습니다. 다시 회원가입해주세요.')
          errorSigningOut.current = true
          await signOut(auth).catch(() => {})
        } else if (result.status === 'unauthorized') {
          // 토큰 무효 → 조용히 signOut (unauthenticated로 처리)
          await signOut(auth).catch(() => {})
        } else {
          // network_error: 서버 일시 불가
          setUser(null)
          setAuthStatus('incomplete')
          setAuthError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.')
        }
      } else {
        // Firebase 로그아웃 이벤트
        setToken(null)
        setUser(null)
        if (errorSigningOut.current) {
          // 에러 처리 signOut이었으면 incomplete 유지
          errorSigningOut.current = false
          setAuthStatus('incomplete')
        } else {
          setAuthStatus('unauthenticated')
          setAuthError(null)
        }
      }
    })

    return () => unsubscribe()
  }, [])

  async function login(email: string, password: string) {
    if (MOCK) {
      await new Promise((r) => setTimeout(r, 400))
      setToken(MOCK_TOKEN)
      setUser(MOCK_USER)
      setAuthStatus('authenticated')
      return
    }
    await signInWithEmailAndPassword(auth, email, password)
    // onIdTokenChanged가 fetchMe → setUser/setAuthStatus 처리
  }

  async function signup(email: string, username: string, password: string) {
    registering.current = true
    try {
      const credential = await createUserWithEmailAndPassword(auth, email, password)
      const firebaseUser = credential.user

      try {
        await updateProfile(firebaseUser, { displayName: username })
      } catch {
        // updateProfile 실패: 계정 삭제 후 중단. delete 에러는 삼켜서 원래 메시지 보존 (Issue 3 수정)
        await firebaseUser.delete().catch(() => {})
        throw new Error('프로필 설정에 실패했습니다. 다시 시도해주세요.')
      }

      const idToken = await firebaseUser.getIdToken()

      let res: Response
      try {
        res = await fetch(`${API_BASE}/api/users/register`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${idToken}`,
          },
          body: JSON.stringify({ username }),
        })
      } catch {
        // 네트워크 오류: Firebase 계정 정리 후 중단
        registering.current = false
        await safeDeleteOrSignOut(firebaseUser)
        throw new Error('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.')
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        const message = data.detail ?? '회원가입에 실패했습니다.'
        // 가드 해제 후 Firebase 계정 삭제 → 같은 이메일로 재시도 가능
        registering.current = false
        await safeDeleteOrSignOut(firebaseUser)
        throw new Error(message)
      }

      // 성공: 백엔드 응답의 실제 데이터로 세팅
      const data = await res.json()
      setToken(idToken)
      setUser({
        id: data.id,
        username: data.username,
        display_name: data.display_name,
        email: data.email,
        role: data.role,
      })
      setAuthStatus('authenticated')
      setAuthError(null)
    } finally {
      registering.current = false
    }
  }

  async function logout() {
    if (MOCK) {
      setToken(null)
      setUser(null)
      setAuthStatus('unauthenticated')
      return
    }
    await signOut(auth)
    // onIdTokenChanged(null) → errorSigningOut=false이므로 unauthenticated + authError=null
  }

  return (
    <AuthContext.Provider value={{ user, token, authStatus, authError, login, logout, signup }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
