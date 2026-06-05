import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import PythonEditor from '../components/PythonEditor'

const API_BASE    = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'
const STOCKS_API  = import.meta.env.VITE_STOCKS_API_BASE ?? 'http://localhost:8080/stocks'

const DISPLAY_FONT = '"SB Aggro",system-ui,sans-serif'
const PANEL_BG     = '#161A23'
const PANEL_BORDER = 'rgba(255,255,255,.06)'
const MUTED        = '#5A6270'

const TIER_LIST = [
  { min: 2000, label: 'Grandmaster', color: '#E8334A' },
  { min: 1800, label: 'Master',      color: '#9B59F5' },
  { min: 1600, label: 'Diamond',     color: '#00bcd4' },
  { min: 1450, label: 'Platinum',    color: '#4fc3f7' },
  { min: 1300, label: 'Gold',        color: '#F5A624' },
  { min: 1150, label: 'Silver',      color: '#c0c0c0' },
  { min: 1000, label: 'Bronze',      color: '#cd7f32' },
  { min: 0,    label: 'Iron',        color: '#B8AEDD' },
]

const MODE_COLOR: Record<string, { bg: string; border: string; text: string }> = {
  '배틀로얄': { bg: 'rgba(155,89,245,.15)', border: 'rgba(155,89,245,.4)', text: '#C8A8FF' },
  '보스전':   { bg: 'rgba(232,51,74,.15)',  border: 'rgba(232,51,74,.4)',  text: '#F05E70' },
  '모의주식': { bg: 'rgba(245,166,36,.15)', border: 'rgba(245,166,36,.4)', text: '#F5A624' },
}

function getTier(elo: number) {
  return TIER_LIST.find(t => elo >= t.min) ?? TIER_LIST[TIER_LIST.length - 1]
}

function formatDate(iso: string) {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}

interface UserInfo {
  user_id: number; username: string; display_name: string
  elo: number; wins: number; losses: number; games_played: number
}
interface BotInfo {
  id: number; name: string
  game_mode: string | null; game_name: string | null
  code: string | null
  is_public: boolean; wins: number; losses: number
  games_played: number; created_at: string
}
interface RankEntry { rank: number; username: string }

// ── 공통 스타일 ─────────────────────────────────
const labelStyle: React.CSSProperties = { fontSize: 11, color: MUTED, display: 'block', marginBottom: 5, letterSpacing: '0.05em' }
const readonlyStyle: React.CSSProperties = { padding: '9px 12px', borderRadius: 7, fontSize: 12, color: MUTED, background: 'rgba(255,255,255,.03)', border: '1px solid rgba(255,255,255,.05)' }
const inputStyle: React.CSSProperties = { padding: '9px 12px', borderRadius: 7, fontSize: 13, color: '#F0EBFF', background: 'rgba(255,255,255,.05)', border: '1px solid rgba(255,255,255,.12)', outline: 'none' }
const btnPrimary: React.CSSProperties = { padding: '9px 20px', borderRadius: 7, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, background: '#E8334A', color: '#fff', transition: 'opacity .2s' }
const btnGhost: React.CSSProperties = { padding: '9px 20px', borderRadius: 7, border: '1px solid rgba(255,255,255,.1)', cursor: 'pointer', fontSize: 12, background: 'rgba(255,255,255,.04)', color: '#F0EBFF' }
const btnDanger: React.CSSProperties = { padding: '9px 20px', borderRadius: 7, border: '1px solid rgba(232,51,74,.3)', cursor: 'pointer', fontSize: 12, background: 'rgba(232,51,74,.08)', color: '#F05E70' }

function SettingGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', color: MUTED, margin: '0 0 14px', textTransform: 'uppercase' as const }}>{label}</p>
      {children}
    </div>
  )
}

