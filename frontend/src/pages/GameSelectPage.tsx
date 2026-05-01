import React from 'react'
import { useNavigate } from 'react-router-dom'

interface GameMode {
  id: string
  title: string
  description: React.ReactNode
  icon: string
  available: boolean
  route?: string
}

const MODES: GameMode[] = [
  {
    id: 'battle-royale',
    title: '배틀로얄',
    description: 'AI 봇을 코딩해 맵에서 싸워라. 채굴·전투·생존으로 최고 점수를 노려라.',
    icon: '⚔️',
    available: true,
    route: '/games/new/battle-royale',
  },
  {
    id: 'boss-battle',
    title: '보스전',
    description: <>강화학습으로 훈련된 보스 봇과 1대1로 맞붙어라. <span className="whitespace-nowrap">이길 수 있겠어?</span></>,
    icon: '👾',
    available: true,
    route: '/games/new/boss-battle',
  },
  {
    id: 'mock-stock',
    title: '모의주식',
    description: '실시간 시세를 예측하는 트레이딩 AI를 만들어 수익률을 겨뤄라.',
    icon: '📈',
    available: true,
    route: '/games/new/mock-stocks',
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
          ◀ 게임 목록
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">게임 모드 선택</span>
      </header>

      <main className="flex flex-1 flex-col items-center justify-center gap-10 px-6 py-12">
        <div className="text-center flex flex-col gap-2">
          <h1 className="text-2xl font-bold">어떤 게임을 만들까요?</h1>
          <p className="text-gray-400 text-sm">원하는 모드를 선택하세요.</p>
        </div>

        <div className="flex gap-6 flex-wrap justify-center">
          {MODES.map((mode) => (
            <ModeCard key={mode.id} mode={mode} onClick={() => mode.route && navigate(mode.route)} />
          ))}
        </div>
      </main>
    </div>
  )
}

function ModeCard({ mode, onClick }: { mode: GameMode; onClick: () => void }) {
  return (
    <div className="relative w-64">
      {/* Card */}
      <button
        onClick={mode.available ? onClick : undefined}
        className={[
          'w-full rounded-2xl border p-6 flex flex-col gap-4 text-left transition-all',
          mode.available
            ? 'border-gray-600 bg-gray-800 hover:border-indigo-500 hover:bg-gray-700 cursor-pointer'
            : 'border-gray-700 bg-gray-800 cursor-default',
        ].join(' ')}
      >
        <span className="text-4xl leading-none -ml-1">{mode.icon}</span>
        <div className="flex flex-col gap-1">
          <span className="font-bold text-lg">{mode.title}</span>
          <span className="text-gray-400 text-sm leading-relaxed">{mode.description}</span>
        </div>
        {mode.available && (
          <span className="text-indigo-400 text-sm font-medium mt-auto">시작하기 →</span>
        )}
      </button>

      {/* Unavailable overlay */}
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
