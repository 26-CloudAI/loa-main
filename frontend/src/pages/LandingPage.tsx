import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/* ── Floating background symbol ── */
function FloatEl({
  children,
  animCls,
  style,
}: {
  children: ReactNode
  animCls: string
  style: CSSProperties
}) {
  return (
    <div
      className={`absolute pointer-events-none select-none ${animCls}`}
      style={style}
    >
      {children}
    </div>
  )
}

/* ── CSS animation injection ── */
const ANIM_CSS = `
  @keyframes loa-flt  { 0%,100%{transform:translateY(0) rotate(0deg)}  50%{transform:translateY(-24px) rotate(5deg)} }
  @keyframes loa-fltr { 0%,100%{transform:translateY(0) rotate(0deg)}  50%{transform:translateY(-18px) rotate(-6deg)} }
  @keyframes loa-glw  { 0%,100%{opacity:.3} 50%{opacity:.65} }
  .lf1{animation:loa-flt   7s ease-in-out infinite}
  .lf2{animation:loa-fltr  9s ease-in-out infinite;animation-delay:-3s}
  .lf3{animation:loa-flt   6s ease-in-out infinite;animation-delay:-5s}
  .lf4{animation:loa-fltr  8s ease-in-out infinite;animation-delay:-1s}
  .lf5{animation:loa-flt  11s ease-in-out infinite;animation-delay:-7s}
  .lf6{animation:loa-fltr 10s ease-in-out infinite;animation-delay:-4s}
  .loa-glw{animation:loa-glw 4s ease-in-out infinite}
  .loa-reveal{opacity:0;transform:translateY(44px);transition:opacity .85s cubic-bezier(.16,1,.3,1),transform .85s cubic-bezier(.16,1,.3,1)}
  .loa-visible{opacity:1;transform:translateY(0)}
  .loa-sect .sect-g1{opacity:0;transform:translateY(32px);transition:opacity .75s cubic-bezier(.16,1,.3,1),transform .75s cubic-bezier(.16,1,.3,1)}
  .loa-sect .sect-g2{opacity:0;transform:translateY(32px);transition:opacity .75s .24s cubic-bezier(.16,1,.3,1),transform .75s .24s cubic-bezier(.16,1,.3,1)}
  .loa-sect .sect-g3{opacity:0;transform:translateY(32px);transition:opacity .75s .48s cubic-bezier(.16,1,.3,1),transform .75s .48s cubic-bezier(.16,1,.3,1)}
  .loa-sect.loa-visible .sect-g1,.loa-sect.loa-visible .sect-g2,.loa-sect.loa-visible .sect-g3{opacity:1;transform:translateY(0)}
`

export default function LandingPage() {
  const { token } = useAuth()
  const ctaTo = token ? '/games' : '/login'

  useEffect(() => {
    const el = document.createElement('style')
    el.id = 'loa-landing-css'
    el.textContent = ANIM_CSS
    if (!document.getElementById('loa-landing-css')) {
      document.head.appendChild(el)
    }
    return () => document.getElementById('loa-landing-css')?.remove()
  }, [])

  return (
    <div
      className="min-h-screen overflow-x-hidden"
      style={{ background: '#0D0F14', color: '#E8EAF0', fontFamily: '"SB Aggro", system-ui, sans-serif' }}
    >
      <Nav token={token} ctaTo={ctaTo} />
      <HeroSection ctaTo={ctaTo} />
      <BattleRoyaleSection />
      <BossBattleSection />
      <MockStocksSection />
      <BottomCTA ctaTo={ctaTo} loggedIn={!!token} />
    </div>
  )
}