function ToggleRow({ label, desc, value, onChange, disabled, badge }: {
  label: string; desc: string; value: boolean
  onChange: () => void; disabled?: boolean; badge?: string
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid rgba(255,255,255,.04)', opacity: disabled ? 0.45 : 1 }}>
      <div style={{ flex: 1, minWidth: 0, marginRight: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 13, color: '#F0EBFF' }}>{label}</span>
          {badge && <span style={{ fontSize: 9, fontWeight: 700, color: '#726890', background: 'rgba(255,255,255,.06)', borderRadius: 4, padding: '1px 5px', letterSpacing: '0.06em' }}>{badge}</span>}
        </div>
        <p style={{ margin: '2px 0 0', fontSize: 11, color: MUTED }}>{desc}</p>
      </div>
      <button disabled={disabled} onClick={onChange} style={{ position: 'relative', width: 36, height: 20, borderRadius: 999, border: 'none', cursor: disabled ? 'default' : 'pointer', flexShrink: 0, background: value ? 'rgba(232,51,74,.4)' : 'rgba(255,255,255,.1)', transition: 'background .2s', padding: 0 }}>
        <span style={{ position: 'absolute', top: 3, width: 14, height: 14, borderRadius: '50%', background: value ? '#E8334A' : '#554C78', left: value ? 19 : 3, transition: 'left .2s, background .2s', boxShadow: value ? '0 0 6px rgba(232,51,74,.5)' : 'none' }} />
      </button>
    </div>
  )
}

