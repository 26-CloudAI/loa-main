import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useNavigate } from 'react-router-dom'
import { MOCK, MOCK_GAMES } from '../dev/mock'
import { BR2_API_BASE } from '../br2'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'
const STOCKS_API_BASE = import.meta.env.VITE_STOCKS_API_BASE ?? 'http://localhost:8080/stocks'

interface RankingEntry {
  rank: number
  bot_id: string
  bot_name?: string
  is_ai_filler?: boolean
  final_total_value: number
  profit_rate: number
  final_credit_score?: number
}

interface GameInfo {
  game_id: string
  status: 'waiting' | 'loading' | 'running' | 'finished' | 'error'
  current_tick: number
  total_bots: number
  alive_bots: number
  bot_ids: string[]
  name?: string | null
  mode?: string
  created_at?: string | null
  finished_at?: string | null
  rankings?: RankingEntry[]
}

const MODE_BADGE: Record<string, { label: string; style: { background: string; color: string; border: string } }> = {
  'battle-royale': { label: '배틀로얄', style: { background: 'rgba(155,89,245,.15)', color: '#C8A8FF', border: '1px solid rgba(155,89,245,.4)' } },
  'battleroyale2': { label: '배틀로얄', style: { background: 'rgba(155,89,245,.15)', color: '#C8A8FF', border: '1px solid rgba(155,89,245,.4)' } },
  'boss':          { label: '보스전',   style: { background: 'rgba(232,51,74,.15)',  color: '#F05E70', border: '1px solid rgba(232,51,74,.4)'  } },
  'mock-stocks':   { label: '모의주식', style: { background: 'rgba(245,166,36,.15)', color: '#FFC76A', border: '1px solid rgba(245,166,36,.4)' } },
}

const STATUS_LABEL: Record<GameInfo['status'], string> = {
  waiting: '대기 중',
  loading: '준비 중',
  running: '진행 중',
  finished: '종료',
  error: '오류',
}

const STATUS_COLOR: Record<GameInfo['status'], string> = {
  waiting: 'bg-yellow-500/20 text-yellow-300',
  loading: 'bg-yellow-500/20 text-yellow-300',
  running: 'bg-green-500/20 text-green-300',
  finished: 'bg-gray-500/20 text-gray-400',
  error: 'bg-red-500/20 text-red-400',
}

const MUTED = '#5A6270'
const navBtn: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer',
  color: MUTED, fontSize: 13, padding: 0, transition: 'color .15s',
}

async function fetchJson(url: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(`${url} (${res.status})`)
  return res.json()
}