/* ═══════════════════════════════════════════
   Navigation
═══════════════════════════════════════════ */
function Nav({ token, ctaTo }: { token: string | null; ctaTo: string }) {
  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-8 py-4"
      style={{
        background: 'rgba(13,15,20,.92)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
      }}
    >
      <Link
        to="/"
        style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none', color: '#E8EAF0' }}
      >
        <span style={{ fontSize: 16, lineHeight: 1, color: '#E8334A' }}>◆</span>
        <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          League of Agents
        </span>
      </Link>

      <nav style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <Link
          to={ctaTo}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#E8334A',
            color: '#fff',
            fontSize: 13,
            fontWeight: 500,
            padding: '8px 18px',
            borderRadius: 6,
            textDecoration: 'none',
            letterSpacing: '0.04em',
          }}
        >
          {token ? '아레나 입장' : '로그인'}
        </Link>
      </nav>
    </header>
  )
}

/* ═══════════════════════════════════════════
   Hero
═══════════════════════════════════════════ */
function HeroSection({ ctaTo }: { ctaTo: string }) {
  return (
    <section
      className="relative flex flex-col items-center justify-center text-center min-h-screen px-6"
      style={{ paddingTop: 80 }}
    >
      {/* Ambient glow */}
      <div
        className="absolute inset-0 loa-glw pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 65% 55% at 50% 42%, rgba(232,51,74,.14) 0%, transparent 68%)',
        }}
      />

      {/* Floating symbols */}
      <FloatEl animCls="lf1" style={{ top: '14%', left: '8%',   fontSize: 90, color: '#E8334A', opacity: .18 }}>◆</FloatEl>
      <FloatEl animCls="lf2" style={{ top: '18%', right: '10%', fontSize: 65, color: '#9B59F5', opacity: .18 }}>◉</FloatEl>
      <FloatEl animCls="lf3" style={{ bottom: '22%', left: '12%', fontSize: 50, color: '#F5A624', opacity: .18 }}>▲</FloatEl>
      <FloatEl animCls="lf4" style={{ bottom: '18%', right: '9%', fontSize: 75, color: '#E8334A', opacity: .15 }}>◈</FloatEl>
      <FloatEl animCls="lf5" style={{ top: '42%', left: '4%',   fontSize: 40, color: '#9B59F5', opacity: .13 }}>✦</FloatEl>
      <FloatEl animCls="lf6" style={{ top: '38%', right: '5%',  fontSize: 44, color: '#F5A624', opacity: .15 }}>◆</FloatEl>

      <div className="relative z-10" style={{ maxWidth: 680, marginTop: -60 }}>
        {/* Live badge */}
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            background: 'rgba(232,51,74,.12)',
            border: '1px solid rgba(232,51,74,.3)',
            borderRadius: 999,
            padding: '7px calc(18px - 0.1em) 7px 18px',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '0.1em',
            color: '#F05E70',
            marginBottom: 28,
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: '#E8334A',
              boxShadow: '0 0 6px #E8334A',
              flexShrink: 0,
            }}
          />
          <span style={{ lineHeight: 1, display: 'block' }}>AI BATTLE ARENA</span>
        </div>

        <h1
          style={{
            fontSize: 'clamp(42px, 6.5vw, 80px)',
            fontWeight: 500,
            lineHeight: 1.08,
            letterSpacing: '-0.025em',
            color: '#E8EAF0',
            marginBottom: 22,
          }}
        >
          당신의 코드가
          <br />
          <span style={{ color: '#E8334A' }}>싸웁니다</span>
        </h1>

        <p
          style={{
            fontSize: 17,
            color: '#5A6270',
            lineHeight: 1.75,
            marginBottom: 40,
            maxWidth: 480,
            marginLeft: 'auto',
            marginRight: 'auto',
          }}
        >
          Python 봇을 작성하고 AI 배틀 아레나에 참가하세요.
          <br />
          배틀로얄 · 보스전 · 모의주식 — 세 가지 전장이 기다립니다.
        </p>

        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <Link
            to={ctaTo}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: '#E8334A',
              color: '#fff',
              fontSize: 17,
              fontWeight: 500,
              letterSpacing: '0.06em',
              padding: '14px 36px',
              borderRadius: 8,
              textDecoration: 'none',
              boxShadow: '0 4px 32px rgba(232,51,74,.38)',
            }}
          >
            지금 플레이하기 →
          </Link>
        </div>
      </div>

    </section>
  )
}

