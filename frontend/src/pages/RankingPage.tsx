import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'
const FONT = '"SB Aggro",system-ui,sans-serif'
const MUTED = '#8A8EA8'
const PANEL_BG = '#1A1C28'
const PANEL_BORDER = 'rgba(255,255,255,.12)'
const PAGE_BG = '#0E0F15'

const ANIM_CSS = `
@keyframes podiumRise {
  from { opacity: 0; transform: translateY(48px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes goldPulse {
  0%,100% { box-shadow: 0 0 64px rgba(255,196,40,.50), 0 12px 40px rgba(0,0,0,.5); }
  50%      { box-shadow: 0 0 100px rgba(255,196,40,.80), 0 12px 40px rgba(0,0,0,.5); }
}
`

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

type TierKey = 'Grandmaster' | 'Master' | 'Diamond' | 'Platinum' | 'Gold' | 'Silver' | 'Bronze' | 'Iron'

const TIER_META: Record<TierKey, { hex: string; bg: string; border: string }> = {
  Grandmaster: { hex: '#f87171', bg: 'rgba(248,113,113,.16)', border: 'rgba(248,113,113,.4)' },
  Master:      { hex: '#c084fc', bg: 'rgba(192,132,252,.16)', border: 'rgba(192,132,252,.4)' },
  Diamond:     { hex: '#22d3ee', bg: 'rgba(34,211,238,.16)',  border: 'rgba(34,211,238,.4)'  },
  Platinum:    { hex: '#2dd4bf', bg: 'rgba(45,212,191,.16)', border: 'rgba(45,212,191,.4)'  },
  Gold:        { hex: '#facc15', bg: 'rgba(250,204,21,.16)', border: 'rgba(250,204,21,.4)'  },
  Silver:      { hex: '#e2e8f0', bg: 'rgba(226,232,240,.12)', border: 'rgba(226,232,240,.3)' },
  Bronze:      { hex: '#fb923c', bg: 'rgba(251,146,60,.14)',  border: 'rgba(251,146,60,.35)' },
  Iron:        { hex: '#94a3b8', bg: 'rgba(148,163,184,.12)', border: 'rgba(148,163,184,.28)' },
}

function getTier(elo: number): { label: TierKey } & typeof TIER_META[TierKey] {
  const key: TierKey =
    elo >= 2000 ? 'Grandmaster' :
    elo >= 1800 ? 'Master' :
    elo >= 1600 ? 'Diamond' :
    elo >= 1450 ? 'Platinum' :
    elo >= 1300 ? 'Gold' :
    elo >= 1150 ? 'Silver' :
    elo >= 1000 ? 'Bronze' : 'Iron'
  return { label: key, ...TIER_META[key] }
}

const PODIUM_CFG = {
  1: {
    color:   '#FFB830',
    accent:  'rgba(255,184,48,.85)',
    cardBg:  'linear-gradient(160deg, #2E260E 0%, #221C08 55%, rgba(255,184,48,.18) 100%)',
    shadow:  '0 0 56px rgba(255,184,48,.32), 0 12px 40px rgba(0,0,0,.6)',
    anim:    'goldPulse 4s ease-in-out infinite',
    cardH: 214, baseH: 56, label: '1ST', w: 180,
    delay: '0.0s',
  },
  2: {
    color:   '#C8D4DE',
    accent:  'rgba(200,212,222,.6)',
    cardBg:  'linear-gradient(160deg, #1E2028 0%, #18191F 100%)',
    shadow:  '0 0 36px rgba(200,212,222,.12), 0 8px 28px rgba(0,0,0,.55)',
    anim:    'none',
    cardH: 170, baseH: 38, label: '2ND', w: 154,
    delay: '0.3s',
  },
  3: {
    color:   '#E8904A',
    accent:  'rgba(232,144,74,.7)',
    cardBg:  'linear-gradient(160deg, #2A1C0C 0%, #1E1408 100%)',
    shadow:  '0 0 36px rgba(232,144,74,.18), 0 8px 28px rgba(0,0,0,.55)',
    anim:    'none',
    cardH: 150, baseH: 26, label: '3RD', w: 154,
    delay: '0.6s',
  },
} as const

