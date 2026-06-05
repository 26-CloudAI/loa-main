import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MOCK, MOCK_GAMES } from '../dev/mock'
import { BR2_API_BASE } from '../br2'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'
const STOCKS_API_BASE = import.meta.env.VITE_STOCKS_API_BASE ?? 'http://localhost:8080/stocks'

const PANEL_BG = '#161A23'
const PANEL_BORDER = 'rgba(255,255,255,.06)'
const MUTED = '#5A6270'
const FONT = '"SB Aggro",system-ui,sans-serif'

// ── Types ──────────────────────────────────────────────────────────────────────

interface RankingEntry {
  rank: number
  user_id: number
  username: string
  display_name: string
  elo: number
  wins: number
  losses: number
  games_played: number
  win_rate: number
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
  started_at?: string | null
  finished_at?: string | null
}

function fmtMMSS(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec))
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

// 서버 타임스탬프를 epoch(ms)로. SQLite datetime('now') 는 tz 표기 없는 UTC("Y-M-D H:M:S")라
// JS new Date() 가 로컬(KST)로 오해해 +9h(=540분) 오차가 남 → tz 없으면 UTC('Z')로 보정.
function parseServerTime(s?: string | null): number {
  if (!s) return 0
  const str = s.trim().replace(' ', 'T')
  const iso = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(str) ? str : str + 'Z'
  const t = new Date(iso).getTime()
  return Number.isNaN(t) ? 0 : t
}

// 진행 중 BR2/보스 게임의 경과시간(초). started_at 부터 now.
// ※ 180초는 마지막 자기장이 멈추는 시점일 뿐 교전은 이어지므로 상한 클램프 없음.
function runningElapsedSec(game: GameInfo): number {
  const started = parseServerTime(game.started_at)
  if (!started) return 0
  return (Date.now() - started) / 1000
}

// ── Helpers ────────────────────────────────────────────────────────────────────

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(`${url} (${res.status})`)
  return res.json() as Promise<T>
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  const t = parseServerTime(dateStr)
  if (!t) return ''
  const diff = Date.now() - t
  const min = Math.floor(diff / 60000)
  if (min < 1) return '방금 전'
  if (min < 60) return `${min}분 전`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}시간 전`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day}일 전`
  return new Date(dateStr).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' })
}

const MODE_LABEL: Record<string, string> = {
  'battle-royale': '배틀로얄',
  'battleroyale2': '배틀로얄',
  'boss': '보스전',
  'mock-stocks': '모의주식',
}

const MODE_PILL: Record<string, { bg: string; color: string; border: string }> = {
  'battle-royale': { bg: 'rgba(232,51,74,.15)',  color: '#F05E70', border: 'rgba(232,51,74,.3)' },
  'battleroyale2': { bg: 'rgba(232,51,74,.15)',  color: '#F05E70', border: 'rgba(232,51,74,.3)' },
  'boss':          { bg: 'rgba(155,89,245,.15)', color: '#C8A8FF', border: 'rgba(155,89,245,.3)' },
  'mock-stocks':   { bg: 'rgba(245,166,36,.15)', color: '#FFC76A', border: 'rgba(245,166,36,.3)' },
}

const STATUS_TEXT: Record<GameInfo['status'], (tick: number) => string> = {
  running:  (tick) => `진행 중 (tick ${tick})`,
  waiting:  () => '대기 중',
  loading:  () => '준비 중',
  finished: () => '종료',
  error:    () => '오류',
}