/* ═══════════════════════════════════════════
   Generic game mode section
═══════════════════════════════════════════ */
interface FloatDef {
  sym: string
  animCls: string
  style: CSSProperties
}

interface GameSectProps {
  num: string
  title: string
  sub: string
  desc: string
  features: string[]
  accent: string
  faint: string
  border: string
  glow: string
  floats: FloatDef[]
  visual: ReactNode
  reverse?: boolean
  fadeInThreshold?: number
  fadeOutThreshold?: number
}

function GameSect({
  num, title, sub, desc, features,
  accent, faint, border, glow,
  floats, visual, reverse,
  fadeInThreshold = 0.35,
  fadeOutThreshold = 0.7,
}: GameSectProps) {
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = contentRef.current
    if (!el) return

    const fadeInObs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) el.classList.add('loa-visible') },
      { threshold: fadeInThreshold },
    )
    const fadeOutObs = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting && entry.boundingClientRect.top > 0)
          el.classList.remove('loa-visible')
      },
      { threshold: fadeOutThreshold },
    )

    fadeInObs.observe(el)
    fadeOutObs.observe(el)
    return () => { fadeInObs.disconnect(); fadeOutObs.disconnect() }
  }, [])

  return (
    <section
      className="relative min-h-screen flex items-center overflow-hidden"
      style={{ borderTop: '1px solid rgba(255,255,255,.04)' }}
    >
      {/* Section glow */}
      <div className="absolute inset-0 pointer-events-none" style={{ background: glow }} />

      {/* Floating symbols */}
      {floats.map((f, i) => (
        <FloatEl key={i} animCls={f.animCls} style={f.style}>
          {f.sym}
        </FloatEl>
      ))}

      <div
        ref={contentRef}
        className="loa-sect relative z-10 w-full max-w-6xl mx-auto px-8 py-24"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 64,
          flexDirection: reverse ? 'row-reverse' : 'row',
        }}
      >
        {/* Text column */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Group 1: 뱃지 + 타이틀 + 소제목 */}
          <div className="sect-g1">
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                background: faint,
                border: `1px solid ${border}`,
                borderRadius: 999,
                padding: '4px 12px',
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.12em',
                color: accent,
                marginBottom: 20,
              }}
            >
              GAME MODE {num}
            </div>

            <h2
              style={{
                fontSize: 'clamp(30px, 3.8vw, 52px)',
                fontWeight: 500,
                lineHeight: 1.1,
                letterSpacing: '-0.02em',
                color: '#E8EAF0',
                marginBottom: 10,
              }}
            >
              {title}
            </h2>

            <p style={{ fontSize: 17, fontWeight: 600, color: accent, marginBottom: 16 }}>{sub}</p>
          </div>

          {/* Group 2: 설명 */}
          <p
            className="sect-g2"
            style={{
              fontSize: 15,
              color: '#5A6270',
              lineHeight: 1.8,
              marginBottom: 28,
              maxWidth: 420,
            }}
          >
            {desc}
          </p>

          {/* Group 3: 특징 목록 */}
          <ul className="sect-g3" style={{ display: 'flex', flexDirection: 'column', gap: 12, listStyle: 'none', padding: 0 }}>
            {features.map((f, i) => (
              <li
                key={i}
                style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, color: '#8090A0' }}
              >
                <span
                  style={{ width: 6, height: 6, borderRadius: '50%', background: accent, flexShrink: 0 }}
                />
                {f}
              </li>
            ))}
          </ul>
        </div>

        {/* Visual column — Group 1과 함께 등장 */}
        <div className="sect-g1" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 256 }}>
          {visual}
        </div>
      </div>
    </section>
  )
}