const navBtn: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer',
  color: MUTED, fontSize: 13, padding: 0, transition: 'color .15s',
}

function TierBadge({ elo }: { elo: number }) {
  const tier = getTier(elo)
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      padding: '2px 9px 3px', borderRadius: 999,
      background: tier.bg, border: `1px solid ${tier.border}`,
      color: tier.hex, fontSize: 10, fontWeight: 600, letterSpacing: '0.05em',
    }}>
      {tier.label}
    </span>
  )
}

function PodiumPillar({ entry, isMe, animDelay }: { entry: RankingEntry; isMe: boolean; animDelay: string }) {
  const cfg = PODIUM_CFG[entry.rank as 1 | 2 | 3]
  const isFirst = entry.rank === 1

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', width: cfg.w,
      animation: `podiumRise 1.4s cubic-bezier(.22,.68,0,1.2) ${animDelay} both`,
    }}>
      {/* ── 카드 ── */}
      <div style={{
        height: cfg.cardH,
        background: cfg.cardBg,
        border: `1px solid rgba(255,255,255,.12)`,
        borderBottom: 'none',
        borderRadius: '5px 5px 0 0',
        boxShadow: cfg.shadow,
        animation: isFirst ? cfg.anim : undefined,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: 6, padding: '16px 12px',
        position: 'relative', overflow: 'hidden',
      }}>
        {/* 미묘한 상단 하이라이트 */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 1,
          background: `linear-gradient(90deg, transparent, ${cfg.accent}, transparent)`,
        }} />

        {/* 순위 숫자 */}
        <span style={{
          fontFamily: FONT,
          fontSize: isFirst ? 56 : 40,
          color: cfg.color,
          lineHeight: 1,
          fontVariantNumeric: 'tabular-nums',
          textShadow: `0 0 24px ${cfg.accent}`,
        }}>
          {entry.rank}
        </span>

        {/* 이름 */}
        <span style={{
          fontFamily: FONT,
          fontSize: isFirst ? 17 : 14,
          color: isMe ? '#C8A8FF' : '#F0F4FF',
          textAlign: 'center',
          lineHeight: 1.3,
          wordBreak: 'break-all',
          maxWidth: '100%',
        }}>
          {entry.display_name}
          {isMe && (
            <span style={{
              marginLeft: 5, fontSize: 9, fontWeight: 700,
              background: 'rgba(155,89,245,.3)', color: '#C8A8FF',
              border: '1px solid rgba(155,89,245,.5)', borderRadius: 4,
              padding: '1px 4px', verticalAlign: 'middle',
            }}>나</span>
          )}
        </span>

        {/* ELO */}
        <span style={{
          fontSize: 12, color: cfg.color, fontVariantNumeric: 'tabular-nums', opacity: 0.9,
          fontWeight: 600,
        }}>
          {entry.elo} ELO
        </span>

        {/* 티어 뱃지 */}
        <div style={{ marginTop: 2 }}>
          <TierBadge elo={entry.elo} />
        </div>
      </div>

      {/* ── 받침대 ── */}
      <div style={{
        height: cfg.baseH,
        background: 'linear-gradient(180deg, rgba(255,255,255,.05) 0%, rgba(255,255,255,.02) 100%)',
        borderLeft: `1px solid rgba(255,255,255,.10)`,
        borderRight: `1px solid rgba(255,255,255,.10)`,
        borderBottom: `1px solid rgba(255,255,255,.10)`,
        borderTop: `2px solid ${cfg.accent}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <span style={{
          fontSize: 10, fontWeight: 800, letterSpacing: '0.12em',
          color: cfg.color, opacity: 0.75,
        }}>
          {cfg.label}
        </span>
      </div>
    </div>
  )
}

export default function RankingPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [rankings, setRankings] = useState<RankingEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/api/rankings`)
      .then(r => { if (!r.ok) throw new Error(`서버 오류 (${r.status})`); return r.json() })
      .then(data => setRankings(data.rankings ?? []))
      .catch(e => setError(e instanceof Error ? e.message : '랭킹을 불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleLogout() { await logout(); navigate('/login') }

  const top3 = rankings.filter(r => r.rank <= 3)
  const rest  = rankings.filter(r => r.rank > 3)

  // 단상: 2위(좌) — 1위(중) — 3위(우)
  const podiumOrder: { entry: RankingEntry; delay: string }[] = [
    { rank: 2, delay: PODIUM_CFG[2].delay },
    { rank: 1, delay: PODIUM_CFG[1].delay },
    { rank: 3, delay: PODIUM_CFG[3].delay },
  ]
    .map(({ rank, delay }) => ({ entry: top3.find(r => r.rank === rank)!, delay }))
    .filter(x => x.entry)

  return (
    <>
      <style>{ANIM_CSS}</style>
      <div style={{
        minHeight: '100vh', background: PAGE_BG, color: '#E8EAF0',
        backgroundImage: 'linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px)',
        backgroundSize: '24px 24px',
      }}>

        {/* ── Nav ── */}
        <nav style={{
          background: 'rgba(15,18,25,.93)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
          height: 56, padding: '0 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          position: 'sticky', top: 0, zIndex: 20,
          borderBottom: '1px solid rgba(255,255,255,.07)',
        }}>
          <button type="button" onClick={() => navigate('/games')}
            style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
            <span style={{ color: '#E8334A', fontSize: 16, lineHeight: 1 }}>◆</span>
            <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.1em', color: '#F0EBFF' }}>LEAGUE OF AGENTS</span>
          </button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
            <button type="button" onClick={() => navigate('/games/list')} style={navBtn}
              onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>게임 목록</button>
            {user && (
              <button type="button" onClick={() => navigate('/mypage')}
                style={{ ...navBtn, display: 'flex', alignItems: 'center', gap: 6, color: '#F0EBFF' }}>
                {user.display_name ?? user.username}
                <span style={{
                  padding: '1px calc(6px - 0.05em) 1px 6px', fontSize: 10, fontWeight: 500,
                  background: 'rgba(155,89,245,.15)', color: '#C8A8FF',
                  border: '1px solid rgba(155,89,245,.35)', borderRadius: 4, letterSpacing: '0.05em',
                }}>{user.role}</span>▾
              </button>
            )}
            <button type="button" onClick={handleLogout} style={navBtn}
              onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>로그아웃</button>
          </div>
        </nav>

        {/* ── 헤더 ── */}
        <header style={{
          padding: '52px 24px 0', textAlign: 'center',
        }}>
          <h1 style={{ fontFamily: FONT, fontSize: 38, margin: '0 0 6px', lineHeight: 1.1, color: '#F4F6FF' }}>리더보드</h1>
          <p style={{ color: MUTED, fontSize: 13, margin: 0 }}>ELO 점수 기준 실시간 랭킹</p>
        </header>

        <main style={{ maxWidth: 840, margin: '0 auto', padding: '0 24px 88px' }}>
          {error && (
            <div style={{ marginTop: 32, fontSize: 13, color: '#f87171', background: 'rgba(248,113,113,.1)', borderRadius: 5, padding: '10px 16px' }}>
              {error}
            </div>
          )}

          {loading ? (
            <div style={{ textAlign: 'center', padding: '100px 0', color: MUTED, fontSize: 13 }}>불러오는 중...</div>
          ) : rankings.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '100px 0', color: MUTED, fontSize: 13 }}>아직 랭킹 데이터가 없습니다.</div>
          ) : (
            <>
              {/* ── 단상 ── */}
              {podiumOrder.length > 0 && (
                <div style={{
                  display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
                  gap: 10, marginTop: 52,
                }}>
                  {podiumOrder.map(({ entry, delay }) => (
                    <PodiumPillar
                      key={entry.user_id}
                      entry={entry}
                      isMe={!!(user && entry.username === user.username)}
                      animDelay={delay}
                    />
                  ))}
                </div>
              )}

              {/* ── 4위 이하 리스트 ── */}
              {rest.length > 0 && (
                <div style={{
                  marginTop: 32, background: PANEL_BG,
                  border: `1px solid ${PANEL_BORDER}`, borderRadius: 5, overflow: 'hidden',
                }}>
                  {/* 헤더 */}
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: '64px 260px 1fr 80px 96px 72px',
                    padding: '10px 20px',
                    background: 'rgba(255,255,255,.03)',
                    borderBottom: `1px solid ${PANEL_BORDER}`,
                  }}>
                    {(['순위', 'ID', '티어', 'ELO', '전적', ''] as const).map(h => (
                      <div key={h} style={{
                        fontSize: 10, color: MUTED, fontWeight: 500, letterSpacing: '0.06em',
                        display: 'flex', justifyContent: 'center', alignItems: 'center',
                      }}>
                        {h}
                      </div>
                    ))}
                  </div>

                  {/* 행 */}
                  {rest.map((entry, i) => {
                    const isMe = !!(user && entry.username === user.username)
                    return (
                      <div
                        key={entry.user_id}
                        style={{
                          display: 'grid',
                          gridTemplateColumns: '64px 260px 1fr 80px 96px 72px',
                          alignItems: 'center',
                          padding: '13px 20px',
                          borderTop: i > 0 ? `1px solid ${PANEL_BORDER}` : undefined,
                          background: isMe ? 'rgba(155,89,245,.09)' : undefined,
                          borderLeft: isMe ? '3px solid rgba(155,89,245,.55)' : '3px solid transparent',
                          transition: 'background .15s',
                        }}
                        onMouseEnter={e => { if (!isMe) e.currentTarget.style.background = 'rgba(255,255,255,.04)' }}
                        onMouseLeave={e => { if (!isMe) e.currentTarget.style.background = '' }}
                      >
                        {/* 순위 — 중앙 */}
                        <div style={{ display: 'flex', justifyContent: 'center' }}>
                          <span style={{
                            fontFamily: FONT, fontSize: 18,
                            color: isMe ? '#C8A8FF' : MUTED,
                            fontVariantNumeric: 'tabular-nums',
                          }}>
                            {entry.rank}
                          </span>
                        </div>

                        {/* 유저 — 중앙 */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 1, alignItems: 'center' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                            <span style={{ fontFamily: FONT, fontSize: 15, color: isMe ? '#C8A8FF' : '#F0F4FF' }}>
                              {entry.display_name}
                            </span>
                            {isMe && (
                              <span style={{
                                fontSize: 9, fontWeight: 700,
                                background: 'rgba(155,89,245,.28)', color: '#C8A8FF',
                                border: '1px solid rgba(155,89,245,.45)', borderRadius: 4,
                                padding: '1px 4px',
                              }}>나</span>
                            )}
                          </div>
                        </div>

                        {/* 티어 — 중앙 */}
                        <div style={{ display: 'flex', justifyContent: 'center' }}>
                          <TierBadge elo={entry.elo} />
                        </div>

                        {/* ELO — 중앙 */}
                        <div style={{ textAlign: 'center' }}>
                          <span style={{
                            fontFamily: FONT, fontSize: 15,
                            color: '#E8EEF8', fontVariantNumeric: 'tabular-nums',
                          }}>
                            {entry.elo}
                          </span>
                        </div>

                        {/* 전적 — 중앙 */}
                        <div style={{ fontSize: 12, textAlign: 'center' }}>
                          <span style={{ color: '#4ade80' }}>{entry.wins}승</span>
                          <span style={{ color: MUTED, margin: '0 3px' }}>/</span>
                          <span style={{ color: '#f87171' }}>{entry.losses}패</span>
                        </div>

                        {/* 봇 보기 — 중앙 */}
                        <div style={{ display: 'flex', justifyContent: 'center' }}>
                          <button
                            type="button"
                            onClick={() => navigate(`/users/${entry.user_id}/bots`)}
                            style={{
                              background: 'none', border: `1px solid ${PANEL_BORDER}`, borderRadius: 6,
                              padding: '4px 10px', color: MUTED, fontSize: 11, cursor: 'pointer',
                              transition: 'color .15s, border-color .15s',
                            }}
                            onMouseEnter={e => { e.currentTarget.style.color = '#F0F4FF'; e.currentTarget.style.borderColor = 'rgba(255,255,255,.24)' }}
                            onMouseLeave={e => { e.currentTarget.style.color = MUTED; e.currentTarget.style.borderColor = PANEL_BORDER }}
                          >
                            봇 보기
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </>
  )
}