const STATUS_COLOR: Record<GameInfo['status'], string> = {
  running:  '#4ade80',
  waiting:  '#facc15',
  loading:  '#facc15',
  finished: MUTED,
  error:    '#f87171',
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatItem({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <span style={{ fontWeight: 300, color: MUTED, fontSize: 11, display: 'block', marginBottom: 4 }}>{label}</span>
      <span style={{ fontFamily: FONT, fontSize: 28, color: color ?? '#F0EBFF' }}>{value}</span>
    </div>
  )
}

function Divider() {
  return <div style={{ width: 1, height: 40, background: 'rgba(255,255,255,.1)' }} />
}

interface ModeCardProps {
  mode: string
  icon: string
  title: string
  desc: string
  borderColor: string
  glowColor: string
  btnBg: string
  btnColor: string
  pillBg: string
  pillColor: string
  pillBorder: string
  onClick: () => void
  tutorialRoute: string
}

function ModeCard({ mode, icon, title, desc, borderColor, glowColor, btnBg, btnColor, pillBg, pillColor, pillBorder, onClick, tutorialRoute }: ModeCardProps) {
  const navigate = useNavigate()
  function onEnter(e: React.MouseEvent<HTMLDivElement>) {
    const el = e.currentTarget
    el.style.transform = 'translateY(-4px)'
    el.style.borderColor = borderColor.replace('.25', '.5')
    el.style.boxShadow = `0 0 56px ${glowColor.replace('.15', '.28').replace('.12', '.22')}`
  }
  function onLeave(e: React.MouseEvent<HTMLDivElement>) {
    const el = e.currentTarget
    el.style.transform = 'translateY(0)'
    el.style.borderColor = borderColor
    el.style.boxShadow = `0 0 40px ${glowColor}`
  }

  return (
    <div
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{
        background: PANEL_BG,
        border: `1px solid ${borderColor}`,
        borderRadius: 14,
        padding: 24,
        boxShadow: `0 0 40px ${glowColor}`,
        transition: 'transform .25s ease, box-shadow .25s ease, border-color .25s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center',
          padding: '2px calc(10px - 0.1em) 3px 10px', borderRadius: 999,
          background: pillBg, color: pillColor,
          border: `1px solid ${pillBorder}`,
          fontSize: 10, fontWeight: 500, letterSpacing: '0.1em',
        }}>
          {mode}
        </span>
        <span style={{ fontSize: 28, color: pillColor, lineHeight: 1 }}>{icon}</span>
      </div>
      <h3 style={{ fontFamily: FONT, fontSize: 26, margin: '0 0 4px', color: '#F0EBFF' }}>{title}</h3>
      <p style={{ fontWeight: 300, color: MUTED, fontSize: 12, margin: '0 0 20px' }}>{desc}</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button
          onClick={onClick}
          style={{
            width: '100%', padding: '10px 0', borderRadius: 8,
            background: btnBg, color: btnColor,
            border: 'none', fontSize: 14, cursor: 'pointer', fontWeight: 500,
            transition: 'filter .15s, transform .15s',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.filter = 'brightness(1.15)'
            e.currentTarget.style.transform = 'translateY(-1px)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.filter = 'brightness(1)'
            e.currentTarget.style.transform = 'translateY(0)'
          }}
        >
          시작하기 →
        </button>
        <button
          onClick={() => navigate(tutorialRoute)}
          style={{
            width: '100%', padding: '7px 0', borderRadius: 8,
            background: 'transparent',
            border: `1px solid ${pillBorder}`,
            color: pillColor, fontSize: 12, cursor: 'pointer',
            opacity: 0.75,
            transition: 'opacity .15s',
          }}
          onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
          onMouseLeave={e => (e.currentTarget.style.opacity = '0.75')}
        >
          📖 튜토리얼 보기
        </button>
      </div>
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function MainPage() {
  const { user, token, logout } = useAuth()
  const navigate = useNavigate()
  const displayName = user?.display_name ?? user?.username ?? 'Agent'

  const [myRanking, setMyRanking] = useState<RankingEntry | null>(null)
  const [botCount, setBotCount] = useState<number | null>(null)
  const [stocksStats, setStocksStats] = useState<{ games_played: number; wins: number; losses: number } | null>(null)
  const [top5, setTop5] = useState<RankingEntry[]>([])
  const [recentGames, setRecentGames] = useState<GameInfo[]>([])
  const [statsLoading, setStatsLoading] = useState(true)
  const [gamesLoading, setGamesLoading] = useState(true)

  // ── Fetch user stats + rankings ──
  useEffect(() => {
    if (MOCK) {
      setMyRanking({ rank: 3, user_id: 1, username: 'alice', display_name: 'Alice', elo: 1420, wins: 26, losses: 16, games_played: 42, win_rate: 0.619 })
      setBotCount(3)
      setTop5([
        { rank: 1, user_id: 2, username: 'codemaster', display_name: 'codeMaster', elo: 3142, wins: 80, losses: 20, games_played: 100, win_rate: 0.8 },
        { rank: 2, user_id: 3, username: 'pyknight',   display_name: 'pyKnight',   elo: 2980, wins: 75, losses: 25, games_played: 100, win_rate: 0.75 },
        { rank: 3, user_id: 1, username: 'alice',       display_name: 'Alice',       elo: 1420, wins: 26, losses: 16, games_played: 42,  win_rate: 0.619 },
        { rank: 4, user_id: 4, username: 'stockguru',  display_name: 'stockGuru',  elo: 1380, wins: 22, losses: 18, games_played: 40,  win_rate: 0.55 },
        { rank: 5, user_id: 5, username: 'deltabot',   display_name: 'deltaBot',   elo: 1300, wins: 18, losses: 22, games_played: 40,  win_rate: 0.45 },
      ])
      setStatsLoading(false)
      return
    }

    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}

    Promise.allSettled([
      fetchJson<{ rankings: RankingEntry[] }>(`${API_BASE}/api/rankings`),
      user ? fetchJson<{ bots: unknown[] }>(`${API_BASE}/api/users/${user.id}/bots`, { headers }) : Promise.reject('no user'),
      user ? fetch(`${STOCKS_API_BASE}/api/users/me/stats`, { headers }).then(r => r.ok ? r.json() : null).catch(() => null) : Promise.resolve(null),
    ]).then(([rankRes, botRes, ssRes]) => {
      if (rankRes.status === 'fulfilled') {
        const list = rankRes.value.rankings ?? []
        setTop5(list.slice(0, 5))
        const me = list.find((r) => r.username === user?.username)
        if (me) setMyRanking(me)
      }
      if (botRes.status === 'fulfilled') {
        setBotCount(botRes.value.bots?.length ?? 0)
      }
      const ss = ssRes.status === 'fulfilled' ? ssRes.value : null
      if (ss) setStocksStats(ss)
    }).finally(() => setStatsLoading(false))
  }, [user, token])

  // ── Fetch recent games ──
  useEffect(() => {
    if (MOCK) {
      setRecentGames(MOCK_GAMES as GameInfo[])
      setGamesLoading(false)
      return
    }
    if (!token) { setGamesLoading(false); return }

    const headers = { Authorization: `Bearer ${token}` }

    Promise.allSettled([
      fetchJson<GameInfo[]>(`${API_BASE}/api/games`, { headers }),
      fetchJson<GameInfo[]>(`${BR2_API_BASE}/api/games`, { headers }),
      fetchJson<GameInfo[]>(`${STOCKS_API_BASE}/api/games`, { headers }),
      fetchJson<GameInfo[]>(`${STOCKS_API_BASE}/api/games/history`, { headers }),
    ]).then(([brRes, br2Res, stocksRes, histRes]) => {
      // 메인 /api/games(current_tick 등) 와 BR2 전용 API(started_at/finished_at 등) 가 같은
      // game_id 를 각각 반환하므로 필드 병합(나중 레코드가 덮어씀)으로 양쪽 필드를 모두 보존.
      // (first-wins dedup 이면 BR2 의 started_at 이 누락돼 진행시간이 0:00 으로 나옴)
      const byId = new Map<string, GameInfo>()
      const mergeIn = (arr: GameInfo[]) => {
        for (const g of arr) {
          const prev = byId.get(g.game_id)
          byId.set(g.game_id, prev ? { ...prev, ...g } : g)
        }
      }
      if (brRes.status === 'fulfilled' && Array.isArray(brRes.value)) mergeIn(brRes.value)
      if (br2Res.status === 'fulfilled' && Array.isArray(br2Res.value)) mergeIn(br2Res.value)
      if (stocksRes.status === 'fulfilled' && Array.isArray(stocksRes.value)) mergeIn(stocksRes.value)
      if (histRes.status === 'fulfilled' && Array.isArray(histRes.value)) mergeIn(histRes.value)
      const merged: GameInfo[] = Array.from(byId.values())
      merged.sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0
        return tb - ta
      })
      setRecentGames(merged.slice(0, 5))
    }).finally(() => setGamesLoading(false))
  }, [token])

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  // ── Stat values ──
  const totalGames  = (myRanking?.games_played ?? 0) + (stocksStats?.games_played ?? 0)
  const totalWins   = (myRanking?.wins ?? 0) + (stocksStats?.wins ?? 0)
  const totalBots   = (botCount ?? 0) + (stocksStats?.games_played ?? 0)
  const rankValue   = statsLoading ? '…' : myRanking ? `#${myRanking.rank}` : '—'
  const recordValue = statsLoading ? '…' : (myRanking || stocksStats) ? `${totalGames}전` : '—'
  const winRate     = statsLoading ? '…' : totalGames > 0 ? `${(totalWins / totalGames * 100).toFixed(0)}%` : '—'
  const botCountVal = statsLoading ? '…' : (botCount !== null || stocksStats) ? String(totalBots) : '—'

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0D0F14',
      color: '#E8EAF0',
      fontFamily: FONT,
    }}>
      {/* ── Nav ── */}
      <nav style={{
        background: 'rgba(13,15,20,.92)',
        backdropFilter: 'blur(14px)',
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
          <button onClick={() => navigate('/games/list')} style={navBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>게임 목록</button>
          <button onClick={() => navigate('/mypage')} style={{ ...navBtn, display: 'flex', alignItems: 'center', gap: 6, color: '#F0EBFF' }}>
            {displayName}
            {user && (
              <span style={{
                padding: '1px calc(6px - 0.05em) 1px 6px',
                fontSize: 10, fontWeight: 500,
                background: 'rgba(155,89,245,.15)', color: '#C8A8FF',
                border: '1px solid rgba(155,89,245,.35)',
                borderRadius: 4, letterSpacing: '0.05em',
              }}>
                {user.role}
              </span>
            )}
          </button>
          <button onClick={handleLogout} style={navBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>로그아웃</button>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section style={{
        position: 'relative',
        padding: '56px 40px 48px',
        textAlign: 'center',
        backgroundImage:
          'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
        backgroundSize: '24px 24px',
      }}>
        <div style={{
          position: 'absolute', inset: 0, pointerEvents: 'none',
          background: 'radial-gradient(ellipse 60% 70% at 50% 40%, rgba(232,51,74,.18) 0%, transparent 70%)',
        }} />

        <div style={{ position: 'relative', zIndex: 1 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '2px calc(12px - 0.1em) 3px 12px', borderRadius: 999,
            background: 'rgba(155,89,245,.12)', border: '1px solid rgba(155,89,245,.3)', color: '#C8A8FF',
            fontSize: 10, fontWeight: 500, letterSpacing: '0.1em', marginBottom: 20,
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#9B59F5', boxShadow: '0 0 8px #9B59F5', display: 'inline-block' }} />
            WELCOME BACK
          </div>

          <h1 style={{ fontFamily: FONT, fontSize: 48, margin: '0 0 10px', lineHeight: 1.2 }}>
            {displayName} <span style={{ color: MUTED }}>님,</span>
          </h1>
          <p style={{ fontWeight: 300, color: MUTED, fontSize: 15, margin: '0 0 32px' }}>오늘도 봇을 단련시킬 시간입니다.</p>

          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 32 }}>
            <StatItem label="현재 랭킹" value={rankValue}   color="#F5A624" />
            <Divider />
            <StatItem label="총 전적"   value={recordValue} />
            <Divider />
            <StatItem label="승률"      value={winRate}     color="#E8334A" />
            <Divider />
            <StatItem label="보유 봇"   value={botCountVal} color="#9B59F5" />
          </div>
        </div>
      </section>

      {/* ── Content ── */}
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 40px 60px' }}>

        {/* Mode Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20, marginBottom: 20 }}>
          <ModeCard
            mode="GAME MODE 01" icon="◆" title="배틀로얄" desc="최후의 1인이 되어라"
            borderColor="rgba(155,89,245,.25)" glowColor="rgba(155,89,245,.15)"
            btnBg="#9B59F5" btnColor="#fff"
            pillBg="rgba(155,89,245,.15)" pillColor="#C8A8FF" pillBorder="rgba(155,89,245,.3)"
            onClick={() => navigate('/games/new/battle-royale')}
            tutorialRoute="/tutorial/battle-royale"
          />
          <ModeCard
            mode="GAME MODE 02" icon="◉" title="보스전" desc="거대한 적을 쓰러뜨려라"
            borderColor="rgba(232,51,74,.25)" glowColor="rgba(232,51,74,.15)"
            btnBg="#E8334A" btnColor="#fff"
            pillBg="rgba(232,51,74,.15)" pillColor="#F05E70" pillBorder="rgba(232,51,74,.3)"
            onClick={() => navigate('/games/new/boss-battle')}
            tutorialRoute="/tutorial/boss"
          />
          <ModeCard
            mode="GAME MODE 03" icon="▲" title="모의주식" desc="알고리즘으로 시장을 지배하라"
            borderColor="rgba(245,166,36,.25)" glowColor="rgba(245,166,36,.12)"
            btnBg="#F5A624" btnColor="#000"
            pillBg="rgba(245,166,36,.15)" pillColor="#FFC76A" pillBorder="rgba(245,166,36,.3)"
            onClick={() => navigate('/games/new/mock-stocks')}
            tutorialRoute="/tutorial/stocks"
          />
        </div>

        {/* Bottom Row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20 }}>

          {/* Recent Games */}
          <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 14, padding: 20, gridColumn: 'span 2' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h4 style={{ fontWeight: 700, fontSize: 14, margin: 0 }}>최근 게임</h4>
              <button onClick={() => navigate('/games/list')} style={linkBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>전체보기 →</button>
            </div>

            {gamesLoading ? (
              <div style={{ textAlign: 'center', padding: '28px 0', color: MUTED, fontSize: 13 }}>불러오는 중...</div>
            ) : recentGames.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '28px 0', color: MUTED, fontSize: 13 }}>아직 게임 기록이 없습니다.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {recentGames.map((game) => {
                  const pill = game.mode ? MODE_PILL[game.mode] : null
                  const modeLabel = game.mode ? MODE_LABEL[game.mode] : '—'
                  // 보스전도 BR2(연속 2D) 엔진 → 관전/결과/시간표시 모두 BR2 경로 사용.
                  const isBR2 = game.mode === 'battleroyale2' || game.mode === 'boss'
                  const statusText =
                    game.status === 'running' && isBR2
                      ? `진행 중 ${fmtMMSS(runningElapsedSec(game))}`
                      : (STATUS_TEXT[game.status]?.(game.current_tick) ?? game.status)
                  const statusColor = STATUS_COLOR[game.status] ?? MUTED

                  function handleClick() {
                    if (game.status === 'finished') {
                      if (game.mode === 'mock-stocks') navigate(`/games/${game.game_id}/mock-stocks/result`)
                      else if (isBR2) navigate(`/games/${game.game_id}/battleroyale/result`)
                      else navigate(`/games/${game.game_id}/watch`)
                    } else {
                      if (game.mode === 'mock-stocks') navigate(`/games/${game.game_id}/mock-stocks/watch`)
                      else if (isBR2) navigate(`/games/${game.game_id}/battleroyale/watch`)
                      else navigate(`/games/${game.game_id}/watch`)
                    }
                  }

                  return (
                    <div
                      key={game.game_id}
                      onClick={handleClick}
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '10px 12px', borderRadius: 8,
                        background: 'rgba(255,255,255,.03)',
                        cursor: 'pointer',
                        transition: 'background .15s',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,.06)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255,255,255,.03)')}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                        {pill && (
                          <span style={{
                            display: 'inline-flex', alignItems: 'center',
                            padding: '2px calc(8px - 0.08em) 2px 8px', borderRadius: 999,
                            background: pill.bg, color: pill.color,
                            border: `1px solid ${pill.border}`,
                            fontSize: 10, fontWeight: 500, letterSpacing: '0.08em', whiteSpace: 'nowrap',
                          }}>
                            {modeLabel}
                          </span>
                        )}
                        <span style={{ fontSize: 13, color: '#F0EBFF', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {game.name ?? `게임 ${game.game_id.slice(0, 8)}`}
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0, fontSize: 12 }}>
                        <span style={{ color: statusColor }}>{statusText}</span>
                        {game.created_at && (
                          <span style={{ color: MUTED }}>{timeAgo(game.created_at)}</span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* TOP 5 */}
          <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 14, padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h4 style={{ fontWeight: 700, fontSize: 14, margin: 0 }}>TOP 5 🏆</h4>
              <button onClick={() => navigate('/rankings')} style={linkBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>전체 →</button>
            </div>

            {statsLoading ? (
              <div style={{ textAlign: 'center', padding: '28px 0', color: MUTED, fontSize: 13 }}>불러오는 중...</div>
            ) : top5.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '28px 0', color: MUTED, fontSize: 13 }}>랭킹 데이터가 없습니다.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {top5.map((entry, i) => {
                  const isMe = entry.username === user?.username
                  const rankColor = i === 0 ? '#F5A624' : i === 1 ? '#D1D5DB' : i === 2 ? '#B45309' : MUTED
                  return (
                    <div
                      key={entry.user_id}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10, fontSize: 13,
                        background: isMe ? 'rgba(155,89,245,.1)' : undefined,
                        borderRadius: isMe ? 6 : undefined,
                        padding: '3px 6px',
                        margin: isMe ? '0 -6px' : undefined,
                      }}
                    >
                      <span style={{ fontFamily: FONT, color: rankColor, width: 18, textAlign: 'center', flexShrink: 0 }}>
                        {entry.rank}
                      </span>
                      <span style={{ flex: 1, color: isMe ? '#C8A8FF' : '#F0EBFF', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {entry.display_name}
                        {isMe && <span style={{ fontSize: 10, color: MUTED, marginLeft: 4 }}>(나)</span>}
                      </span>
                      <span style={{ color: MUTED, flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>{entry.elo}</span>
                    </div>
                  )
                })}

                {/* 내 순위가 top5 밖일 때 구분선 + 내 항목 추가 */}
                {myRanking && !top5.some((r) => r.username === user?.username) && (
                  <>
                    <div style={{ borderTop: `1px solid ${PANEL_BORDER}`, margin: '4px 0' }} />
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, background: 'rgba(155,89,245,.1)', borderRadius: 6, padding: '3px 6px', margin: '0 -6px' }}>
                      <span style={{ fontFamily: FONT, color: MUTED, width: 18, textAlign: 'center', flexShrink: 0 }}>{myRanking.rank}</span>
                      <span style={{ flex: 1, color: '#C8A8FF' }}>
                        {myRanking.display_name}
                        <span style={{ fontSize: 10, color: MUTED, marginLeft: 4 }}>(나)</span>
                      </span>
                      <span style={{ color: MUTED, flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>{myRanking.elo}</span>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

const navBtn: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer',
  color: MUTED, fontSize: 13, padding: 0, transition: 'color .15s',
}

const linkBtn: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer',
  color: MUTED, fontSize: 12, transition: 'color .15s',
}