/* ═══════════════════════════════════════════
   Battle Royale
═══════════════════════════════════════════ */
function BattleRoyaleSection() {
  return (
    <GameSect
      num="01"
      title="배틀로얄"
      sub="최후의 1인이 되어라"
      desc="다수의 AI 봇이 동시에 참가하는 서바이벌 전투. 자원을 수집하고 전략적으로 움직이며 마지막까지 살아남은 봇이 승자가 됩니다."
      features={[
        '최대 8봇 동시 대전',
        '실시간 전장 관전 및 플레이 로그',
        'ELO 기반 랭킹 시스템',
      ]}
      accent="#9B59F5"
      faint="rgba(155,89,245,.12)"
      border="rgba(155,89,245,.35)"
      glow="radial-gradient(ellipse 55% 70% at 75% 50%, rgba(155,89,245,.1) 0%, transparent 70%)"
      floats={[
        { sym: '◆', animCls: 'lf1', style: { top: '8%',   right: '5%',  fontSize: 110, color: '#9B59F5', opacity: .07 } },
        { sym: '✦', animCls: 'lf2', style: { bottom: '12%', right: '18%', fontSize: 70, color: '#9B59F5', opacity: .06 } },
        { sym: '◈', animCls: 'lf3', style: { top: '35%',  right: '32%', fontSize: 45, color: '#E8EAF0', opacity: .04 } },
        { sym: '▲', animCls: 'lf4', style: { bottom: '28%', right: '6%', fontSize: 55, color: '#9B59F5', opacity: .07 } },
        { sym: '◉', animCls: 'lf5', style: { top: '55%',  right: '24%', fontSize: 65, color: '#E8EAF0', opacity: .03 } },
        { sym: '◆', animCls: 'lf6', style: { top: '18%',  right: '44%', fontSize: 38, color: '#9B59F5', opacity: .04 } },
      ]}
      visual={<BRVisual />}
    />
  )
}

function BRVisual() {
  const dots = [0, 60, 120, 180, 240, 300]
  return (
    <div
      style={{
        position: 'relative',
        width: 280,
        height: 280,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(155,89,245,.2) 0%, transparent 70%)',
        }}
      />
      <div
        style={{
          fontSize: 96,
          color: '#9B59F5',
          lineHeight: 1,
          textShadow: '0 0 50px rgba(155,89,245,.5)',
          zIndex: 1,
        }}
      >
        ◆
      </div>
      {dots.map((deg, i) => {
        const rad = (deg * Math.PI) / 180
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              width: i === 0 ? 9 : 6,
              height: i === 0 ? 9 : 6,
              borderRadius: '50%',
              background: i === 0 ? '#9B59F5' : '#2D1475',
              top: `${50 + 43 * Math.sin(rad)}%`,
              left: `${50 + 43 * Math.cos(rad)}%`,
              transform: 'translate(-50%, -50%)',
              boxShadow: i === 0 ? '0 0 10px #9B59F5' : 'none',
            }}
          />
        )
      })}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: '50%',
          border: '1px solid rgba(155,89,245,.2)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 18,
          borderRadius: '50%',
          border: '1px dashed rgba(155,89,245,.1)',
        }}
      />
    </div>
  )
}

