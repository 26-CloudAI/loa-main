import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MOCK, MOCK_GAME_ID } from '../dev/mock'
import BotCodeInput from '../components/BotCodeInput'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'

const MAX_CODE_BYTES = 50 * 1024
const MAX_BOTS = 3

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

type Difficulty = '하' | '중' | '상'

const DIFFICULTY_INFO: Record<Difficulty, { label: string; sub: string; desc: string; color: string; border: string; selected: string }> = {
  하: {
    label: '하',
    sub: '쉬움',
    desc: '광물 채굴·생존 중심 룰베이스 보스.\n인접 공격만 하며 추적하지 않습니다.',
    color: 'text-green-300',
    border: 'border-green-700',
    selected: 'border-green-400 bg-green-950/40',
  },
  중: {
    label: '중',
    sub: '보통',
    desc: '채굴·전투 균형형 룰베이스 보스.\n시야 내 적을 적극 추적합니다.',
    color: 'text-yellow-300',
    border: 'border-yellow-700',
    selected: 'border-yellow-400 bg-yellow-950/40',
  },
  상: {
    label: '상',
    sub: '어려움',
    desc: '수천 판 학습한 DQN 강화학습 보스.\n매일 유저 코드를 학습해 점점 강해집니다.',
    color: 'text-red-300',
    border: 'border-red-700',
    selected: 'border-red-400 bg-red-950/40',
  },
}

function DifficultySelector({
  value,
  onChange,
}: {
  value: Difficulty
  onChange: (d: Difficulty) => void
}) {
  return (
    <div className="flex gap-3">
      {(Object.keys(DIFFICULTY_INFO) as Difficulty[]).map((d) => {
        const info = DIFFICULTY_INFO[d]
        const isSelected = value === d
        return (
          <button
            key={d}
            type="button"
            onClick={() => onChange(d)}
            className={[
              'flex-1 rounded-xl border px-3 py-3 text-left transition-all',
              isSelected ? info.selected : 'border-gray-700 bg-gray-800 hover:border-gray-500',
            ].join(' ')}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className={`font-bold text-base ${isSelected ? info.color : 'text-gray-300'}`}>
                {info.label}
              </span>
              <span className={`text-xs ${isSelected ? info.color : 'text-gray-500'}`}>
                {info.sub}
              </span>
            </div>
            <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-line">{info.desc}</p>
          </button>
        )
      })}
    </div>
  )
}

function BossInfoBanner({ difficulty }: { difficulty: Difficulty }) {
  const info = DIFFICULTY_INFO[difficulty]
  return (
    <div className="rounded-xl px-5 py-4 flex gap-4 items-start" style={{ background: 'rgba(232,51,74,.1)', border: '1px solid rgba(232,51,74,.35)' }}>
      <span className="text-3xl shrink-0">👾</span>
      <div className="flex flex-col gap-1">
        <p className={`font-bold ${info.color}`}>
          AI 보스 ({info.label} — {info.sub})
        </p>
        <p className="text-sm text-gray-400 leading-relaxed">{info.desc}</p>
      </div>
    </div>
  )
}

type BotEntry = { id: string; code: string }