export default function MyPage() {
  const { user, token, logout } = useAuth()
  const navigate = useNavigate()
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null)
  const [bots, setBots]         = useState<BotInfo[]>([])
  const [myRank, setMyRank]     = useState<number | null>(null)
  const [loading, setLoading]   = useState(true)
  const [stocksStats, setStocksStats] = useState<{ games_played: number; wins: number; losses: number } | null>(null)
  const [toggling, setToggling]             = useState<number | null>(null)
  const [barProgress, setBarProgress]       = useState(0)
  const [selectedMode, setSelectedMode]     = useState<string | null>(null)
  const [displayNameInput, setDisplayNameInput] = useState('')
  const [savingName, setSavingName]         = useState(false)
  const [saveMsg, setSaveMsg]               = useState('')
  const [expandedBotId, setExpandedBotId]   = useState<number | null>(null)
  const [editingCode, setEditingCode]       = useState<Record<number, string>>({})
  const [savingBot, setSavingBot]           = useState<number | null>(null)
  const [botSaveMsg, setBotSaveMsg]         = useState<Record<number, string>>({})

  // 게임 설정 (localStorage 저장)
  const [settings, setSettings] = useState(() => {
    try { return JSON.parse(localStorage.getItem('loa_settings') || '{}') } catch { return {} }
  })
  function toggleSetting(key: string) {
    setSettings((prev: Record<string, boolean>) => {
      const next = { ...prev, [key]: !prev[key] }
      localStorage.setItem('loa_settings', JSON.stringify(next))
      return next
    })
  }

  useEffect(() => {
    if (!user?.id || !token) return
    Promise.all([
      fetch(`${API_BASE}/api/users/${user.id}/bots`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()),
      fetch(`${API_BASE}/api/rankings`).then(r => r.json()),
      fetch(`${STOCKS_API}/api/users/me/stats`, { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([ud, rd, ss]) => {
      setUserInfo(ud.user)
      setBots(ud.bots ?? [])
      if (ss) setStocksStats(ss)
      const found = (rd.rankings as RankEntry[])?.find(r => r.username === user.username)
      setMyRank(found?.rank ?? null)

      const elo = ud.user?.elo ?? 0
      const t = TIER_LIST.find((x: typeof TIER_LIST[0]) => elo >= x.min) ?? TIER_LIST[TIER_LIST.length - 1]
      const next = TIER_LIST[TIER_LIST.indexOf(t) - 1]
      const p = next ? Math.min(100, Math.round(((elo - t.min) / (next.min - t.min)) * 100)) : 100
      setTimeout(() => setBarProgress(p), 80)
    }).finally(() => setLoading(false))
  }, [user?.id, token])

  async function togglePublic(botId: number, cur: boolean) {
    if (!token) return
    setToggling(botId)
    try {
      await fetch(`${API_BASE}/api/bots/${botId}/visibility`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ is_public: !cur }),
      })
      setBots(prev => prev.map(b => b.id === botId ? { ...b, is_public: !cur } : b))
    } finally { setToggling(null) }
  }

  async function saveBot(botId: number) {
    const code = editingCode[botId]
    if (!code?.trim() || !token) return
    setSavingBot(botId)
    try {
      const res = await fetch(`${API_BASE}/api/bots/${botId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ code }),
      })
      if (!res.ok) throw new Error()
      setBotSaveMsg(prev => ({ ...prev, [botId]: '저장되었습니다.' }))
      setTimeout(() => setBotSaveMsg(prev => { const n = { ...prev }; delete n[botId]; return n }), 2000)
      setExpandedBotId(null)
    } catch {
      setBotSaveMsg(prev => ({ ...prev, [botId]: '저장 실패' }))
    } finally { setSavingBot(null) }
  }


  const tier       = userInfo ? getTier(userInfo.elo) : null
  const totalWins  = (userInfo?.wins ?? 0) + (stocksStats?.wins ?? 0)
  const totalLosses = (userInfo?.losses ?? 0) + (stocksStats?.losses ?? 0)
  const totalGames = (userInfo?.games_played ?? 0) + (stocksStats?.games_played ?? 0)
  const winRate    = totalGames > 0 ? ((totalWins / totalGames) * 100).toFixed(1) : '0.0'

  return (
    <div style={{
      minHeight: '100vh', background: '#241848', color: '#F0EBFF',
    }}>

      {/* ── Nav ── */}
      <nav style={{
        background: 'rgba(13,15,20,.92)', backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        height: 56, padding: '0 28px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        position: 'sticky', top: 0, zIndex: 20,
      }}>
        <button onClick={() => navigate('/games')}
          style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
          <span style={{ color: '#E8334A', fontSize: 16, lineHeight: 1 }}>◆</span>
          <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.1em', color: '#F0EBFF' }}>LEAGUE OF AGENTS</span>
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
          <button onClick={() => navigate('/rankings')} style={{ color: MUTED, fontSize: 13, background: 'none', border: 'none', cursor: 'pointer', padding: 0, transition: 'color .15s' }} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>리더보드</button>
          <button onClick={() => navigate('/games/list')} style={{ color: MUTED, fontSize: 13, background: 'none', border: 'none', cursor: 'pointer', padding: 0, transition: 'color .15s' }} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>게임 목록</button>
          <button onClick={async () => { await logout(); navigate('/login') }}
            style={{ color: MUTED, fontSize: 13, background: 'none', border: 'none', cursor: 'pointer', padding: 0, transition: 'color .15s' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>
            로그아웃
          </button>
        </div>
      </nav>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120, color: MUTED, fontSize: 13 }}>불러오는 중...</div>
      ) : (
        <>
          {/* ── Hero ── */}
          <section style={{
            position: 'relative', padding: '56px 40px 48px', textAlign: 'center',
            backgroundImage: 'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}>
            <div style={{
              position: 'absolute', inset: 0, pointerEvents: 'none',
              background: 'radial-gradient(ellipse 60% 70% at 50% 40%, rgba(232,51,74,.18) 0%, transparent 70%)',
            }} />
            <div style={{ position: 'relative', zIndex: 1 }}>


              {/* 아바타 */}
              {tier && (
                <div style={{
                  width: 72, height: 72, borderRadius: '50%', margin: '0 auto 20px',
                  background: 'rgba(255,255,255,.05)',
                  border: `2px solid ${tier.color}55`,
                  boxShadow: `0 0 20px ${tier.color}33`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none"
                    stroke={tier.color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="8" r="4" />
                    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
                  </svg>
                </div>
              )}

              {/* 닉네임 */}
              <h1 style={{ fontFamily: DISPLAY_FONT, fontSize: 48, margin: '0 0 16px', lineHeight: 1.2 }}>
                {userInfo?.display_name ?? ''}
              </h1>

              {/* 티어 한 줄 요약 */}
              {tier && userInfo && (() => {
                const nextTier  = TIER_LIST[TIER_LIST.indexOf(tier) - 1]
                const nextMin   = nextTier?.min ?? tier.min
                const eloToNext = nextTier ? nextMin - userInfo.elo : 0
                return (
                  <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 10, marginBottom: 32 }}>
                    {/* 티어명 */}
                    <span style={{
                      fontFamily: DISPLAY_FONT, fontSize: 16, fontWeight: 700,
                      color: tier.color, textShadow: `0 0 12px ${tier.color}88`,
                      letterSpacing: '0.04em',
                    }}>
                      {tier.label}
                    </span>

                    {/* 바 + 다음 티어 텍스트 오른쪽 */}
                    {nextTier && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ width: 280, height: 4, background: 'rgba(255,255,255,.08)', borderRadius: 999, overflow: 'hidden' }}>
                          <div style={{
                            width: `${barProgress}%`, height: '100%',
                            background: `linear-gradient(90deg, ${tier.color}66, ${tier.color})`,
                            borderRadius: 999,
                            boxShadow: `0 0 6px ${tier.color}55`,
                            transition: 'width 1s cubic-bezier(.25,.46,.45,.94)',
                          }} />
                        </div>
                        <span style={{ fontSize: 12, color: '#F0EBFF', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'baseline', gap: '0.3em' }}>
                          <span>{nextTier.label}까지</span>
                          <span style={{ color: tier.color, fontWeight: 700 }}>{eloToNext}</span>
                        </span>
                      </div>
                    )}
                  </div>
                )
              })()}

              {/* 스탯 row — MainPage StatItem 스타일 */}
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 32 }}>
                {[
                  { label: '현재 랭킹', value: myRank ? `${myRank}위` : '—', color: '#F5A624' },
                  { label: 'ELO',       value: String(userInfo?.elo ?? 0),   color: '#E8334A' },
                  { label: '승률',      value: `${winRate}%`,                color: '#4ade80' },
                  { label: '총 전적',   value: `${totalWins}승 ${totalLosses}패`, color: '#F0EBFF' },
                ].map(({ label, value, color }, i, arr) => (
                  <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
                    <div style={{ textAlign: 'center' }}>
                      <span style={{ color: MUTED, fontSize: 14, display: 'block', marginBottom: 4 }}>{label}</span>
                      <span style={{ fontFamily: DISPLAY_FONT, fontSize: 28, color }}>{value}</span>
                    </div>
                    {i < arr.length - 1 && (
                      <div style={{ width: 1, height: 40, background: 'rgba(255,255,255,.1)' }} />
                    )}
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* ── 하단 콘텐츠 ── */}
          <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 40px 60px', display: 'flex', flexDirection: 'column', gap: 20 }}>

            {/* 모드별 전적 카드 */}
            {bots.length > 0 && (() => {
              const modes = ['배틀로얄', '보스전', '모의주식'] as const
              return (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16 }}>
                  {modes.map((mode) => {
                    const mc = MODE_COLOR[mode]
                    let total: number, wins: number
                    if (mode === '모의주식') {
                      total = stocksStats?.games_played ?? 0
                      wins  = stocksStats?.wins ?? 0
                    } else {
                      const modeBots = bots.filter(b => b.game_mode === mode)
                      wins  = modeBots.filter(b => b.wins > 0).length
                      total = modeBots.length
                    }
                    const isSelected = selectedMode === mode
                    const borderCol = mc.border.replace('.4', isSelected ? '.7' : '.25')
                    const glowCol   = mc.bg.replace('.15', isSelected ? '.25' : '.12')

                    if (total === 0) return (
                      <div key={mode}
                        onClick={() => setSelectedMode(isSelected ? null : mode)}
                        style={{
                          background: PANEL_BG, border: `1px solid ${borderCol}`,
                          borderRadius: 14, padding: '18px 20px', opacity: .45, cursor: 'pointer',
                          boxShadow: `0 0 40px ${glowCol}`,
                          transition: 'transform .25s ease, border-color .25s ease',
                        }}>
                        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: mc.text }}>{mode}</span>
                        <p style={{ margin: '10px 0 0', fontSize: 13, color: MUTED }}>기록 없음</p>
                      </div>
                    )
                    const wr = Math.round((wins / total) * 100)
                    return (
                      <div key={mode}
                        onClick={() => setSelectedMode(isSelected ? null : mode)}
                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-4px)' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.transform = 'translateY(0)' }}
                        style={{
                          background: PANEL_BG,
                          border: `1px solid ${borderCol}`,
                          borderRadius: 14, padding: '18px 20px', cursor: 'pointer',
                          boxShadow: `0 0 40px ${glowCol}`,
                          transition: 'transform .25s ease, border-color .25s ease, box-shadow .25s ease',
                          outline: isSelected ? `2px solid ${mc.text}44` : 'none',
                        }}>
                        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: mc.text }}>{mode}</span>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, margin: '10px 0 4px' }}>
                          <span style={{ fontFamily: DISPLAY_FONT, fontSize: 28, color: '#F0EBFF' }}>{total}전</span>
                          <span style={{ fontSize: 13, color: '#4ade80' }}>{wins}승</span>
                          <span style={{ fontSize: 13, color: '#F05E70' }}>{total - wins}패</span>
                        </div>
                        <div style={{ height: 3, background: 'rgba(255,255,255,.08)', borderRadius: 999, overflow: 'hidden' }}>
                          <div style={{ width: `${wr}%`, height: '100%', background: mc.text, borderRadius: 999 }} />
                        </div>
                        <span style={{ fontSize: 11, color: MUTED, marginTop: 4, display: 'block' }}>승률 {wr}%</span>
                      </div>
                    )
                  })}
                </div>
              )
            })()}

            {/* ── 내 봇 관리 ── */}
            <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 14, overflow: 'hidden' }}>
              {/* 헤더 */}
              <div style={{ padding: '16px 20px', borderBottom: `1px solid ${PANEL_BORDER}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h4 style={{ fontWeight: 700, fontSize: 14, margin: 0 }}>내 봇 관리</h4>
                <span style={{ fontSize: 12, color: MUTED }}>{(selectedMode ? bots.filter(b => b.game_mode === selectedMode) : bots).length}개</span>
              </div>

              {bots.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '48px 0', color: MUTED, fontSize: 13 }}>아직 등록된 봇이 없습니다.</div>
              ) : (() => {
                const filtered = selectedMode ? bots.filter(b => b.game_mode === selectedMode) : bots
                const selected = filtered.find(b => b.id === expandedBotId) ?? null
                const curCode  = selected ? (editingCode[selected.id] ?? selected.code ?? '') : ''
                return (
                <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', minHeight: 420 }}>

                  {/* 왼쪽: 봇 카드 목록 */}
                  <div style={{ borderRight: `1px solid ${PANEL_BORDER}`, overflowY: 'auto', maxHeight: 520 }}>
                    {filtered.map(bot => {
                      const mc     = bot.game_mode ? MODE_COLOR[bot.game_mode] : null
                      const won    = bot.wins > 0
                      const played = bot.games_played > 0
                      const active = expandedBotId === bot.id
                      return (
                        <div key={bot.id}
                          onClick={() => {
                            setExpandedBotId(active ? null : bot.id)
                            if (!editingCode[bot.id] && bot.code) setEditingCode(prev => ({ ...prev, [bot.id]: bot.code! }))
                          }}
                          style={{
                            padding: '14px 16px', cursor: 'pointer',
                            borderBottom: `1px solid ${PANEL_BORDER}`,
                            borderLeft: active ? '3px solid #E8334A' : '3px solid transparent',
                            background: active ? 'rgba(232,51,74,.08)' : 'transparent',
                            transition: 'background .15s',
                          }}>
                          {/* 모드 뱃지 */}
                          {mc && <span style={{ fontSize: 9, fontWeight: 500, letterSpacing: '0.06em', color: mc.text, background: mc.bg, border: `1px solid ${mc.border}`, borderRadius: 999, padding: '2px 7px', display: 'inline-block', marginBottom: 6 }}>{bot.game_mode}</span>}
                          {/* 봇명 */}
                          <div style={{ fontSize: 13, fontWeight: 600, color: active ? '#F0EBFF' : '#B0A8D0', marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{bot.name}</div>
                          {bot.game_name && <div style={{ fontSize: 11, color: '#3D3558', marginBottom: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{bot.game_name}</div>}
                          {/* 하단: 승패 + 날짜 + 토글 */}
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <span style={{ fontSize: 11, fontWeight: 600, color: !played ? MUTED : won ? '#4ade80' : '#F05E70' }}>{!played ? '미경기' : won ? '승' : '패'}</span>
                              <span style={{ fontSize: 10, color: '#3D3558' }}>{formatDate(bot.created_at)}</span>
                            </div>
                            <button disabled={toggling === bot.id} onClick={e => { e.stopPropagation(); togglePublic(bot.id, bot.is_public) }}
                              style={{ position: 'relative', width: 32, height: 18, borderRadius: 999, border: 'none', cursor: 'pointer', flexShrink: 0, opacity: toggling === bot.id ? 0.5 : 1, background: bot.is_public ? 'rgba(74,222,128,.35)' : 'rgba(255,255,255,.1)', padding: 0 }}>
                              <span style={{ position: 'absolute', top: 2, width: 14, height: 14, borderRadius: '50%', background: bot.is_public ? '#4ade80' : '#554C78', left: bot.is_public ? 16 : 2, transition: 'left .2s' }} />
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  {/* 오른쪽: 코드 에디터 */}
                  {selected ? (
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                      {/* 에디터 헤더 */}
                      <div style={{ padding: '12px 20px', borderBottom: `1px solid ${PANEL_BORDER}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(0,0,0,.2)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontSize: 13, fontWeight: 600, color: '#F0EBFF' }}>{selected.name}</span>
                          {selected.game_mode && (() => { const mc = MODE_COLOR[selected.game_mode]; return <span style={{ fontSize: 9, fontWeight: 500, color: mc.text, background: mc.bg, border: `1px solid ${mc.border}`, borderRadius: 999, padding: '2px 7px' }}>{selected.game_mode}</span> })()}
                          <span style={{ fontSize: 11, color: selected.is_public ? '#4ade80' : MUTED }}>{selected.is_public ? '공개' : '비공개'}</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          {botSaveMsg[selected.id] && <span style={{ fontSize: 12, color: botSaveMsg[selected.id].includes('실패') ? '#F05E70' : '#4ade80' }}>{botSaveMsg[selected.id]}</span>}
                          <button onClick={() => saveBot(selected.id)} disabled={savingBot === selected.id}
                            style={{ padding: '6px 18px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, background: '#E8334A', color: '#fff', opacity: savingBot === selected.id ? 0.6 : 1 }}>
                            {savingBot === selected.id ? '저장 중...' : '저장'}
                          </button>
                        </div>
                      </div>
                      {/* 코드 에디터 */}
                      <PythonEditor
                        value={curCode}
                        onChange={code => setEditingCode(prev => ({ ...prev, [selected.id]: code }))}
                      />
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: MUTED, fontSize: 13, gap: 8 }}>
                      <span style={{ fontSize: 28, opacity: .3 }}>{'</>'}</span>
                      <span>봇을 선택하면 코드를 편집할 수 있습니다</span>
                    </div>
                  )}
                </div>
                )
              })()}
            </div>

            {/* ── 내 정보 설정 ── */}
            <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 14, padding: 28 }}>
              <h4 style={{ fontWeight: 700, fontSize: 14, margin: '0 0 28px' }}>내 정보 설정</h4>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 40 }}>

                {/* ① 계정 */}
                <div>
                  <SettingGroup label="계정">
                    <div style={{ marginBottom: 14 }}>
                      <label style={labelStyle}>아이디</label>
                      <div style={readonlyStyle}>{userInfo?.username ?? '—'}</div>
                    </div>
                    <div style={{ marginBottom: 14 }}>
                      <label style={labelStyle}>현재 닉네임</label>
                      <div style={readonlyStyle}>{userInfo?.display_name ?? '—'}</div>
                    </div>
                    <div style={{ marginBottom: 14 }}>
                      <label style={labelStyle}>닉네임 변경</label>
                      <input type="text" value={displayNameInput} onChange={e => setDisplayNameInput(e.target.value)}
                        placeholder="새 닉네임 입력" maxLength={20}
                        style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' as const }} />
                    </div>
                    <button disabled={savingName || !displayNameInput.trim()}
                      onClick={async () => {
                        if (!token || !displayNameInput.trim()) return
                        setSavingName(true); setSaveMsg('')
                        try {
                          const res = await fetch(`${API_BASE}/api/me`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ display_name: displayNameInput.trim() }) })
                          if (!res.ok) throw new Error()
                          setUserInfo(prev => prev ? { ...prev, display_name: displayNameInput.trim() } : prev)
                          setSaveMsg('변경되었습니다.'); setDisplayNameInput('')
                        } catch { setSaveMsg('저장 실패') } finally { setSavingName(false) }
                      }}
                      style={{ ...btnPrimary, opacity: savingName || !displayNameInput.trim() ? 0.4 : 1 }}>
                      {savingName ? '저장 중...' : '닉네임 저장'}
                    </button>
                    {saveMsg && <p style={{ margin: '8px 0 0', fontSize: 11, color: saveMsg.includes('실패') ? '#F05E70' : '#4ade80' }}>{saveMsg}</p>}
                  </SettingGroup>
                </div>

                {/* ② 게임 설정 */}
                <div>
                  <SettingGroup label="게임 설정">
                    {([
                      { key: 'botDefaultPublic',  label: '봇 코드 기본 공개',    desc: '게임 생성 시 코드 공개 ON으로 시작' },
                      { key: 'fillWithAI',        label: 'AI 자동 채우기',        desc: '최소 봇 수 미달 시 AI로 자동 채움' },
                      { key: 'showKillFeed',      label: '킬 피드 표시',          desc: '관전 화면에서 킬 이벤트 알림 표시' },
                      { key: 'autoSpectate',      label: '게임 생성 후 자동 관전', desc: '게임 시작 즉시 관전 화면으로 이동' },
                    ] as { key: string; label: string; desc: string }[]).map(item => (
                      <ToggleRow key={item.key} label={item.label} desc={item.desc}
                        value={!!settings[item.key]} onChange={() => toggleSetting(item.key)} />
                    ))}
                  </SettingGroup>
                </div>

                {/* ③ 알림 & 계정 관리 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
                  <SettingGroup label="알림">
                    {([
                      { key: 'notifyGameEnd',   label: '게임 종료 알림',    desc: '내 게임이 끝나면 알림', disabled: true },
                      { key: 'notifyRankUp',    label: '랭킹 상승 알림',    desc: '순위가 오르면 알림', disabled: true },
                    ] as { key: string; label: string; desc: string; disabled?: boolean }[]).map(item => (
                      <ToggleRow key={item.key} label={item.label} desc={item.desc}
                        value={!!settings[item.key]} onChange={() => toggleSetting(item.key)}
                        disabled={item.disabled} badge="준비 중" />
                    ))}
                  </SettingGroup>

                  <SettingGroup label="계정 관리">
                    <button onClick={() => navigate('/rankings')}
                      style={{ ...btnGhost, marginBottom: 8, width: '100%' }}>
                      리더보드 보기
                    </button>
                    <button onClick={async () => { await logout(); navigate('/login') }}
                      style={{ ...btnDanger, width: '100%' }}>
                      로그아웃
                    </button>
                  </SettingGroup>
                </div>

              </div>
            </div>

          </div>
        </>
      )}
    </div>
  )
}