/* ═══════════════════════════════════════════
   Boss Battle
═══════════════════════════════════════════ */
function BossBattleSection() {
  return (
    <GameSect
      num="02"
      title="보스전"
      sub="거대한 적을 쓰러뜨려라"
      desc="강력한 보스 몬스터에 맞서 여러 봇이 협력 또는 경쟁하며 싸우는 모드. 최대 피해를 입힌 봇이 승리를 가져갑니다."
      features={[
        '단계별 보스 패턴 — 높아지는 난이도',
        '협력 / 경쟁 전략의 갈림길',
        '처치 기여도 기반 점수 산정',
      ]}
      accent="#E8334A"
      faint="rgba(232,51,74,.12)"
      border="rgba(232,51,74,.35)"
      glow="radial-gradient(ellipse 55% 70% at 25% 50%, rgba(232,51,74,.1) 0%, transparent 70%)"
      floats={[
        { sym: '◉', animCls: 'lf1', style: { top: '8%',   left: '5%',  fontSize: 110, color: '#E8334A', opacity: .07 } },
        { sym: '▲', animCls: 'lf2', style: { bottom: '12%', left: '18%', fontSize: 70, color: '#E8334A', opacity: .06 } },
        { sym: '◆', animCls: 'lf3', style: { top: '35%',  left: '32%', fontSize: 45, color: '#E8EAF0', opacity: .04 } },
        { sym: '✦', animCls: 'lf4', style: { bottom: '28%', left: '6%', fontSize: 55, color: '#E8334A', opacity: .07 } },
        { sym: '◈', animCls: 'lf5', style: { top: '55%',  left: '24%', fontSize: 65, color: '#E8EAF0', opacity: .03 } },
        { sym: '◉', animCls: 'lf6', style: { top: '18%',  left: '44%', fontSize: 38, color: '#E8334A', opacity: .04 } },
      ]}
      visual={<BossVisual />}
      reverse
      fadeInThreshold={0.5}
      fadeOutThreshold={0.85}
    />
  )
}

function BossVisual() {
  const dots = [0, 45, 90, 135, 180, 225, 270, 315]
  return (
    <div
      style={{
        position: 'relative',
        width: 280,
        height: 280,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(232,51,74,.2) 0%, transparent 70%)',
        }}
      />
      <div
        style={{
          fontSize: 96,
          color: '#E8334A',
          lineHeight: 1,
          textShadow: '0 0 50px rgba(232,51,74,.5)',
          zIndex: 1,
        }}
      >
        ◉
      </div>
      {dots.map((deg, i) => {
        const rad = (deg * Math.PI) / 180
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              width: i % 2 === 0 ? 8 : 5,
              height: i % 2 === 0 ? 8 : 5,
              borderRadius: '50%',
              background: i % 2 === 0 ? '#E8334A' : '#6B0E1A',
              top: `${50 + 43 * Math.sin(rad)}%`,
              left: `${50 + 43 * Math.cos(rad)}%`,
              transform: 'translate(-50%, -50%)',
              boxShadow: i % 2 === 0 ? '0 0 8px #E8334A' : 'none',
            }}
          />
        )
      })}
      <div style={{ position: 'absolute', inset: 0,  borderRadius: '50%', border: '1px solid rgba(232,51,74,.2)' }} />
      <div style={{ position: 'absolute', inset: 18, borderRadius: '50%', border: '1px dashed rgba(232,51,74,.1)' }} />
      <div style={{ position: 'absolute', inset: 36, borderRadius: '50%', border: '1px solid rgba(232,51,74,.07)' }} />
    </div>
  )
}

/* ═══════════════════════════════════════════
   Mock Stocks
═══════════════════════════════════════════ */
function MockStocksSection() {
  return (
    <GameSect
      num="03"
      title="모의주식"
      sub="알고리즘으로 시장을 지배해라"
      desc="AI 봇이 모의 주식 시장에서 자동 매매를 수행합니다. 최적의 매수·매도 타이밍을 찾는 트레이딩 알고리즘을 코딩하세요."
      features={[
        '실시간 가격 변동 시뮬레이션',
        '매수 / 매도 API로 자유로운 전략 구현',
        '최종 포트폴리오 수익률 기반 순위',
      ]}
      accent="#F5A624"
      faint="rgba(245,166,36,.12)"
      border="rgba(245,166,36,.35)"
      glow="radial-gradient(ellipse 55% 70% at 75% 50%, rgba(245,166,36,.08) 0%, transparent 70%)"
      floats={[
        { sym: '▲', animCls: 'lf1', style: { top: '8%',   right: '5%',  fontSize: 100, color: '#F5A624', opacity: .08 } },
        { sym: '◆', animCls: 'lf2', style: { bottom: '12%', right: '18%', fontSize: 65, color: '#F5A624', opacity: .06 } },
        { sym: '✦', animCls: 'lf3', style: { top: '35%',  right: '32%', fontSize: 45, color: '#E8EAF0', opacity: .04 } },
        { sym: '◈', animCls: 'lf4', style: { bottom: '28%', right: '6%', fontSize: 55, color: '#F5A624', opacity: .07 } },
        { sym: '◉', animCls: 'lf5', style: { top: '55%',  right: '24%', fontSize: 60, color: '#E8EAF0', opacity: .03 } },
        { sym: '▲', animCls: 'lf6', style: { top: '18%',  right: '44%', fontSize: 38, color: '#F5A624', opacity: .05 } },
      ]}
      visual={<StocksVisual />}
    />
  )
}