export default function GamesPage() {
  const { user, token, logout } = useAuth()
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
    if (!token) {
      setLoading(false)
      return
    }
    try {
      const [brResult, br2Result, stocksActive, stocksHistory] = await Promise.allSettled([
        fetchJson(`${API_BASE}/api/games`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetchJson(`${BR2_API_BASE}/api/games`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetchJson(`${STOCKS_API_BASE}/api/games`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetchJson(`${STOCKS_API_BASE}/api/games/history`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ])

      // 메인 /api/games 가 이미 battleroyale2 모드를 포함하고, BR2 전용 API 가 같은 게임을
      // 다시 반환하므로 game_id 기준 전역 dedup (먼저 들어온 레코드 우선).
      const merged: GameInfo[] = []
      const seen = new Set<string>()
      const pushUnique = (arr: GameInfo[]) => {
        for (const g of arr) {
          if (seen.has(g.game_id)) continue
          seen.add(g.game_id)
          merged.push(g)
        }
      }
      if (brResult.status === 'fulfilled' && Array.isArray(brResult.value)) {
        pushUnique(brResult.value as GameInfo[])
      }
      if (br2Result.status === 'fulfilled' && Array.isArray(br2Result.value)) {
        pushUnique(br2Result.value as GameInfo[])
      }
      if (stocksActive.status === 'fulfilled' && Array.isArray(stocksActive.value)) {
        pushUnique(stocksActive.value as GameInfo[])
      }
      if (stocksHistory.status === 'fulfilled' && Array.isArray(stocksHistory.value)) {
        // history는 finished 상태이므로 활성 목록과 game_id 중복 시 활성 우선
        pushUnique(stocksHistory.value as GameInfo[])
      }

      // created_at 기준 내림차순 정렬 (최신 게임이 위로)
      merged.sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0
        return tb - ta
      })

      setGames(merged)

      // BattleRoyale 호출만 실패해도 핵심 흐름이 끊기므로 에러로 처리
      if (brResult.status === 'rejected') {
        const reason = brResult.reason
        throw new Error(reason instanceof Error ? reason.message : String(reason))
      }
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
  }, [token])

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div style={{
      position: 'relative',
      minHeight: '100vh',
      background: '#0D0F14',
      color: '#E8EAF0',
      backgroundImage: 'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
      backgroundSize: '24px 24px',
    }}>
      <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 60% 70% at 50% 40%, rgba(99,102,241,.15) 0%, transparent 70%)',
      }} />
      {/* 헤더 */}
      <nav style={{
        background: 'rgba(13,15,20,.92)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        height: 56,
        padding: '0 28px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        position: 'sticky',
        top: 0,
        zIndex: 20,
      }}>
        <button
          onClick={() => navigate('/games')}
          style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          <span style={{ color: '#E8334A', fontSize: 16, lineHeight: 1 }}>◆</span>
          <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.1em', color: '#F0EBFF' }}>LEAGUE OF AGENTS</span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
          <button onClick={() => navigate('/rankings')} style={navBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>리더보드</button>
          {user && (
            <button
              onClick={() => navigate('/mypage')}
              style={{ ...navBtn, display: 'flex', alignItems: 'center', gap: 6, color: '#F0EBFF' }}
            >
              {user.display_name ?? user.username}
              <span style={{
                padding: '1px calc(6px - 0.05em) 1px 6px',
                fontSize: 10, fontWeight: 500,
                background: 'rgba(155,89,245,.15)', color: '#C8A8FF',
                border: '1px solid rgba(155,89,245,.35)',
                borderRadius: 4, letterSpacing: '0.05em',
              }}>
                {user.role}
              </span>
            </button>
          )}
          <button onClick={handleLogout} style={navBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>로그아웃</button>
        </div>
      </nav>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* 타이틀 + 새 게임 버튼 */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-medium">게임 목록</h2>
          <button
            onClick={() => navigate('/games/new')}
            className="bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg px-4 transition-colors" style={{ paddingTop: 7, paddingBottom: 10 }}
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
  const modeBadge = game.mode ? MODE_BADGE[game.mode] : null
  const isStocks = game.mode === 'mock-stocks'
  const isBR2 = game.mode === 'battleroyale2'
  const isFinished = game.status === 'finished'

  function handleWatch() {
    if (isStocks) {
      navigate(`/games/${game.game_id}/mock-stocks/watch`)
    } else if (isBR2) {
      navigate(`/games/${game.game_id}/battleroyale/watch`)
    } else {
      navigate(`/games/${game.game_id}/watch`)
    }
  }

  function handleResult() {
    if (isStocks) {
      navigate(`/games/${game.game_id}/mock-stocks/result`)
    } else if (isBR2) {
      navigate(`/games/${game.game_id}/battleroyale/result`)
    } else {
      navigate(`/games/${game.game_id}/watch`)
    }
  }

  function handleReplay() {
    if (isStocks) {
      navigate(`/games/${game.game_id}/mock-stocks/replay`)
    } else if (isBR2) {
      navigate(`/games/${game.game_id}/battleroyale/replay`)
    } else {
      navigate(`/games/${game.game_id}/replay`)
    }
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl px-5 py-4 flex items-center justify-between gap-4">
      {/* 게임 이름 */}
      <div className="w-36 shrink-0 min-w-0">
        <span className="text-sm font-medium text-white truncate block">
          {game.name ?? `게임 ${shortId}`}
        </span>
      </div>

      {/* 뱃지 */}
      <div className="flex items-center shrink-0">
        <div className="w-20 flex items-center justify-center">
          {modeBadge && (
            <span className="text-xs leading-none rounded-full px-2 font-medium" style={{ ...modeBadge.style, paddingTop: '3px', paddingBottom: '3px' }}>
              {modeBadge.label}
            </span>
          )}
        </div>
        <div className="w-16 flex items-center justify-center">
          <span className={`text-xs leading-none rounded-full px-2 py-1 font-medium ${STATUS_COLOR[game.status]}`}>
            {STATUS_LABEL[game.status]}
          </span>
        </div>
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
          <span className="text-white font-medium">{game.total_bots}</span>
        </span>
      </div>

      {/* 오른쪽: 관전 / 결과 + 리플레이 버튼 */}
      <div className="shrink-0 flex items-center gap-2">
        {isFinished ? (
          <>
            <button
              onClick={handleResult}
              className="text-sm rounded-lg px-3 transition-colors bg-gray-600 hover:bg-gray-500 text-white"
              style={{ paddingTop: '4px', paddingBottom: '6px' }}
            >
              결과 보기
            </button>
            <button
              onClick={handleReplay}
              className="flex items-center gap-0.5 text-sm rounded-lg transition-colors bg-indigo-700 hover:bg-indigo-600 text-white"
              style={{ paddingTop: '4px', paddingBottom: '6px', paddingLeft: '8px', paddingRight: '12px' }}
            >
              <span>🎬</span><span>리플레이</span>
            </button>
          </>
        ) : (
          <button
            onClick={handleWatch}
            className="text-sm rounded-lg px-3 transition-colors bg-gray-600 hover:bg-gray-500 text-white"
            style={{ paddingTop: '4px', paddingBottom: '6px' }}
          >
            관전하기
          </button>
        )}
      </div>
    </div>
  )
}
