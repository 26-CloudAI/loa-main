import React, { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { MOCK } from '../dev/mock'
import BotCodeInput from '../components/BotCodeInput'
import { BR2_API_BASE } from '../br2'

// BR2(연속 2D 배틀로얄) 백엔드. VITE_API_BASE(.../battleroyale) → /battleroyale2 파생.
const API_BASE = BR2_API_BASE

const MAX_CODE_BYTES = 50 * 1024 // 50KB

// 유저 봇 기본 코드. 백엔드 BattleRoyale2/bots/user_template.py 와 동일 구조.
// exec 네임스페이스에 BattleRoyale2DBot 이 주입되므로 import 불필요. get_action 은 action dict 반환.
const DEFAULT_CODE = `import math

# class Bot(BattleRoyale2DBot) 을 정의하세요. get_action(state) 가 매 결정 틱(0.1s) 호출됩니다.
# 허용 import: math, random, json, collections, heapq, itertools
class Bot(BattleRoyale2DBot):
    def choose_spawn(self, map_info):
        # 매치 시작 시 1회. 희귀 코인/상자 클러스터 근처에서 시작 (None 이면 랜덤)
        rc = map_info.get("rare_clusters") or map_info.get("chest_clusters") or []
        if rc:
            return (rc[0][0], rc[0][1])
        return None

    def get_action(self, state):
        me = state["self"]
        x, y = me["pos"]
        vision = state["vision"]
        zone = state.get("zone", {})
        action = {
            "move_dir": [0.0, 0.0], "aim_dir": [1.0, 0.0],
            "attack": False, "guard": False, "dash": False,
            "pickup": False, "use_potion": False,
        }

        # 1) HP 낮고 포션 보유 → 사용
        if me.get("has_potion") and me["hp"] < 80:
            action["use_potion"] = True

        # 2) 자기장 밖이면 중심으로 이동
        if zone.get("active") and zone.get("damage", 0) > 0:
            cx, cy = zone["center"]
            dx, dy = cx - x, cy - y
            d = math.hypot(dx, dy)
            if d > zone.get("radius", 0):
                action["move_dir"] = [dx / d, dy / d]
                action["aim_dir"] = [dx / d, dy / d]
                return action

        # 3) 가까운 적 → 사거리(60) 안이면 공격, 아니면 접근
        enemies = vision.get("enemies", [])
        if enemies:
            e = min(enemies, key=lambda en: (en["pos"][0]-x)**2 + (en["pos"][1]-y)**2)
            dx, dy = e["pos"][0]-x, e["pos"][1]-y
            d = math.hypot(dx, dy) or 1.0
            action["aim_dir"] = [dx/d, dy/d]
            if d <= 60:
                action["attack"] = True
            else:
                action["move_dir"] = [dx/d, dy/d]
            return action

        # 4) 코인 채집 (희귀 우선)
        nodes = vision.get("nodes", [])
        if nodes:
            rare = [n for n in nodes if n.get("rare")]
            pool = rare if rare else nodes
            n = min(pool, key=lambda nd: (nd["pos"][0]-x)**2 + (nd["pos"][1]-y)**2)
            dx, dy = n["pos"][0]-x, n["pos"][1]-y
            d = math.hypot(dx, dy) or 1.0
            action["move_dir"] = [dx/d, dy/d]
            action["aim_dir"] = [dx/d, dy/d]

        return action
`

function byteSize(str: string) {
  return new TextEncoder().encode(str).length
}

// ── Rules Modal (BR2) ───────────────────────────────────────────────────

function RulesModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative z-10 bg-gray-800 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 shrink-0">
          <h2 className="font-bold text-lg">📋 배틀로얄 2D 룰 & 코드 가이드</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors text-xl leading-none">✕</button>
        </div>

        <div className="overflow-y-auto px-6 py-5 flex flex-col gap-6 text-sm scrollbar-custom">
          <Section title="🎮 게임 개요">
            <p className="text-gray-300 leading-relaxed">
              연속 2D 맵(3000×3000)에서 봇들이 경쟁합니다. 코인·아이템 파밍, 근접/원거리 전투, 자기장 생존으로 점수를 쌓으세요.
              <b> 한 목숨</b>이며(리스폰 없음), 매치는 최대 <b>180초</b>, 마지막 1명이 남으면 종료됩니다.
            </p>
          </Section>

          <Section title="⚙️ Bot 클래스 구조">
            <p className="text-gray-400 mb-2"><code className="text-green-400">class Bot(BattleRoyale2DBot)</code> 를 정의하면 매 결정 틱(100ms)마다 <code className="text-green-400">get_action(state)</code> 가 호출됩니다. action <b>딕셔너리</b>를 반환하세요.</p>
            <CodeBlock>{`class Bot(BattleRoyale2DBot):
    def choose_spawn(self, map_info):   # 매치 시작 1회 (선택)
        return None                      # (x, y) 또는 None(랜덤)

    def get_action(self, state):
        me = state["self"]
        return {
            "move_dir": [0.0, 0.0],   # 이동 방향(길이 0~1=속도비율)
            "aim_dir":  [1.0, 0.0],   # 조준/바라보는 방향
            "attack": False, "guard": False, "dash": False,
            "pickup": False, "use_potion": False,
        }`}</CodeBlock>
            <p className="text-gray-500 text-xs mt-1">허용 import: <code className="text-indigo-300">math, random, json, collections, heapq, itertools</code></p>
          </Section>

          <Section title="📦 state 객체 상세">
            <table className="w-full text-xs border-separate border-spacing-y-1">
              <thead>
                <tr className="text-gray-500 text-left"><th className="w-52 pb-1">키</th><th>설명</th></tr>
              </thead>
              <tbody className="text-gray-300">
                {[
                  ['self.pos', '[x, y] — 내 봇 좌표'],
                  ['self.hp / max_hp', '체력 / 최대체력(200)'],
                  ['self.atk / def / speed', '공격력 / 방어력 / 이동속도'],
                  ['self.attack_cd / dash_cd / guard_cd', '각 쿨다운 잔여(초). 0이면 사용 가능'],
                  ['self.has_potion / has_ranged', '포션 보유 / 원거리 무기 보유 여부'],
                  ['self.guarding', '현재 가드 중 여부'],
                  ['vision.enemies', '시야 내 적: [{id, pos, hp, guarding}]'],
                  ['vision.nodes', '시야 내 코인: [{pos, rare}]'],
                  ['vision.items', '시야 내 드롭 아이템: [{pos, type}]'],
                  ['vision.chests', '시야 내 상자: [{pos}]'],
                  ['vision.projectiles', '시야 내 투사체: [{pos, vel, owner_id}]'],
                  ['zone', '{active, center:[x,y], radius, damage, phase}'],
                  ['leaderboard', '상위 3명: [{id, score}]'],
                ].map(([k, v]) => (
                  <tr key={k} className="bg-gray-800/40 rounded">
                    <td className="px-2 py-1 rounded-l font-mono text-indigo-300">{k}</td>
                    <td className="px-2 py-1 rounded-r">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-gray-500 text-xs mt-1">시야 반경 200px. 그 안의 객체만 vision 에 들어옵니다.</p>
          </Section>

          <Section title="🕹️ action 딕셔너리">
            <div className="grid grid-cols-2 gap-2">
              {[
                ['move_dir [x,y]', '이동 방향 벡터. 길이 0~1 = 속도비율'],
                ['aim_dir [x,y]', '조준/정면 방향 단위벡터 (공격·가드 기준)'],
                ['attack', '근접 부채꼴(60px,90°) 또는 원거리 발사(보유 시). 쿨다운 0.5/0.7s'],
                ['guard', '1초 가드 발동(쿨10s). 정면 ±60° 100% 차단 + 공격자 1초 경직'],
                ['dash', '0.2초 순간이동(600px/s). 쿨다운 5s'],
                ['pickup', '인접 상자 열기 (1초 유지)'],
                ['use_potion', '보유 포션 사용 (HP +50, 즉시)'],
              ].map(([a, desc]) => (
                <div key={a} className="bg-gray-800/50 rounded-lg px-3 py-2">
                  <p className="font-mono text-green-400 text-xs">{a}</p>
                  <p className="text-gray-400 text-xs mt-0.5">{desc}</p>
                </div>
              ))}
            </div>
          </Section>

          <Section title="🏆 점수 체계">
            <table className="w-full text-xs border-separate border-spacing-y-1">
              <tbody className="text-gray-300">
                {[
                  ['🪙 일반 코인', '+5점'],
                  ['💎 희귀 코인', '+20점'],
                  ['⚔️ 적 처치', '+100점'],
                  ['🛡️ 가드 성공', '+10점'],
                  ['⏱️ 생존 1초', '+0.1점'],
                  ['🥇 최종 생존 1위', '+100점'],
                  ['🥈 2위 / 🥉 3위', '+50 / +25점'],
                ].map(([item, pts]) => (
                  <tr key={item} className="bg-gray-800/40">
                    <td className="px-2 py-1 rounded-l">{item}</td>
                    <td className="px-2 py-1 rounded-r text-right font-mono text-yellow-300 font-semibold">{pts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="🌀 자기장 (배그 스타일)">
            <p className="text-gray-300 leading-relaxed">
              0~60초는 안전. 이후 60~100s / 100~140s / 140~180s 3단계로 중심이 옮겨가며 좁아집니다.
              자기장 밖은 단계별 <b className="text-red-400">2 → 3 → 5 dmg/s</b>. <code className="text-indigo-300">state.zone</code> 의 center/radius 로 항상 안전권 안에 있으세요.
              <code className="text-indigo-300"> map_info</code> 로 첫 자기장(zone1) 위치를 미리 알 수 있어 스폰 전략에 활용 가능합니다.
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
  const location = useLocation()

  const [gameName, setGameName] = useState('')
  const [botId, setBotId] = useState('')
  const [code, setCode] = useState<string>(
    (location.state as { templateCode?: string } | null)?.templateCode ?? DEFAULT_CODE
  )
  const [isPublic, setIsPublic] = useState(true)
  const [botCount, setBotCount] = useState(4)   // 총 봇 수 (내 봇 1 + AI 채움)
  const [seed, setSeed] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [showRules, setShowRules] = useState(false)

  const codeBytes = byteSize(code)
  const codeOverLimit = codeBytes > MAX_CODE_BYTES
  const canSubmit = !submitting && code.trim().length > 0 && !codeOverLimit

  async function handleSubmit(e: { preventDefault(): void }) {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError('')

    const myBotId = botId.trim() || 'my_bot'

    // ── mock mode ──────────────────────────────────────────────
    if (MOCK) {
      await new Promise((r) => setTimeout(r, 600))
      navigate(`/games/dev/battleroyale/watch`)
      return
    }
    // ──────────────────────────────────────────────────────────

    try {
      const body: Record<string, unknown> = {
        bots: [{ bot_id: myBotId, name: myBotId, code, is_public: isPublic }],
        bot_count: botCount,
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
      navigate(`/games/${encodeURIComponent(game.game_id)}/battleroyale/watch`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '게임 생성에 실패했습니다.')
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen text-white" style={{
      position: 'relative',
      background: '#0D0F14',
      backgroundImage: 'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
      backgroundSize: '24px 24px',
    }}>
      <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 60% 70% at 50% 40%, rgba(155,89,245,.18) 0%, transparent 70%)',
      }} />
      {showRules && <RulesModal onClose={() => setShowRules(false)} />}

      <header className="sticky top-0 z-20 h-14 px-6 flex items-center gap-3" style={{ background: 'rgba(13,15,20,.92)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>
        <button onClick={() => navigate(-1)} className="text-gray-400 hover:text-white text-sm transition-colors">◀ 뒤로</button>
        <span className="text-gray-600">|</span>
        <span className="font-bold">⚔️ 배틀로얄 2D — 새 게임</span>
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

          {/* 게임 이름 */}
          <section className="flex flex-col gap-2">
            <label className="text-sm font-medium text-gray-300">
              게임 이름 <span className="text-gray-500 font-normal">(비우면 자동 설정됨)</span>
            </label>
            <input
              type="text"
              value={gameName}
              onChange={(e) => setGameName(e.target.value)}
              placeholder="새 배틀로얄 2D 1"
              maxLength={40}
              className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-600 w-72"
            />
          </section>

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
              className="bg-gray-800 text-white text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500 placeholder-gray-600 w-72"
            />
          </section>

          {/* 코드 입력 */}
          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-gray-300">봇 코드 (Python · class Bot)</label>
              <span className={`text-xs font-mono ${codeOverLimit ? 'text-red-400' : 'text-gray-500'}`}>
                {(codeBytes / 1024).toFixed(1)} KB / 50 KB
                {codeOverLimit && ' — 초과'}
              </span>
            </div>
            <BotCodeInput value={code} onChange={setCode} hasError={codeOverLimit} accentColor="indigo" />
            {codeOverLimit && <p className="text-red-400 text-xs">코드가 50KB를 초과합니다. 줄여주세요.</p>}
            <p className="text-xs text-gray-500">우측 상단 <b>📋 룰 확인</b> 에서 state/action 스키마를 확인하세요.</p>
          </section>

          {/* 게임 옵션 */}
          <section className="bg-gray-800 border border-gray-700 rounded-xl px-5 py-4 flex flex-col gap-3">
            <h3 className="text-sm font-medium text-gray-300">게임 옵션</h3>

            <div className="flex flex-col divide-y divide-gray-700/50">
              <div className="pb-3 flex items-center justify-between">
                <div>
                  <p className="text-sm text-white">봇 코드 공개</p>
                  <p className="text-xs text-gray-500">다른 유저가 내 봇 코드를 볼 수 있습니다</p>
                </div>
                <button
                  type="button"
                  onClick={() => setIsPublic((v) => !v)}
                  className={`relative w-11 h-6 rounded-full transition-colors ${isPublic ? 'bg-indigo-600' : 'bg-gray-700'}`}
                >
                  <span className={`absolute top-1 left-0 w-4 h-4 bg-white rounded-full shadow transition-transform ${isPublic ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
              </div>

              {/* 봇 수 */}
              <div className="py-3 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-white">봇 수</p>
                    <p className="text-xs text-gray-500">내 봇 1 + 나머지는 AI(초식/미친개/존버) 랜덤 채움</p>
                  </div>
                  <span className="text-sm text-indigo-400 font-mono">{botCount}봇</span>
                </div>
                <input
                  type="range"
                  min={2}
                  max={8}
                  step={1}
                  value={botCount}
                  onChange={(e) => setBotCount(parseInt(e.target.value, 10))}
                  className="w-full accent-indigo-500"
                />
                <div className="flex justify-between text-xs text-gray-600">
                  <span>2봇</span>
                  <span>8봇</span>
                </div>
              </div>

              <div className="pt-3 flex items-center justify-between">
                <div>
                  <p className="text-sm text-white">시드 (재현용, 선택)</p>
                  <p className="text-xs text-gray-500">비우면 랜덤</p>
                </div>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ''))}
                  placeholder="랜덤"
                  className="bg-gray-600 text-white text-sm rounded-lg px-3 py-1.5 outline-none focus:ring-2 focus:ring-indigo-500 w-20 text-center placeholder-gray-400"
                />
              </div>
            </div>
          </section>

          {error && (
            <div className="text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">{error}</div>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg py-3 transition-colors"
          >
            {submitting ? '게임 생성 중...' : '게임 시작'}
          </button>

        </form>
      </main>
    </div>
  )
}