function StocksVisual() {
  const bars = [28, 45, 38, 62, 42, 75, 55, 82, 68, 90]
  return (
    <div
      style={{
        width: 300,
        padding: '16px 20px 12px',
        background: 'rgba(22,26,35,.85)',
        borderRadius: 14,
        border: '1px solid rgba(245,166,36,.2)',
        boxShadow: '0 0 40px rgba(245,166,36,.07)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <span style={{ fontSize: 10, fontWeight: 700, color: '#F5A624', letterSpacing: '0.08em' }}>
          PORTFOLIO
        </span>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#F5A624', fontFamily: 'monospace' }}>
          +24.3%
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 5, height: 120, position: 'relative' }}>
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: 1,
            background: 'rgba(245,166,36,.12)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 0,
            height: 1,
            background: 'rgba(245,166,36,.12)',
          }}
        />
        {bars.map((h, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              height: `${h}%`,
              background:
                i === bars.length - 1
                  ? '#F5A624'
                  : `rgba(245,166,36,${.18 + (i / bars.length) * .32})`,
              borderRadius: '2px 2px 0 0',
              boxShadow: i === bars.length - 1 ? '0 0 10px rgba(245,166,36,.5)' : 'none',
            }}
          />
        ))}
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════
   Bottom CTA
═══════════════════════════════════════════ */
function BottomCTA({ ctaTo, loggedIn }: { ctaTo: string; loggedIn: boolean }) {
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = contentRef.current
    if (!el) return

    const fadeInObs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) el.classList.add('loa-visible') },
      { threshold: 0.4 },
    )
    const fadeOutObs = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting && entry.boundingClientRect.top > 0)
          el.classList.remove('loa-visible')
      },
      { threshold: 0.7 },
    )

    fadeInObs.observe(el)
    fadeOutObs.observe(el)
    return () => { fadeInObs.disconnect(); fadeOutObs.disconnect() }
  }, [])

  return (
    <section
      className="relative flex flex-col items-center justify-center text-center py-36 pb-28 px-6"
      style={{ borderTop: '1px solid rgba(255,255,255,.04)' }}
    >
      <div
        className="absolute inset-0 loa-glw pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 60% 70% at 50% 50%, rgba(232,51,74,.07) 0%, transparent 70%)',
        }}
      />
      <div ref={contentRef} className="loa-reveal relative z-10">
        <h2
          style={{
            fontSize: 'clamp(26px, 3.8vw, 46px)',
            fontWeight: 500,
            letterSpacing: '-0.02em',
            color: '#E8EAF0',
            marginBottom: 14,
          }}
        >
          지금 바로 참전하세요
        </h2>
        <p style={{ fontSize: 16, color: '#5A6270', marginBottom: 36 }}>
          Python 봇 하나면 충분합니다.
        </p>
        <Link
          to={ctaTo}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#E8334A',
            color: '#fff',
            fontSize: 17,
            fontWeight: 500,
            letterSpacing: '0.06em',
            padding: '11px 32px',
            borderRadius: 8,
            textDecoration: 'none',
            boxShadow: '0 4px 40px rgba(232,51,74,.32)',
          }}
        >
          {loggedIn ? '아레나 입장 →' : '무료로 시작하기 →'}
        </Link>
      </div>
    </section>
  )
}
