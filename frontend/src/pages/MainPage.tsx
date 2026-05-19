import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const PANEL_BG = '#221638'
const PANEL_BORDER = 'rgba(255,255,255,.06)'
const MUTED = '#726890'
const DISPLAY_FONT = '"JalnanGothic",system-ui,sans-serif'

function StatItem({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <span style={{ color: MUTED, fontSize: 11, display: 'block', marginBottom: 4 }}>{label}</span>
      <span style={{ fontFamily: DISPLAY_FONT, fontSize: 28, color: color ?? '#F0EBFF' }}>{value}</span>
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
  onClick: () => void
}

function ModeCard({ mode, icon, title, desc, borderColor, glowColor, btnBg, btnColor, pillBg, pillColor, onClick }: ModeCardProps) {
  function onEnter(e: React.MouseEvent<HTMLDivElement>) {
    const el = e.currentTarget
    el.style.transform = 'translateY(-4px)'
    el.style.borderColor = borderColor.replace('.25', '.5')
  }
  function onLeave(e: React.MouseEvent<HTMLDivElement>) {
    const el = e.currentTarget
    el.style.transform = 'translateY(0)'
    el.style.borderColor = borderColor
  }

  return (
    <div
      onClick={onClick}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{
        background: PANEL_BG,
        border: `1px solid ${borderColor}`,
        borderRadius: 14,
        padding: 24,
        cursor: 'pointer',
        boxShadow: `0 0 40px ${glowColor}`,
        transition: 'transform .25s ease, box-shadow .25s ease, border-color .25s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          padding: '3px 10px', borderRadius: 999,
          background: pillBg, color: pillColor,
          fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
        }}>
          {mode}
        </span>
        <span style={{ fontSize: 28, color: pillColor.replace('FF', '').startsWith('#') ? pillColor : undefined, lineHeight: 1 }}>
          {icon}
        </span>
      </div>
      <h3 style={{ fontFamily: DISPLAY_FONT, fontSize: 26, margin: '0 0 4px', color: '#F0EBFF' }}>{title}</h3>
      <p style={{ color: MUTED, fontSize: 12, marginBottom: 20, margin: '0 0 20px' }}>{desc}</p>
      <button
        style={{
          width: '100%', padding: '10px 0', borderRadius: 8,
          background: btnBg, color: btnColor,
          border: 'none', fontSize: 14, cursor: 'pointer', fontWeight: 500,
        }}
      >
        시작하기 →
      </button>
    </div>
  )
}

export default function MainPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const displayName = user?.display_name ?? user?.username ?? 'Agent'

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: '#1A1030',
      color: '#F0EBFF',
      fontFamily: '"Pretendard Variable","Pretendard",system-ui,sans-serif',
    }}>
      {/* ── Nav ── */}
      <nav style={{
        background: 'rgba(26,16,48,.88)',
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
          <button onClick={() => navigate('/rankings')} style={navBtn}>리더보드</button>
          <button onClick={() => navigate('/games/list')} style={navBtn}>게임 목록</button>
          <button onClick={() => navigate('/mypage')} style={{ ...navBtn, color: '#F0EBFF' }}>
            {displayName} ▾
          </button>
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
          {/* Welcome pill */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '3px 12px', borderRadius: 999,
            background: 'rgba(155,89,245,.12)', border: '1px solid rgba(155,89,245,.3)', color: '#C8A8FF',
            fontSize: 10, fontWeight: 700, letterSpacing: '0.1em',
            marginBottom: 20,
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#9B59F5', boxShadow: '0 0 8px #9B59F5', display: 'inline-block' }} />
            WELCOME BACK
          </div>

          <h1 style={{ fontFamily: DISPLAY_FONT, fontSize: 48, margin: '0 0 10px', lineHeight: 1.2 }}>
            {displayName} <span style={{ color: MUTED }}>님,</span>
          </h1>
          <p style={{ color: MUTED, fontSize: 15, margin: '0 0 32px' }}>오늘도 봇을 단련시킬 시간입니다.</p>

          {/* Stats row */}
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 32 }}>
            <StatItem label="현재 랭킹" value="—" color="#F5A624" />
            <Divider />
            <StatItem label="총 전적" value="—" />
            <Divider />
            <StatItem label="승률" value="—" color="#E8334A" />
            <Divider />
            <StatItem label="보유 봇" value="—" color="#9B59F5" />
          </div>
        </div>
      </section>

      {/* ── Content ── */}
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 40px 60px' }}>

        {/* Mode Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20, marginBottom: 20 }}>
          <ModeCard
            mode="GAME MODE 01" icon="◆" title="배틀로얄" desc="최후의 1인이 되어라"
            borderColor="rgba(232,51,74,.25)" glowColor="rgba(232,51,74,.15)"
            btnBg="#E8334A" btnColor="#fff"
            pillBg="rgba(232,51,74,.15)" pillColor="#F05E70"
            onClick={() => navigate('/games/new/battle-royale')}
          />
          <ModeCard
            mode="GAME MODE 02" icon="◉" title="보스전" desc="거대한 적을 쓰러뜨려라"
            borderColor="rgba(155,89,245,.25)" glowColor="rgba(155,89,245,.15)"
            btnBg="#9B59F5" btnColor="#fff"
            pillBg="rgba(155,89,245,.15)" pillColor="#C8A8FF"
            onClick={() => navigate('/games/new/boss-battle')}
          />
          <ModeCard
            mode="GAME MODE 03" icon="▲" title="모의주식" desc="알고리즘으로 시장을 지배하라"
            borderColor="rgba(245,166,36,.25)" glowColor="rgba(245,166,36,.12)"
            btnBg="#F5A624" btnColor="#000"
            pillBg="rgba(245,166,36,.15)" pillColor="#FFC76A"
            onClick={() => navigate('/games/new/mock-stocks')}
          />
        </div>

        {/* Bottom Row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20 }}>
          {/* Recent Games */}
          <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 14, padding: 20, gridColumn: 'span 2' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h4 style={{ fontWeight: 700, fontSize: 14, margin: 0 }}>최근 게임</h4>
              <button
                onClick={() => navigate('/games/list')}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: MUTED, fontSize: 12 }}
              >
                전체보기 →
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '28px 0', color: MUTED, fontSize: 13 }}>
              <span>아직 게임 기록이 없습니다.</span>
            </div>
          </div>

          {/* Leaderboard Preview */}
          <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 14, padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h4 style={{ fontWeight: 700, fontSize: 14, margin: 0 }}>TOP 5 🏆</h4>
              <button
                onClick={() => navigate('/rankings')}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: MUTED, fontSize: 12 }}
              >
                전체 →
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '28px 0', color: MUTED, fontSize: 13 }}>
              <span>랭킹 데이터 준비 중</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

const navBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: MUTED,
  fontSize: 13,
  padding: 0,
}
