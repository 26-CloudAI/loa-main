import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'

const DISPLAY_FONT = '"JalnanGothic",system-ui,sans-serif'
const PANEL_BG     = '#221638'
const PANEL_BORDER = 'rgba(255,255,255,.06)'
const MUTED        = '#726890'

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
  '배틀로얄': { bg: 'rgba(232,51,74,.15)',  border: 'rgba(232,51,74,.4)',  text: '#F05E70' },
  '보스전':   { bg: 'rgba(155,89,245,.15)', border: 'rgba(155,89,245,.4)', text: '#C8A8FF' },
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
  is_public: boolean; wins: number; losses: number
  games_played: number; created_at: string
}
interface RankEntry { rank: number; username: string }

export default function MyPage() {
  const { user, token, logout } = useAuth()
  const navigate = useNavigate()
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null)
  const [bots, setBots]         = useState<BotInfo[]>([])
  const [myRank, setMyRank]     = useState<number | null>(null)
  const [loading, setLoading]   = useState(true)
  const [toggling, setToggling]       = useState<number | null>(null)
  const [barProgress, setBarProgress] = useState(0)

  useEffect(() => {
    if (!user?.id || !token) return
    Promise.all([
      fetch(`${API_BASE}/api/users/${user.id}/bots`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()),
      fetch(`${API_BASE}/api/rankings`).then(r => r.json()),
    ]).then(([ud, rd]) => {
      setUserInfo(ud.user)
      setBots(ud.bots ?? [])
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

  const tier    = userInfo ? getTier(userInfo.elo) : null
  const winRate = userInfo?.games_played
    ? ((userInfo.wins / userInfo.games_played) * 100).toFixed(1) : '0.0'

  return (
    <div style={{
      minHeight: '100vh', background: '#1A1030', color: '#F0EBFF',
      fontFamily: '"Pretendard Variable","Pretendard",system-ui,sans-serif',
    }}>

      {/* ── Nav ── */}
      <nav style={{
        background: 'rgba(26,16,48,.88)', backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        height: 56, padding: '0 28px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        position: 'sticky', top: 0, zIndex: 20,
        borderBottom: '1px solid rgba(255,255,255,.05)',
      }}>
        <button onClick={() => navigate('/games')}
          style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
          <span style={{ color: '#E8334A', fontSize: 16 }}>◆</span>
          <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.1em', color: '#F0EBFF' }}>LEAGUE OF AGENTS</span>
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
          <button onClick={() => navigate('/rankings')} style={{ color: MUTED, fontSize: 13, background: 'none', border: 'none', cursor: 'pointer' }}>리더보드</button>
          <button onClick={() => navigate('/games/list')} style={{ color: MUTED, fontSize: 13, background: 'none', border: 'none', cursor: 'pointer' }}>게임 목록</button>
          <button onClick={async () => { await logout(); navigate('/login') }}
            style={{ color: '#F0EBFF', fontSize: 13, background: 'none', border: 'none', cursor: 'pointer' }}>
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


              {/* MYPAGE pill */}
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '3px 12px', borderRadius: 999,
                background: 'rgba(155,89,245,.12)', border: '1px solid rgba(155,89,245,.3)', color: '#C8A8FF',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
                marginBottom: 20,
              }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#9B59F5', boxShadow: '0 0 8px #9B59F5', display: 'inline-block' }} />
                MYPAGE
              </div>

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
                        <span style={{ fontSize: 12, color: '#F0EBFF', whiteSpace: 'nowrap' }}>
                          {nextTier.label}까지{' '}
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
                  { label: '총 전적',   value: `${userInfo?.wins ?? 0}승 ${userInfo?.losses ?? 0}패`, color: '#F0EBFF' },
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

          {/* ── 게임 이력 패널 ── */}
          <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 40px 60px' }}>
            <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 14, padding: 24 }}>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <h4 style={{ fontWeight: 700, fontSize: 14, margin: 0 }}>게임 이력</h4>
                <span style={{ fontSize: 12, color: MUTED }}>{bots.length}전</span>
              </div>

              {bots.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '32px 0', color: MUTED, fontSize: 13 }}>
                  아직 참여한 게임이 없습니다.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {bots.map((bot) => {
                    const mc     = bot.game_mode ? MODE_COLOR[bot.game_mode] : null
                    const won    = bot.wins > 0
                    const played = bot.games_played > 0
                    return (
                      <div key={bot.id} style={{
                        display: 'flex', alignItems: 'center', gap: 14,
                        padding: '12px 16px', borderRadius: 10,
                        background: 'rgba(255,255,255,.03)',
                        border: '1px solid rgba(255,255,255,.05)',
                        borderLeft: played
                          ? `3px solid ${won ? '#4ade80' : '#E8334A'}`
                          : '3px solid rgba(255,255,255,.1)',
                      }}>
                        {/* 결과 */}
                        <span style={{
                          width: 28, textAlign: 'center', fontSize: 12, fontWeight: 700, flexShrink: 0,
                          color: !played ? MUTED : won ? '#4ade80' : '#F05E70',
                        }}>
                          {!played ? '—' : won ? 'W' : 'L'}
                        </span>

                        {/* 모드 뱃지 */}
                        {mc ? (
                          <span style={{
                            fontSize: 9, fontWeight: 700, letterSpacing: '0.07em',
                            color: mc.text, background: mc.bg, border: `1px solid ${mc.border}`,
                            borderRadius: 999, padding: '2px 8px', flexShrink: 0,
                          }}>{bot.game_mode}</span>
                        ) : <span style={{ width: 52 }} />}

                        {/* 봇명 + 게임명 */}
                        <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontSize: 13, fontWeight: 600, color: '#F0EBFF' }}>{bot.name}</span>
                          {bot.game_name && (
                            <span style={{ fontSize: 12, color: MUTED }}>{bot.game_name}</span>
                          )}
                        </div>

                        {/* 날짜 */}
                        <span style={{ fontSize: 11, color: '#3D3558', flexShrink: 0 }}>
                          {formatDate(bot.created_at)}
                        </span>

                        {/* 공개 토글 */}
                        <button
                          disabled={toggling === bot.id}
                          onClick={() => togglePublic(bot.id, bot.is_public)}
                          style={{
                            position: 'relative', width: 36, height: 20,
                            borderRadius: 999, border: 'none', cursor: 'pointer', flexShrink: 0,
                            opacity: toggling === bot.id ? 0.5 : 1,
                            background: bot.is_public ? 'rgba(74,222,128,.35)' : 'rgba(255,255,255,.1)',
                            transition: 'background .2s', padding: 0,
                          }}>
                          <span style={{
                            position: 'absolute', top: 3, width: 14, height: 14,
                            borderRadius: '50%',
                            background: bot.is_public ? '#4ade80' : '#554C78',
                            left: bot.is_public ? 19 : 3,
                            transition: 'left .2s, background .2s',
                            boxShadow: bot.is_public ? '0 0 6px rgba(74,222,128,.5)' : 'none',
                          }} />
                        </button>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
