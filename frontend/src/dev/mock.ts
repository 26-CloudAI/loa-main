// ─── Mock mode (VITE_MOCK=true 일 때만 활성화) ───────────────────────────────
export const MOCK = import.meta.env.VITE_MOCK === 'true'

// ── Mock 사용자 ────────────────────────────────────────────────────────────────
export const MOCK_USER = {
  id: 1,
  username: 'alice',
  display_name: 'Alice',
  email: 'alice@arena.dev',
  role: 'user',
}
export const MOCK_TOKEN = 'mock-jwt-token'

// ── Mock 게임 목록 ─────────────────────────────────────────────────────────────
export const MOCK_GAME_ID = 'aaaaaaaa-1111-2222-3333-444444444444'

export const MOCK_GAMES = [
  // 가장 최근 생성 — 대기 중
  {
    game_id: 'bbbbbbbb-1111-2222-3333-444444444444',
    status: 'waiting',
    current_tick: 0,
    total_bots: 2,
    alive_bots: 2,
    bot_ids: ['my_bot', 'BOSS'],
    name: '새 보스전 1',
    mode: 'boss',
  },
  // 진행 중
  {
    game_id: MOCK_GAME_ID,
    status: 'running',
    current_tick: 45,
    total_bots: 4,
    alive_bots: 3,
    bot_ids: ['my_bot', 'AI_초식_0', 'AI_미친개_1', 'AI_존버_2'],
    name: '새 배틀로얄 2',
    mode: 'battle-royale',
  },
  // 가장 오래된 — 종료
  {
    game_id: 'cccccccc-1111-2222-3333-444444444444',
    status: 'finished',
    current_tick: 200,
    total_bots: 4,
    alive_bots: 0,
    bot_ids: ['my_bot', 'AI_초식_0', 'AI_미친개_1', 'AI_존버_2'],
    name: '새 배틀로얄 1',
    mode: 'battle-royale',
  },
]

export const MOCK_GAME_INFO = {
  game_id: MOCK_GAME_ID,
  status: 'running',
  current_tick: 0,
  total_bots: 4,
  alive_bots: 4,
  bot_ids: ['my_bot', 'AI_초식_0', 'AI_미친개_1', 'AI_존버_2'],
}

// ── Mock tick 시뮬레이터 ────────────────────────────────────────────────────────

interface MockBot {
  id: string
  x: number
  y: number
  energy: number
  score: number
  alive: boolean
  shield_active: boolean
}

interface MockMineral {
  x: number
  y: number
  rare: boolean
}

function rand(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min
}

function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v))
}

// 광물 초기 배치
function initMinerals(): MockMineral[] {
  const minerals: MockMineral[] = []
  // 중앙 일반 광물
  for (let i = 0; i < 60; i++) {
    minerals.push({ x: rand(30, 70), y: rand(30, 70), rare: false })
  }
  // 희귀 광물
  for (let i = 0; i < 8; i++) {
    minerals.push({ x: rand(5, 95), y: rand(5, 95), rare: true })
  }
  return minerals
}

// 봇 초기 배치
function initBots(): MockBot[] {
  return [
    { id: 'my_bot',      x: 20, y: 20, energy: 100, score: 0,  alive: true, shield_active: false },
    { id: 'AI_초식_0',   x: 80, y: 20, energy: 100, score: 0,  alive: true, shield_active: false },
    { id: 'AI_미친개_1', x: 80, y: 80, energy: 100, score: 0,  alive: true, shield_active: false },
    { id: 'AI_존버_2',   x: 20, y: 80, energy: 100, score: 0,  alive: true, shield_active: false },
  ]
}