function BotCard({
  index,
  total,
  bot,
  onUpdate,
  onRemove,
}: {
  index: number
  total: number
  bot: BotEntry
  onUpdate: (field: keyof BotEntry, value: string) => void
  onRemove: () => void
}) {
  const codeBytes = byteSize(bot.code)
  const overLimit = codeBytes > MAX_CODE_BYTES

  return (
    <div className="border border-gray-700 rounded-xl overflow-hidden">
      {/* 카드 헤더 */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-red-400 bg-red-950/50 border border-red-800/60 rounded px-2 py-0.5">
            봇 {index + 1}
          </span>
          <input
            type="text"
            value={bot.id}
            onChange={(e) => onUpdate('id', e.target.value)}
            placeholder={index === 0 ? 'challenger' : `challenger_${index + 1}`}
            maxLength={32}
            className="bg-transparent text-white text-sm outline-none placeholder-gray-500 w-40"
          />
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-xs font-mono ${overLimit ? 'text-red-400' : 'text-gray-500'}`}>
            {(codeBytes / 1024).toFixed(1)} KB / 50 KB
          </span>
          {total > 1 && (
            <button
              type="button"
              onClick={onRemove}
              className="text-gray-500 hover:text-red-400 transition-colors text-lg leading-none"
              title="봇 제거"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* 코드 에디터 */}
      <div className="p-3 bg-gray-900">
        <BotCodeInput
          value={bot.code}
          onChange={(v) => onUpdate('code', v)}
          hasError={overLimit}
          accentColor="red"
        />
        {overLimit && (
          <p className="text-red-400 text-xs mt-1">코드가 50KB를 초과합니다. 줄여주세요.</p>
        )}
      </div>
    </div>
  )
}

export default function BossBattlePage() {
  const { token } = useAuth()
  const navigate = useNavigate()

  const [gameName, setGameName] = useState('')
  const [bots, setBots] = useState<BotEntry[]>([{ id: '', code: DEFAULT_CODE }])
  const [tickInterval, setTickInterval] = useState(0.05)
  const [seed, setSeed] = useState('')
  const [difficulty, setDifficulty] = useState<Difficulty>('중')
  const [isPublic, setIsPublic] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  function addBot() {
    if (bots.length < MAX_BOTS) {
      setBots((prev) => [...prev, { id: '', code: DEFAULT_CODE }])
    }
  }

  function removeBot(idx: number) {
    setBots((prev) => prev.filter((_, i) => i !== idx))
  }

  function updateBot(idx: number, field: keyof BotEntry, value: string) {
    setBots((prev) => prev.map((b, i) => (i === idx ? { ...b, [field]: value } : b)))
  }

  const anyOverLimit = bots.some((b) => byteSize(b.code) > MAX_CODE_BYTES)
  const canSubmit = !submitting && bots.every((b) => b.code.trim().length > 0) && !anyOverLimit

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
        bots: bots.map((b, i) => ({
          bot_id: b.id.trim() || (i === 0 ? 'challenger' : `challenger_${i + 1}`),
          code: b.code,
          is_public: isPublic,
        })),
        tick_interval: tickInterval,
        mode: 'boss',
        difficulty,
        seed: seed !== '' ? parseInt(seed, 10) : null,
        name: gameName.trim() || undefined,
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

          <BossInfoBanner difficulty={difficulty} />

          {/* 난이도 선택 */}
          <Section title="난이도">
            <DifficultySelector value={difficulty} onChange={setDifficulty} />
          </Section>

          {/* 게임 이름 */}
          <div className="flex flex-col gap-2">
            <h3 className="font-semibold text-white text-sm">
              게임 이름 <span className="text-gray-500 font-normal">(비우면 자동 설정됨)</span>
            </h3>
            <input
              type="text"
              value={gameName}
              onChange={(e) => setGameName(e.target.value)}
              placeholder="새 보스전 1"
              maxLength={40}
              className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-red-500 placeholder-gray-600 w-72"
            />
          </div>

          {/* 봇 목록 */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-white text-sm">
                내 봇
                <span className="text-gray-500 font-normal ml-2">
                  ({bots.length}/{MAX_BOTS}) — 팀으로 보스에 도전
                </span>
              </h3>
            </div>

            {bots.map((bot, idx) => (
              <BotCard
                key={idx}
                index={idx}
                total={bots.length}
                bot={bot}
                onUpdate={(field, value) => updateBot(idx, field, value)}
                onRemove={() => removeBot(idx)}
              />
            ))}

            {bots.length < MAX_BOTS && (
              <button
                type="button"
                onClick={addBot}
                className="flex items-center justify-center gap-2 border border-dashed border-gray-600 hover:border-red-600 rounded-xl py-3 text-sm text-gray-500 hover:text-red-400 transition-colors"
              >
                <span className="text-lg leading-none">+</span>
                봇 추가 ({bots.length}/{MAX_BOTS})
              </button>
            )}
          </div>

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
                className={`relative w-11 h-6 rounded-full transition-colors ${isPublic ? 'bg-[#E8334A]' : 'bg-gray-700'}`}
              >
                <span className={`absolute top-1 left-0 w-4 h-4 bg-white rounded-full shadow transition-transform ${isPublic ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-white">틱 간격 (속도)</p>
                  <p className="text-xs text-gray-500">값이 작을수록 빠름</p>
                </div>
                <span className="text-sm font-mono" style={{ color: '#E8334A' }}>{tickInterval.toFixed(2)}s</span>
              </div>
              <input
                type="range"
                min={0.01}
                max={1.0}
                step={0.01}
                value={tickInterval}
                onChange={(e) => setTickInterval(parseFloat(e.target.value))}
                className="w-full accent-[#E8334A]"
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
                type="text"
                inputMode="numeric"
                value={seed}
                onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ''))}
                placeholder="랜덤"
                className="bg-gray-600 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-red-500 w-20 text-center placeholder-gray-400"
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
            className="bg-[#E8334A] hover:bg-[#D42B42] disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-3 transition-colors"
          >
            {submitting
              ? '도전 중...'
              : bots.length > 1
                ? `${bots.length}봇 팀으로 보스에 도전!`
                : '보스에게 도전!'}
          </button>

        </form>
      </main>
    </div>
  )
}
