import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MOCK, MOCK_GAME_ID } from '../dev/mock'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'

const MAX_CODE_BYTES = 50 * 1024 // 50KB

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

    # 랜덤 탐색
    return random.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])
`

function byteSize(str: string) {
  return new TextEncoder().encode(str).length
}

// ── Rules Modal ────────────────────────────────────────────────────────

function RulesModal({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      onClick={onClose}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Window */}
      <div
        className="relative z-10 bg-gray-800 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 shrink-0">
          <h2 className="font-bold text-lg">📋 배틀로얄 룰 & 코드 가이드</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white transition-colors text-xl leading-none"
          >
            ✕
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto px-6 py-5 flex flex-col gap-6 text-sm scrollbar-custom">

          {/* 개요 */}
          <Section title="🎮 게임 개요">
            <p className="text-gray-300 leading-relaxed">
              최대 100개의 AI 봇이 100×100 맵에서 경쟁합니다. 광물 채굴, 전투, 생존으로 점수를 쌓아 최고 점수를 기록하세요.
              게임은 최대 <b>200틱</b>이며, 봇이 1개 남거나 모든 광물이 소진되면 종료됩니다.
            </p>
          </Section>

          {/* action 함수 */}
          <Section title="⚙️ action 함수 구조">
            <p className="text-gray-400 mb-2">매 틱마다 엔진이 <code className="text-green-400">action(state)</code> 를 호출합니다. 문자열 하나를 반환하세요.</p>
            <CodeBlock>{`def action(state: dict) -> str:
    my       = state["my_bot"]       # 내 봇 정보
    vision   = state["vision"]       # 시야 정보
    zone     = state.get("zone_bounds", (0,0,99,99))
    bots     = state.get("other_bots", [])  # 시야 내 적 봇 목록
    return "STAY"`}
            </CodeBlock>
          </Section>

          {/* state 구조 */}
          <Section title="📦 state 객체 상세">
            <table className="w-full text-xs border-separate border-spacing-y-1">
              <thead>
                <tr className="text-gray-500 text-left">
                  <th className="w-44 pb-1">키</th>
                  <th>설명</th>
                </tr>
              </thead>
              <tbody className="text-gray-300">
                {[
                  ['my_bot.position', '[x, y] — 내 봇 현재 좌표'],
                  ['my_bot.energy', '현재 에너지 (0 이하이면 사망)'],
                  ['my_bot.score', '현재 누적 점수'],
                  ['my_bot.alive', 'True / False'],
                  ['vision.grid', '5×5 리스트. 중심(2,2)이 내 위치. 셀 값 ↓'],
                  ['vision.grid 셀 값', '"empty" / "mineral" / "mineral_rare" / "bot_enemy" / "bot_self" / "wall"'],
                  ['zone_bounds', '(min_x, min_y, max_x, max_y) — 안전 구역 범위'],
                  ['other_bots', '시야 내 적 봇 리스트: [{id, position, energy}]'],
                ].map(([k, v]) => (
                  <tr key={k} className="bg-gray-800/40 rounded">
                    <td className="px-2 py-1 rounded-l font-mono text-indigo-300">{k}</td>
                    <td className="px-2 py-1 rounded-r">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          {/* 액션 목록 */}
          <Section title="🕹️ 반환 가능한 액션">
            <div className="grid grid-cols-2 gap-2">
              {[
                ['MOVE_UP / DOWN / LEFT / RIGHT', '한 칸 이동 (에너지 -2)'],
                ['MINE', '인접 광물 채굴 시도 (에너지 -3)'],
                ['ATTACK_UP / DOWN / LEFT / RIGHT', '1칸 앞 공격 (에너지 -5, 피해 25)'],
                ['SHIELD', '이번 틱 공격 완전 방어 (에너지 -3)'],
                ['STAY', '제자리 대기 (에너지 -1)'],
              ].map(([action, desc]) => (
                <div key={action} className="bg-gray-800/50 rounded-lg px-3 py-2">
                  <p className="font-mono text-green-400 text-xs">{action}</p>
                  <p className="text-gray-400 text-xs mt-0.5">{desc}</p>
                </div>
              ))}
            </div>
          </Section>

          {/* 점수 체계 */}
          <Section title="🏆 점수 체계">
            <table className="w-full text-xs border-separate border-spacing-y-1">
              <tbody className="text-gray-300">
                {[
                  ['⛏️ 일반 광물 채굴', '+5점'],
                  ['💎 희귀 광물 채굴', '+20점'],
                  ['⚔️ 킬 (적 처치)', '+30점'],
                  ['🛡️ 방어 성공 (SHIELD)', '+10점'],
                  ['⏱️ 생존 틱', '매 틱 +0.1점'],
                  ['🥇 최장 생존 1위', '+100점 (게임 종료 시)'],
                  ['🥈 최장 생존 2위', '+50점'],
                  ['🥉 최장 생존 3위', '+25점'],
                ].map(([item, pts]) => (
                  <tr key={item} className="bg-gray-800/40">
                    <td className="px-2 py-1 rounded-l">{item}</td>
                    <td className="px-2 py-1 rounded-r text-right font-mono text-yellow-300 font-semibold">{pts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          {/* 자기장 */}
          <Section title="🌀 자기장 (Zone)">
            <p className="text-gray-300 leading-relaxed">
              76틱부터 자기장이 수축합니다. 안전 구역 밖에 있으면 매 틱 <b className="text-red-400">에너지 -3</b>.
              151틱 이후 수축 속도가 2배로 빨라집니다. <code className="text-indigo-300">zone_bounds</code>를 확인해 항상 안전 구역 안에 있으세요.
            </p>
          </Section>

        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-semibold text-white text-sm">{title}</h3>
      {children}
    </div>
  )
}

function CodeBlock({ children }: { children: React.ReactNode }) {
  return (
    <pre className="bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-xs text-green-300 font-mono overflow-x-auto whitespace-pre scrollbar-custom">
      {children}
    </pre>
  )
}

export default function GameNewPage() {
  const { token } = useAuth()
  const navigate = useNavigate()

  const [botId, setBotId] = useState('')
  const [code, setCode] = useState(DEFAULT_CODE)
  const [isPublic, setIsPublic] = useState(true)
  const [fillWithAi, setFillWithAi] = useState(true)
  const [minBots, setMinBots] = useState<number | ''>(4)
  const [tickInterval, setTickInterval] = useState(0.05)
  const [seed, setSeed] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [showRules, setShowRules] = useState(false)

  const codeBytes = byteSize(code)
  const codeOverLimit = codeBytes > MAX_CODE_BYTES
  const canSubmit = !submitting && code.trim().length > 0 && !codeOverLimit

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError('')

    // ── mock mode ──────────────────────────────────────────────
    if (MOCK) {
      await new Promise((r) => setTimeout(r, 600))
      navigate(`/games/${MOCK_GAME_ID}/watch`)
      return
    }
    // ──────────────────────────────────────────────────────────

    try {
      const body: Record<string, unknown> = {
        bots: [{ bot_id: botId.trim() || 'my_bot', code, is_public: isPublic }],
        tick_interval: tickInterval,
        fill_with_ai: fillWithAi,
        min_bots: minBots || 2,
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
      {showRules && <RulesModal onClose={() => setShowRules(false)} />}
      {/* 헤더 */}
      <header className="sticky top-0 z-20 h-14 border-b border-gray-800 bg-gray-950 px-6 flex items-center gap-3">
        <button
          onClick={() => navigate('/games/new')}
          className="text-gray-400 hover:text-white text-sm transition-colors"
        >
          ◀ 모드 선택
        </button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">새 게임 만들기</span>
        <button
          type="button"
          onClick={() => setShowRules(true)}
          className="ml-auto text-xs font-medium text-indigo-400 hover:text-indigo-300 border border-indigo-500/40 hover:border-indigo-400 rounded-lg px-3 py-1.5 transition-colors"
        >
          📋 룰 확인
        </button>
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
          <section className="bg-gray-800 border border-gray-700 rounded-xl px-5 py-4 flex flex-col gap-4">
            <h3 className="text-sm font-medium text-gray-300">게임 옵션</h3>

            {/* 봇 코드 공개 여부 */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white">봇 코드 공개</p>
                <p className="text-xs text-gray-500">다른 유저가 리더보드에서 내 봇 코드를 볼 수 있습니다</p>
              </div>
              <button
                type="button"
                onClick={() => setIsPublic((v) => !v)}
                className={`relative w-11 h-6 rounded-full transition-colors ${
                  isPublic ? 'bg-indigo-600' : 'bg-gray-700'
                }`}
              >
                <span
                  className={`absolute top-1 left-0 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                    isPublic ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>

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
                  className={`absolute top-1 left-0 w-4 h-4 bg-white rounded-full shadow transition-transform ${
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
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                value={minBots}
                onChange={(e) => {
                  const raw = e.target.value.replace(/[^0-9]/g, '')
                  if (raw === '') { setMinBots(''); return }
                  setMinBots(Math.min(100, Number(raw)))
                }}
                onBlur={() => setMinBots((v) => (v === '' || v < 2 ? 2 : v))}
                className="bg-gray-600 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-indigo-500 w-16 text-center"
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
                className="bg-gray-600 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-indigo-500 w-24 text-center placeholder-gray-400"
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
