import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useNavigate } from 'react-router-dom'
import { MOCK, MOCK_GAMES } from '../dev/mock'

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
  finished_at?: string | null
  rankings?: RankingEntry[]
}

const MODE_BADGE: Record<string, { label: string; className: string }> = {
  'battle-royale': { label: '배틀로얄', className: 'bg-indigo-600/30 text-indigo-300 border border-indigo-600/50' },
  'boss':          { label: '보스전',   className: 'bg-red-700/30 text-red-300 border border-red-700/50' },
  'mock-stocks':   { label: '모의주식', className: 'bg-emerald-600/30 text-emerald-300 border border-emerald-600/50' },
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
      const [brResult, stocksActive, stocksHistory] = await Promise.allSettled([
        fetchJson(`${API_BASE}/api/games`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetchJson(`${STOCKS_API_BASE}/api/games`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetchJson(`${STOCKS_API_BASE}/api/games/history`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ])

      const merged: GameInfo[] = []
      if (brResult.status === 'fulfilled' && Array.isArray(brResult.value)) {
        merged.push(...(brResult.value as GameInfo[]))
      }
      if (stocksActive.status === 'fulfilled' && Array.isArray(stocksActive.value)) {
        merged.push(...(stocksActive.value as GameInfo[]))
      }
      if (stocksHistory.status === 'fulfilled' && Array.isArray(stocksHistory.value)) {
        // history는 finished 상태이므로 활성 목록과 game_id 중복 시 활성 우선
        const activeIds = new Set(merged.map((g) => g.game_id))
        for (const g of stocksHistory.value as GameInfo[]) {
          if (!activeIds.has(g.game_id)) merged.push(g)
        }
      }

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
    <div className="min-h-screen bg-gray-900 text-white">
      {/* 헤더 */}
      <header className="sticky top-0 z-20 h-14 border-b border-gray-800 bg-gray-950 px-6 flex items-center justify-between">
        <span className="font-bold text-lg">League of Agents</span>
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/rankings')}
            className="text-sm text-gray-400 hover:text-white transition-colors"
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
  const modeBadge = game.mode ? MODE_BADGE[game.mode] : null
  const isStocks = game.mode === 'mock-stocks'
  const isFinished = game.status === 'finished'

  function handleAction() {
    if (isStocks) {
      navigate(isFinished
        ? `/games/${game.game_id}/mock-stocks/result`
        : `/games/${game.game_id}/mock-stocks/watch`)
      return
    }
    navigate(`/games/${game.game_id}/watch`)
  }

  const actionLabel = isStocks
    ? (isFinished ? '결과 보기' : '관전하기')
    : '관전하기'
  const actionDisabled = false

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl px-5 py-4 flex items-center justify-between gap-4">
      {/* 왼쪽: 게임 이름 + 뱃지들 */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm font-medium text-white truncate">
          {game.name ?? `게임 ${shortId}`}
        </span>
        {modeBadge && (
          <span className={`shrink-0 text-xs rounded-full px-2 py-0.5 font-medium ${modeBadge.className}`}>
            {modeBadge.label}
          </span>
        )}
        <span
          className={`shrink-0 text-xs rounded-full px-2 py-0.5 font-medium ${STATUS_COLOR[game.status]}`}
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
          <span className="text-white font-medium">{isStocks ? game.total_bots : game.alive_bots}</span>
          {!isStocks && (
            <>
              {' / '}
              {game.total_bots}
            </>
          )}
        </span>
      </div>

      {/* 오른쪽: 관전 / 결과 보기 버튼 */}
      <button
        onClick={handleAction}
        disabled={actionDisabled}
        className={`shrink-0 text-sm rounded-lg px-3 py-1.5 transition-colors ${
          actionDisabled
            ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
            : 'bg-gray-800 hover:bg-gray-700 text-gray-200'
        }`}
      >
        {actionLabel}
      </button>
    </div>
  )
}
