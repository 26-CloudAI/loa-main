import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MOCK, MOCK_GAME_ID } from '../dev/mock'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080'

const MAX_CODE_BYTES = 50 * 1024

const DEFAULT_CODE = `import random

def action(state: dict) -> str:
    my      = state["my_bot"]
    pos_x, pos_y = my["position"]
    energy  = my["energy"]
    grid    = state["vision"]["grid"]
    zone_bounds = state.get("zone_bounds", (0, 0, 99, 99))
    min_x, min_y, max_x, max_y = zone_bounds

    # 존 밖이면 중심으로 이동
    in_zone = min_x <= pos_x <= max_x and min_y <= pos_y <= max_y
    if not in_zone:
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        dx, dy = cx - pos_x, cy - pos_y
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    # 에너지 위험 시 방어
    if energy <= 20:
        return "SHIELD"

    # 인접 적 공격
    dirs = [(0,-1,"ATTACK_UP"), (0,1,"ATTACK_DOWN"), (-1,0,"ATTACK_LEFT"), (1,0,"ATTACK_RIGHT")]
    for dx, dy, atk in dirs:
        if grid[2 + dy][2 + dx] == "bot_enemy":
            return atk

    # 인접 광물 채굴
    for dx, dy, _ in dirs:
        cell = grid[2 + dy][2 + dx]
        if cell in ("mineral", "mineral_rare"):
            return "MINE"

    # 시야 내 광물로 이동
    for row in range(5):
        for col in range(5):
            if grid[row][col] in ("mineral", "mineral_rare"):
                dx, dy = col - 2, row - 2
                if abs(dx) >= abs(dy):
                    return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
                return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    return random.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])
`

function byteSize(str: string) {
  return new TextEncoder().encode(str).length
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-semibold text-white text-sm">{title}</h3>
      {children}
    </div>
  )
}

function BossInfoBanner() {
  return (
    <div className="bg-red-950/40 border border-red-800/60 rounded-xl px-5 py-4 flex gap-4 items-start">
      <span className="text-3xl shrink-0">👾</span>
      <div className="flex flex-col gap-1">
        <p className="font-bold text-red-300">AI 보스 — DQN 강화학습 봇</p>
        <p className="text-sm text-gray-400 leading-relaxed">
          수천 판의 게임 경험으로 훈련된 보스입니다. 자기장 회피, 광물 채굴, 전투 판단을
          신경망으로 결정하며 매 게임마다 학습해 점점 강해집니다.
          당신의 봇이 이길 수 있을지 도전해보세요.
        </p>
      </div>
    </div>
  )
}

export default function BossBattlePage() {
  const { token } = useAuth()
  const navigate = useNavigate()

  const [botId, setBotId] = useState('')
  const [code, setCode] = useState(DEFAULT_CODE)
  const [tickInterval, setTickInterval] = useState(0.05)
  const [seed, setSeed] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const codeBytes = byteSize(code)
  const codeOverLimit = codeBytes > MAX_CODE_BYTES
  const canSubmit = !submitting && code.trim().length > 0 && !codeOverLimit

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError('')

    if (MOCK) {
      await new Promise((r) => setTimeout(r, 600))
      navigate(`/games/${MOCK_GAME_ID}/watch`)
      return
    }

    try {
      const body: Record<string, unknown> = {
        bots: [{ bot_id: botId.trim() || 'challenger', code }],
        tick_interval: tickInterval,
        mode: 'boss',
        seed: seed !== '' ? parseInt(seed, 10) : null,
      }

      const res = await fetch(`${API_BASE}/api/games`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail ?? `서버 오류 (${res.status})`)
      }

      const game = await res.json()
      navigate(`/games/${game.game_id}/watch`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '게임 생성에 실패했습니다.')
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="sticky top-0 z-20 h-14 border-b border-gray-800 bg-gray-950 px-6 flex items-center gap-3">
        <button
          onClick={() => navigate('/games/new')}
          className="text-gray-400 hover:text-white text-sm transition-colors"
        >
          ◀ 모드 선택
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">👾 보스전</span>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8">
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">

          <BossInfoBanner />

          {/* 봇 이름 */}
          <Section title="내 봇 이름">
            <input
              type="text"
              value={botId}
              onChange={(e) => setBotId(e.target.value)}
              placeholder="challenger"
              maxLength={32}
              className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-red-500 placeholder-gray-600 w-64"
            />
          </Section>

          {/* 코드 에디터 */}
          <Section title="봇 코드 (Python)">
            <div className="flex justify-end">
              <span className={`text-xs font-mono ${codeOverLimit ? 'text-red-400' : 'text-gray-500'}`}>
                {(codeBytes / 1024).toFixed(1)} KB / 50 KB{codeOverLimit && ' — 초과'}
              </span>
            </div>
            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              spellCheck={false}
              rows={20}
              className={`bg-gray-900 text-green-300 font-mono text-sm rounded-lg px-4 py-3 outline-none resize-y border ${
                codeOverLimit
                  ? 'border-red-500 focus:ring-2 focus:ring-red-500'
                  : 'border-gray-700 focus:ring-2 focus:ring-red-500'
              } w-full`}
            />
            {codeOverLimit && (
              <p className="text-red-400 text-xs">코드가 50KB를 초과합니다. 줄여주세요.</p>
            )}
          </Section>

          {/* 게임 옵션 */}
          <section className="bg-gray-800 border border-gray-700 rounded-xl px-5 py-4 flex flex-col gap-4">
            <h3 className="text-sm font-medium text-gray-300">게임 옵션</h3>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-white">틱 간격 (속도)</p>
                  <p className="text-xs text-gray-500">값이 작을수록 빠름</p>
                </div>
                <span className="text-sm text-red-400 font-mono">{tickInterval.toFixed(2)}s</span>
              </div>
              <input
                type="range"
                min={0.01}
                max={1.0}
                step={0.01}
                value={tickInterval}
                onChange={(e) => setTickInterval(parseFloat(e.target.value))}
                className="w-full accent-red-500"
              />
              <div className="flex justify-between text-xs text-gray-600">
                <span>0.01s (빠름)</span>
                <span>1.0s (느림)</span>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white">시드 (재현용, 선택)</p>
                <p className="text-xs text-gray-500">비우면 랜덤</p>
              </div>
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                placeholder="랜덤"
                className="bg-gray-600 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-red-500 w-24 text-center placeholder-gray-400"
              />
            </div>
          </section>

          {error && (
            <div className="text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="bg-red-700 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-3 transition-colors"
          >
            {submitting ? '도전 중...' : '보스에게 도전!'}
          </button>

        </form>
      </main>
    </div>
  )
}