export function startMockSimulation(callbacks: {
  onTick: (data: {
    tick: number
    bots: MockBot[]
    minerals: MockMineral[]
    zone_bounds: [number, number, number, number]
    alive_count: number
    leaderboard: { rank: number; id: string; score: number }[]
  }) => void
  onEvent: (ev: { event_type: string; actor_id: string; target_id?: string }) => void
  onEnd: (data: { reason: string; rankings: { rank: number; id: string; score: number; kills: number; minerals_mined: number; survival_ticks: number }[] }) => void
}): () => void {
  let tick = 0
  const bots = initBots()
  let minerals = initMinerals()
  const kills: Record<string, number> = {}
  const mined: Record<string, number> = {}
  bots.forEach((b) => { kills[b.id] = 0; mined[b.id] = 0 })

  const MAX_TICKS = 200

  const id = setInterval(() => {
    tick++

    // Zone boundary → zone_bounds: [minX, minY, maxX, maxY]
    let zb = 0
    if (tick >= 76 && tick < 151)  zb = Math.floor((tick - 76) / 20) + 1
    if (tick >= 151)               zb = Math.floor((tick - 151) / 10) + 4
    const zone_bounds: [number, number, number, number] = [zb, zb, 99 - zb, 99 - zb]

    const aliveBots = bots.filter((b) => b.alive)

    // Move bots randomly
    for (const bot of aliveBots) {
      const dx = rand(-2, 2)
      const dy = rand(-2, 2)
      bot.x = clamp(bot.x + dx, 0, 99)
      bot.y = clamp(bot.y + dy, 0, 99)
      bot.energy = clamp(bot.energy - 1, 0, 100)

      // Zone damage
      if (zb > 0 && (bot.x < zone_bounds[0] || bot.x > zone_bounds[2] || bot.y < zone_bounds[1] || bot.y > zone_bounds[3])) {
        bot.energy = clamp(bot.energy - 3, 0, 100)
        if (Math.random() < 0.1) {
          callbacks.onEvent({ event_type: 'zone_damage', actor_id: bot.id })
        }
      }

      // Mine nearby mineral
      const nearIdx = minerals.findIndex((m) => Math.abs(m.x - bot.x) <= 1 && Math.abs(m.y - bot.y) <= 1)
      if (nearIdx >= 0 && Math.random() < 0.3) {
        const m = minerals[nearIdx]
        const pts = m.rare ? 40 : 15
        bot.score += pts
        bot.energy = clamp(bot.energy + (m.rare ? 25 : 10), 0, 100)
        mined[bot.id] = (mined[bot.id] ?? 0) + 1
        minerals.splice(nearIdx, 1)
        callbacks.onEvent({ event_type: 'mine_success', actor_id: bot.id })
      }

      // Occasional attack
      if (Math.random() < 0.02) {
        const target = aliveBots.find((b) => b.id !== bot.id && Math.abs(b.x - bot.x) <= 1 && Math.abs(b.y - bot.y) <= 1)
        if (target) {
          target.energy = clamp(target.energy - 25, 0, 100)
          bot.score += 2
          callbacks.onEvent({ event_type: 'kill', actor_id: bot.id, target_id: target.id })
        }
      }

      // Shield flicker
      bot.shield_active = Math.random() < 0.05

      // Survival bonus
      bot.score += 0.1

      // Death check
      if (bot.energy <= 0) {
        bot.alive = false
        bot.shield_active = false
        kills[bot.id] = kills[bot.id] ?? 0
        callbacks.onEvent({ event_type: 'death', actor_id: bot.id })
      }
    }

    // Regenerate a few minerals occasionally
    if (Math.random() < 0.15 && minerals.length < 80) {
      minerals.push({ x: rand(10, 90), y: rand(10, 90), rare: false })
    }

    // Leaderboard
    const sorted = [...bots].sort((a, b) => b.score - a.score)
    const leaderboard = sorted.slice(0, 3).map((b, i) => ({
      rank: i + 1, id: b.id, score: Math.round(b.score * 10) / 10,
    }))

    callbacks.onTick({
      tick,
      bots: bots.map((b) => ({ ...b, score: Math.round(b.score * 10) / 10 })),
      minerals,
      zone_bounds,
      alive_count: aliveBots.length,
      leaderboard,
    })

    // End condition
    const stillAlive = bots.filter((b) => b.alive)
    if (stillAlive.length <= 1 || tick >= MAX_TICKS) {
      clearInterval(id)
      const reason = tick >= MAX_TICKS ? 'max_ticks' : 'last_standing'
      const rankings = [...bots]
        .sort((a, b) => b.score - a.score)
        .map((b, i) => ({
          rank: i + 1,
          id: b.id,
          score: Math.round(b.score * 10) / 10,
          kills: kills[b.id] ?? 0,
          minerals_mined: mined[b.id] ?? 0,
          survival_ticks: tick,
        }))
      callbacks.onEnd({ reason, rankings })
    }
  }, 150) // 150ms per tick

  return () => clearInterval(id)
}
