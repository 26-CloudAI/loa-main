import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080'

const MAX_CODE_BYTES = 50 * 1024 // 50KB

const DEFAULT_CODE = `def action(state: dict) -> str:
    """
    state 구조:
      - state["tick"]: 현재 틱 (int)
      - state["my_bot"]["position"]: [x, y]
      - state["my_bot"]["energy"]: 현재 에너지
      - state["my_bot"]["score"]: 현재 점수
      - state["vision"]["grid"]: 5x5 시야 배열
        ("empty", "mineral", "mineral_rare", "bot_enemy", "ME", "wall", "zone")
      - state["zone_boundary"]: 생존 구역 경계
      - state["leaderboard"]: [{"rank", "id", "score"}, ...]

    반환값 (str):
      "STAY", "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT",
      "MINE", "ATTACK_UP", "ATTACK_DOWN", "ATTACK_LEFT", "ATTACK_RIGHT", "SHIELD"
    """
    return "STAY"
`

function byteSize(str: string) {
  return new TextEncoder().encode(str).length
}

export default function GameNewPage() {
  const navigate = useNavigate()

  const [botId, setBotId] = useState('')
  const [code, setCode] = useState(DEFAULT_CODE)
  const [fillWithAi, setFillWithAi] = useState(true)
  const [minBots, setMinBots] = useState(4)
  const [tickInterval, setTickInterval] = useState(0.05)
  const [seed, setSeed] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const codeBytes = byteSize(code)
  const codeOverLimit = codeBytes > MAX_CODE_BYTES
  const canSubmit = !submitting && code.trim().length > 0 && !codeOverLimit

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError('')

    try {
      const body: Record<string, unknown> = {
        bots: [{ bot_id: botId.trim() || 'my_bot', code }],
        tick_interval: tickInterval,
        fill_with_ai: fillWithAi,
        min_bots: minBots,
        seed: seed !== '' ? parseInt(seed, 10) : null,
      }

      const res = await fetch(`${API_BASE}/api/games`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
    <div className="min-h-screen bg-gray-950 text-white">
      {/* 헤더 */}
      <header className="border-b border-gray-800 px-6 py-3 flex items-center gap-3">
        <button
          onClick={() => navigate('/games')}
          className="text-gray-400 hover:text-white text-sm transition-colors"
        >
          ◀ 게임 목록
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">새 게임 만들기</span>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8">
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">

          {/* 봇 이름 */}
          <section className="flex flex-col gap-2">
            <label className="text-sm font-medium text-gray-300">
              봇 이름 <span className="text-gray-500 font-normal">(게임 내 표시 ID)</span>
            </label>
            <input
              type="text"
              value={botId}
              onChange={(e) => setBotId(e.target.value)}
              placeholder="my_bot"
              maxLength={32}
              className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-600 w-64"
            />
          </section>

          {/* 코드 에디터 */}
          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-gray-300">봇 코드 (Python)</label>
              <span
                className={`text-xs font-mono ${
                  codeOverLimit ? 'text-red-400' : 'text-gray-500'
                }`}
              >
                {(codeBytes / 1024).toFixed(1)} KB / 50 KB
                {codeOverLimit && ' — 초과'}
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
                  : 'border-gray-700 focus:ring-2 focus:ring-indigo-500'
              } w-full`}
            />
            {codeOverLimit && (
              <p className="text-red-400 text-xs">코드가 50KB를 초과합니다. 줄여주세요.</p>
            )}
          </section>

          {/* 게임 옵션 */}
          <section className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4 flex flex-col gap-4">
            <h3 className="text-sm font-medium text-gray-300">게임 옵션</h3>

            {/* AI 채우기 */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white">AI로 빈 슬롯 채우기</p>
                <p className="text-xs text-gray-500">내 봇 외 나머지를 AI 봇으로 채웁니다</p>
              </div>
              <button
                type="button"
                onClick={() => setFillWithAi((v) => !v)}
                className={`relative w-11 h-6 rounded-full transition-colors ${
                  fillWithAi ? 'bg-indigo-600' : 'bg-gray-700'
                }`}
              >
                <span
                  className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                    fillWithAi ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

            {/* 최소 봇 수 */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white">최소 봇 수</p>
                <p className="text-xs text-gray-500">2 ~ 100</p>
              </div>
              <input
                type="number"
                min={2}
                max={100}
                value={minBots}
                onChange={(e) => setMinBots(Math.min(100, Math.max(2, parseInt(e.target.value) || 2)))}
                className="bg-gray-800 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-indigo-500 w-20 text-center"
              />
            </div>

            {/* 틱 간격 */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-white">틱 간격 (속도)</p>
                  <p className="text-xs text-gray-500">값이 작을수록 빠름</p>
                </div>
                <span className="text-sm text-indigo-400 font-mono">{tickInterval.toFixed(2)}s</span>
              </div>
              <input
                type="range"
                min={0.01}
                max={1.0}
                step={0.01}
                value={tickInterval}
                onChange={(e) => setTickInterval(parseFloat(e.target.value))}
                className="w-full accent-indigo-500"
              />
              <div className="flex justify-between text-xs text-gray-600">
                <span>0.01s (빠름)</span>
                <span>1.0s (느림)</span>
              </div>
            </div>

            {/* 시드 */}
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
                className="bg-gray-800 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-indigo-500 w-24 text-center placeholder-gray-600"
              />
            </div>
          </section>

          {/* 에러 */}
          {error && (
            <div className="text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">
              {error}
            </div>
          )}

          {/* 제출 버튼 */}
          <button
            type="submit"
            disabled={!canSubmit}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-3 transition-colors"
          >
            {submitting ? '게임 생성 중...' : '게임 시작'}
          </button>

        </form>
      </main>
    </div>
  )
}
