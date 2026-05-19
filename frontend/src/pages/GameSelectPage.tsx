import React from 'react'
import { useNavigate } from 'react-router-dom'

interface ModeTheme {
  border: string
  glow: string
  accent: string
  accentBg: string
}

interface GameMode {
  id: string
  title: string
  description: React.ReactNode
  icon: string
  available: boolean
  route?: string
  theme: ModeTheme
}

const MODES: GameMode[] = [
  {
    id: 'battle-royale',
    title: '배틀로얄',
    description: 'AI 봇을 코딩해 맵에서 싸워라. 채굴·전투·생존으로 최고 점수를 노려라.',
    icon: '⚔️',
    available: true,
    route: '/games/new/battle-royale',
    theme: {
      border:   'rgba(232,51,74,.35)',
      glow:     'rgba(232,51,74,.12)',
      accent:   '#F05E70',
      accentBg: 'rgba(232,51,74,.15)',
    },
  },
  {
    id: 'boss-battle',
    title: '보스전',
    description: <>강화학습으로 훈련된 보스 봇과 1대1로 맞붙어라. <span className="whitespace-nowrap">이길 수 있겠어?</span></>,
    icon: '👾',
    available: true,
    route: '/games/new/boss-battle',
    theme: {
      border:   'rgba(155,89,245,.35)',
      glow:     'rgba(155,89,245,.12)',
      accent:   '#C8A8FF',
      accentBg: 'rgba(155,89,245,.15)',
    },
  },
  {
    id: 'mock-stock',
    title: '모의주식',
    description: '실시간 시세를 예측하는 트레이딩 AI를 만들어 수익률을 겨뤄라.',
    icon: '📈',
    available: true,
    route: '/games/new/mock-stocks',
    theme: {
      border:   'rgba(245,166,36,.35)',
      glow:     'rgba(245,166,36,.1)',
      accent:   '#FFC76A',
      accentBg: 'rgba(245,166,36,.15)',
    },
  },
]

export default function GameSelectPage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col">
      <header className="sticky top-0 z-20 h-14 border-b border-gray-800 bg-gray-950 px-6 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate('/games')}
          className="text-gray-400 hover:text-white text-sm transition-colors"
        >
          ◀ 메인
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">게임 모드 선택</span>
      </header>

      <main className="flex flex-1 flex-col items-center px-6">
        <div className="flex-1" />
        <div className="flex flex-col items-center gap-10">
          <div className="text-center flex flex-col gap-2">
            <h1 className="text-2xl font-bold">어떤 게임을 만들까요?</h1>
            <p className="text-gray-400 text-sm">원하는 모드를 선택하세요.</p>
          </div>

          <div className="flex gap-6 flex-wrap justify-center">
            {MODES.map((mode) => (
              <ModeCard key={mode.id} mode={mode} onClick={() => mode.route && navigate(mode.route)} />
            ))}
          </div>
        </div>
        <div className="flex-2" />
      </main>
    </div>
  )
}

function ModeCard({ mode, onClick }: { mode: GameMode; onClick: () => void }) {
  const { theme } = mode

  return (
    <div className="relative w-64">
      <button
        onClick={mode.available ? onClick : undefined}
        className="w-full rounded-2xl p-6 flex flex-col gap-4 text-left transition-all duration-200"
        style={{
          background: '#221638',
          border: `1px solid ${theme.border}`,
          boxShadow: `0 0 32px ${theme.glow}`,
          cursor: mode.available ? 'pointer' : 'default',
        }}
        onMouseEnter={e => {
          if (!mode.available) return
          const el = e.currentTarget
          el.style.transform = 'translateY(-4px)'
          el.style.borderColor = theme.border.replace('.35', '.6')
          el.style.boxShadow = `0 0 48px ${theme.glow.replace('.12', '.22').replace('.1)', '.18)')}`
        }}
        onMouseLeave={e => {
          const el = e.currentTarget
          el.style.transform = 'translateY(0)'
          el.style.borderColor = theme.border
          el.style.boxShadow = `0 0 32px ${theme.glow}`
        }}
      >
        <div className="flex items-center justify-between">
          <span className="text-4xl leading-none -ml-1">{mode.icon}</span>
          <span
            className="text-xs font-bold tracking-widest px-2 py-1 rounded-full"
            style={{ background: theme.accentBg, color: theme.accent }}
          >
            NEW
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="font-bold text-lg" style={{ color: '#F0EBFF' }}>{mode.title}</span>
          <span className="text-sm leading-relaxed break-keep" style={{ color: '#9B8AB0' }}>{mode.description}</span>
        </div>
        {mode.available && (
          <span className="text-sm font-medium mt-auto" style={{ color: theme.accent }}>
            시작하기 →
          </span>
        )}
      </button>

      {!mode.available && (
        <div className="absolute inset-0 rounded-2xl backdrop-blur-sm bg-gray-950/60 flex items-center justify-center">
          <span className="text-gray-300 text-sm font-semibold tracking-wide bg-gray-800/80 px-4 py-2 rounded-full border border-gray-700">
            🚧 개발 중
          </span>
        </div>
      )}
    </div>
  )
}
