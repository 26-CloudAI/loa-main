import Phaser from 'phaser'

// ── World constants ───────────────────────────────────────────────────
const CELLS = 100
const CELL  = 6            // 6 px per cell → 600×600 world
const W     = CELLS * CELL // 600

// ── Minimap constants (fixed size; position is computed dynamically) ───
const MM_W    = 180
const MM_H    = 180
const MM_PAD  = 8
const MM_ZOOM = MM_W / W   // 0.3 — fit full world in minimap

// ── Label rendering constants ─────────────────────────────────────────
// 텍스트를 LABEL_RES배 해상도로 그려 선명도 확보
// LABEL_WORLD: 기준 월드 크기(px), update()에서 줌 반비례 보정됨
const LABEL_RES   = 10          // 오버샘플 배수
const LABEL_WORLD = 4           // 기준 월드 표시 크기(px) — 보정 전 기준값
const LABEL_PX    = LABEL_WORLD * LABEL_RES  // 실제 렌더 폰트 크기(40px)

// ── Shared types ──────────────────────────────────────────────────────

export interface BotState {
  id: string; x: number; y: number
  energy: number; score: number; alive: boolean; shield_active: boolean
}
export interface Mineral { x: number; y: number; rare: boolean }
export interface TickData {
  tick: number; bots: BotState[]; minerals: Mineral[]
  zone_bounds: [number, number, number, number]
  alive_count: number
}
export interface GameEvent {
  type: string; actor_id: string; target_id?: string
}

// ── Helpers ───────────────────────────────────────────────────────────

function botIcon(id: string, myId: string, myIcon: string): string {
  if (id === myId) return myIcon
  const s = id.toLowerCase()
  if (s.includes('초식') || s.includes('herbivore')) return '🌿'
  if (s.includes('미친개') || s.includes('maddog'))  return '🐺'
  if (s.includes('존버')   || s.includes('camper'))  return '🏕️'
  return '🤖'
}

function hashHex(id: string): number {
  let h = 5381
  for (let i = 0; i < id.length; i++) h = ((h << 5) + h + id.charCodeAt(i)) | 0
  const hue = Math.abs(h) % 360
  const s = 0.65, l = 0.58
  const k  = (n: number) => (n + hue / 30) % 12
  const a  = s * Math.min(l, 1 - l)
  const f  = (n: number) => Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))))
  return (f(0) << 16) | (f(8) << 8) | f(4)
}

// ── Per-bot graphics handle ───────────────────────────────────────────

interface BotGfx {
  root:   Phaser.GameObjects.Container
  icon:   Phaser.GameObjects.Image
  hpBg:   Phaser.GameObjects.Graphics
  hp:     Phaser.GameObjects.Graphics
  ring:   Phaser.GameObjects.Graphics
  shield: Phaser.GameObjects.Graphics
  label:  Phaser.GameObjects.Text
  tween?: Phaser.Tweens.Tween
}

// ── Scene ─────────────────────────────────────────────────────────────

export class BattleRoyaleScene extends Phaser.Scene {

  // ── React-facing refs ──────────────────────────────────────────────
  tickRef:       { current: TickData | null } = { current: null }
  eventQueueRef: { current: GameEvent[] }     = { current: [] }
  myBotId    = 'my_bot'
  followBotId = 'my_bot'
  myBotIcon  = '⭐'
  zoom       = 3

  // ── Internal state ─────────────────────────────────────────────────
  private bots     = new Map<string, BotGfx>()
  private minerals = new Map<string, Phaser.GameObjects.Image>()
  private zoneGfx!:    Phaser.GameObjects.Graphics
  // mmGfx: seen only by minimap camera (viewport indicator + border)
  private mmGfx!:      Phaser.GameObjects.Graphics
  private minimapCam!: Phaser.Cameras.Scene2D.Camera
  // minimap screen-space position (updated on resize)
  private mmX = 0
  private mmY = 0
  private death!:   Phaser.GameObjects.Particles.ParticleEmitter
  private sparks!:  Phaser.GameObjects.Particles.ParticleEmitter
  private lastTick = -1
  private lastTd:  TickData | null = null
  colorMap = new Map<string, number>()
  private isPanning = false
  onFollowChange?: (botId: string) => void

  constructor() { super({ key: 'BattleRoyaleScene' }) }

  // ── Emoji texture factory ──────────────────────────────────────────

  private emojiTex(emoji: string): string {
    const key = 'em_' + [...emoji]
      .map(c => c.codePointAt(0)!.toString(16))
      .join('_')
    if (this.textures.exists(key)) return key
    const SIZE = 72
    const ct = this.textures.createCanvas(key, SIZE, SIZE)
    if (!ct) return '__missing'
    const ctx = ct.getContext()
    ctx.clearRect(0, 0, SIZE, SIZE)
    ctx.font = `${Math.round(SIZE * 0.78)}px serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(emoji, SIZE / 2, SIZE / 2 + 2)
    ct.refresh()
    this.textures.get(key).setFilter(Phaser.Textures.FilterMode.LINEAR)
    return key
  }

  // ── create ─────────────────────────────────────────────────────────

  create() {
    for (const e of ['⭐','🤖','🐺','🌿','🏕️','💀','🪨','💎']) this.emojiTex(e)

    // World background
    this.add.graphics().fillStyle(0x0a0a0f).fillRect(0, 0, W, W)

    // Grid
    const grid = this.add.graphics()
    grid.lineStyle(0.5, 0xffffff, 0.05)
    for (let i = 0; i <= CELLS; i++) {
      grid.lineBetween(i * CELL, 0, i * CELL, W)
      grid.lineBetween(0, i * CELL, W, i * CELL)
    }

    this.zoneGfx = this.add.graphics()

    // mmGfx: minimap overlay (viewport rect + border). Depth 300 so it's on top.
    this.mmGfx = this.add.graphics().setDepth(300)

    // Particle textures
    const pg = this.make.graphics({ x: 0, y: 0 }, false)
    pg.fillStyle(0xffffff).fillCircle(3, 3, 3)
    pg.generateTexture('pt', 6, 6)
    pg.destroy()

    this.death = this.add.particles(0, 0, 'pt', {
      speed: { min: 40, max: 120 }, scale: { start: 1.1, end: 0 },
      alpha: { start: 1, end: 0 }, lifespan: 650,
      tint: [0xf87171, 0xfbbf24, 0xffffff], quantity: 0, emitting: false,
    }).setDepth(50)

    this.sparks = this.add.particles(0, 0, 'pt', {
      speed: { min: 15, max: 60 }, scale: { start: 0.7, end: 0 },
      alpha: { start: 1, end: 0 }, lifespan: 450,
      tint: [0xfacc15, 0xa855f7], quantity: 0, emitting: false, gravityY: -100,
    }).setDepth(50)

    // ── Main camera ───────────────────────────────────────────────────
    this.cameras.main
      .setBackgroundColor(0x0a0a0f)
      .setBounds(0, 0, W, W)
      .setZoom(this.zoom)
      .centerOn(W / 2, W / 2)

    // Main camera ignores mmGfx (viewport rect is for minimap only)
    this.cameras.main.ignore(this.mmGfx)

    // ── Minimap camera (screen-space position: dynamic, bottom-right) ──
    // cameras.add(x, y, width, height) uses SCREEN coords — no zoom issue!
    this.mmX = this.scale.width  - MM_W - MM_PAD
    this.mmY = this.scale.height - MM_H - MM_PAD
    this.minimapCam = this.cameras.add(this.mmX, this.mmY, MM_W, MM_H)
      .setZoom(MM_ZOOM)            // show full world
      .setBounds(0, 0, W, W)
      .setBackgroundColor(0x050508)
      .centerOn(W / 2, W / 2)
      .setName('minimap')

    // ── Input: minimap click/drag → pan main camera ───────────────────
    this.input.on('pointerdown', (p: Phaser.Input.Pointer) => {
      if (this.inMinimap(p.x, p.y)) {
        this.isPanning = true
        this.minimapPan(p.x, p.y)
      }
    })
    this.input.on('pointermove', (p: Phaser.Input.Pointer) => {
      if (this.isPanning && p.isDown) {
        this.minimapPan(
          Phaser.Math.Clamp(p.x, this.mmX, this.mmX + MM_W),
          Phaser.Math.Clamp(p.y, this.mmY, this.mmY + MM_H),
        )
      }
    })
    this.input.on('pointerup', () => { this.isPanning = false })
  }

  // ── Minimap helpers ───────────────────────────────────────────────

  private inMinimap(sx: number, sy: number): boolean {
    return sx >= this.mmX && sx <= this.mmX + MM_W && sy >= this.mmY && sy <= this.mmY + MM_H
  }

  private minimapPan(sx: number, sy: number) {
    // screen px → cell index → world pos
    const cellX = (sx - this.mmX) / (MM_W / CELLS)
    const cellY = (sy - this.mmY) / (MM_H / CELLS)
    this.cameras.main.pan(cellX * CELL, cellY * CELL, 80, 'Sine.easeOut')
  }

  // ── Public resize hook (called from React when canvas size changes) ─
  resize(canvasSize: number) {
    this.mmX = canvasSize - MM_W - MM_PAD
    this.mmY = canvasSize - MM_H - MM_PAD
    this.minimapCam?.setPosition(this.mmX, this.mmY)
  }

  // ── update ─────────────────────────────────────────────────────────

  update() {
    const ev = this.eventQueueRef.current.shift()
    if (ev) this.handleEvent(ev)

    this.cameras.main.zoom = Phaser.Math.Linear(
      this.cameras.main.zoom, this.zoom, 0.1,
    )

    // 줌에 반비례해서 라벨 스케일 보정:
    // 화면상 목표 크기(TARGET_SCREEN_PX)를 유지하도록 월드 스케일 계산
    // scale = TARGET_SCREEN_PX / (LABEL_PX × zoom)
    const TARGET_SCREEN_PX = 13  // 화면상 라벨 높이(px) — 줌 무관 고정
    const zoom = this.cameras.main.zoom
    const labelScale = TARGET_SCREEN_PX / (LABEL_PX * zoom)
    for (const [, gfx] of this.bots) {
      gfx.label.setScale(labelScale)
    }

    const td = this.tickRef.current
    if (td && td.tick !== this.lastTick) {
      this.lastTick = td.tick
      this.lastTd   = td
      this.applyTick(td)
    }

    if (this.lastTd) this.drawMinimapOverlay()
  }

  // ── Tick processing ────────────────────────────────────────────────

  private applyTick(td: TickData) {
    this.drawZone(td.zone_bounds)
    this.syncMinerals(td.minerals)
    this.syncBots(td.bots)
    this.followBot(td.bots)
  }

  // ── Zone ──────────────────────────────────────────────────────────

  private drawZone([x0, y0, x1, y1]: [number, number, number, number]) {
    const g = this.zoneGfx.clear()
    g.fillStyle(0xdc2626, 0.18)
    g.fillRect(0, 0,            W,              y0 * CELL)
    g.fillRect(0, (y1+1)*CELL,  W,              W - (y1+1)*CELL)
    g.fillRect(0, y0*CELL,      x0*CELL,        (y1-y0+1)*CELL)
    g.fillRect((x1+1)*CELL, y0*CELL, W-(x1+1)*CELL, (y1-y0+1)*CELL)
    g.lineStyle(1.5, 0xef4444, 0.8)
    g.strokeRect(x0*CELL, y0*CELL, (x1-x0+1)*CELL, (y1-y0+1)*CELL)
  }

  // ── Minerals ──────────────────────────────────────────────────────

  private syncMinerals(minerals: Mineral[]) {
    const alive = new Set<string>()
    for (const m of minerals) {
      const k = `${m.x},${m.y}`
      alive.add(k)
      if (!this.minerals.has(k)) {
        const img = this.add.image(
          (m.x + 0.5) * CELL, (m.y + 0.5) * CELL,
          this.emojiTex(m.rare ? '💎' : '🪨'),
        ).setDisplaySize(CELL * 0.82, CELL * 0.82).setOrigin(0.5)
        this.minerals.set(k, img)
      }
    }
    for (const [k, img] of this.minerals) {
      if (!alive.has(k)) { img.destroy(); this.minerals.delete(k) }
    }
  }

  // ── Bots ──────────────────────────────────────────────────────────

  private syncBots(bots: BotState[]) {
    for (const bot of bots) {
      const isMe = bot.id === this.myBotId
      const wx   = (bot.x + 0.5) * CELL
      const wy   = (bot.y + 0.5) * CELL
      if (!this.bots.has(bot.id)) this.createBot(bot.id, isMe, wx, wy)
      const gfx = this.bots.get(bot.id)!

      if (!bot.alive) {
        gfx.root.setAlpha(0.25)
        gfx.icon.setTexture(this.emojiTex('💀'))
        gfx.hpBg.setVisible(false); gfx.hp.setVisible(false)
        gfx.ring.setVisible(false); gfx.shield.setVisible(false)
        gfx.label.setVisible(false)
        gfx.root.setPosition(wx, wy)
        continue
      }

      gfx.root.setAlpha(1)
      gfx.icon.setTexture(this.emojiTex(botIcon(bot.id, this.myBotId, this.myBotIcon)))

      if (gfx.tween) gfx.tween.stop()
      gfx.tween = this.tweens.add({
        targets: gfx.root, x: wx, y: wy, duration: 90, ease: 'Sine.easeOut',
      })

      const ratio = Math.max(0, Math.min(1, bot.energy / 100))
      const bw = CELL * 1.5, bh = 1.5, bx = -bw / 2, by = -CELL * 0.9
      gfx.hpBg.clear().fillStyle(0x111111).fillRect(bx, by, bw, bh).setVisible(true)
      const col = ratio > 0.5 ? 0x4ade80 : ratio > 0.25 ? 0xfacc15 : 0xf87171
      gfx.hp.clear().fillStyle(col).fillRect(bx, by, bw * ratio, bh).setVisible(true)
      gfx.ring.setVisible(isMe)
      gfx.shield.setVisible(bot.shield_active)
      gfx.label.setVisible(true)
    }
  }

  private createBot(id: string, isMe: boolean, x: number, y: number) {
    const color = this.colorMap.get(id) ?? hashHex(id)
    if (!this.colorMap.has(id)) this.colorMap.set(id, color)
    const root   = this.add.container(x, y).setDepth(10)
    const ring   = this.add.graphics().lineStyle(1.2, 0xffd700, 0.9).strokeCircle(0, 0, CELL * 0.75)
    const shield = this.add.graphics().lineStyle(1.2, 0x00c8dc, 0.85).strokeCircle(0, 0, CELL * 0.98)
    const hpBg   = this.add.graphics()
    const hp     = this.add.graphics()
    const icon   = this.add.image(0, 0.5, this.emojiTex(botIcon(id, this.myBotId, this.myBotIcon)))
      .setDisplaySize(CELL * 0.92, CELL * 0.92).setOrigin(0.5)
    // 텍스트를 LABEL_RES배 해상도로 렌더링 후 스케일 다운 → 선명
    // 실제 화면 크기는 update()에서 줌 반비례로 매 프레임 보정됨
    const label  = this.add.text(0, CELL * 0.95, isMe ? `★ ${id}` : id, {
      fontSize: `${LABEL_PX}px`,
      fontFamily: '"Noto Sans KR", "Apple SD Gothic Neo", sans-serif',
      color: isMe ? '#ffd700' : '#e2e8f0',
      stroke: '#000000',
      strokeThickness: LABEL_RES * 2,
      resolution: 2,
      padding: { x: LABEL_RES, y: LABEL_RES / 2 },
    }).setOrigin(0.5, 0).setScale(LABEL_WORLD / LABEL_PX)
    root.add([ring, shield, hpBg, hp, icon, label])
    this.bots.set(id, { root, icon, hpBg, hp, ring, shield, label })
  }

  // ── Camera follow ─────────────────────────────────────────────────

  private followBot(bots: BotState[]) {
    if (this.isPanning) return
    const preferred = bots.find(b => b.id === this.followBotId && b.alive)
    const target    = preferred ?? bots.find(b => b.id === this.myBotId && b.alive)
    // If the followed bot died, fall back to myBotId and notify React
    if (!preferred && target && this.followBotId !== this.myBotId) {
      this.followBotId = this.myBotId
      this.onFollowChange?.(this.myBotId)
    }
    if (target) {
      this.cameras.main.pan(
        (target.x + 0.5) * CELL, (target.y + 0.5) * CELL, 130, 'Sine.easeOut',
      )
    }
  }

  // ── Events ────────────────────────────────────────────────────────

  // 원형 펄스 헬퍼 (color: 0xRRGGBB)
  private pulse(x: number, y: number, color: number, radius: number, duration: number) {
    const g = this.add.graphics().setDepth(30)
    g.lineStyle(1.2, color, 0.9).strokeCircle(x, y, radius)
    this.tweens.add({
      targets: g, alpha: 0, scaleX: 2.2, scaleY: 2.2,
      duration, ease: 'Quad.easeOut',
      onComplete: () => g.destroy(),
    })
  }

  private handleEvent(ev: GameEvent) {
    const gfx     = this.bots.get(ev.actor_id)
    const tgfx    = ev.target_id ? this.bots.get(ev.target_id) : undefined
    const pos     = gfx  ? { x: gfx.root.x,  y: gfx.root.y  } : null
    const tpos    = tgfx ? { x: tgfx.root.x, y: tgfx.root.y } : null
    // 카메라 효과는 관전 중인 봇(또는 내 봇) 관련 이벤트일 때만 적용
    const isFocused = ev.actor_id === this.followBotId || ev.actor_id === this.myBotId
                   || ev.target_id === this.followBotId || ev.target_id === this.myBotId
    switch (ev.type) {
      case 'death':
        if (pos) this.death.setPosition(pos.x, pos.y).explode(18)  // 파티클은 항상
        if (isFocused) {
          this.cameras.main.shake(200, 0.006)
          this.cameras.main.flash(120, 255, 80, 80, false)
        }
        break
      case 'mine_success':
        if (pos) this.sparks.setPosition(pos.x, pos.y).explode(8)
        break
      case 'kill':
        break
      case 'attack_hit':
        // 공격자 → 피격자 방향 짧은 선 + 피격자 위치에 붉은 펄스
        if (pos && tpos) {
          const line = this.add.graphics().setDepth(29)
          line.lineStyle(1, 0xef4444, 0.7).lineBetween(pos.x, pos.y, tpos.x, tpos.y)
          this.tweens.add({ targets: line, alpha: 0, duration: 150, onComplete: () => line.destroy() })
        }
        if (tpos) this.pulse(tpos.x, tpos.y, 0xef4444, CELL * 0.9, 280)
        break
      case 'attack_miss':
        // 공격자 위치에 회색 작은 펄스
        if (pos) this.pulse(pos.x, pos.y, 0x6b7280, CELL * 0.6, 200)
        break
      case 'guard_success':
        // 방어 성공 — 청록 펄스
        if (pos) this.pulse(pos.x, pos.y, 0x22d3ee, CELL * 1.0, 300)
        break
      case 'shield':
        // 실드 전개 — 넓고 천천히 퍼지는 청보라 펄스
        if (pos) this.pulse(pos.x, pos.y, 0x818cf8, CELL * 1.1, 450)
        break
      case 'zone_damage':
        if (pos) {
          const pulse = this.add.graphics().setDepth(30)
          pulse.lineStyle(1, 0xf97316, 0.8).strokeCircle(pos.x, pos.y, CELL * 1.2)
          this.tweens.add({
            targets: pulse, alpha: 0, scaleX: 2, scaleY: 2,
            duration: 350, ease: 'Quad.easeOut',
            onComplete: () => pulse.destroy(),
          })
        }
        break
    }
  }

  // ── Minimap overlay (seen only by minimapCam) ─────────────────────
  // Draws: world border + viewport indicator rect in world-space coords.
  // The zone/bots/minerals are automatically rendered by minimapCam
  // since they are regular world objects.

  private drawMinimapOverlay() {
    const g  = this.mmGfx.clear()
    const lw = 1 / MM_ZOOM   // 1 screen-pixel in world units at minimap zoom

    // World border
    const ia = this.isPanning
    g.lineStyle(lw * (ia ? 2 : 1), ia ? 0x6366f1 : 0x6b7280, ia ? 0.95 : 0.7)
    g.strokeRect(0, 0, W, W)

    // Viewport indicator: where the main camera is currently looking
    const mv = this.cameras.main.worldView
    g.lineStyle(lw * 1.5, ia ? 0x6366f1 : 0xffffff, 0.85)
    g.strokeRect(mv.x, mv.y, mv.width, mv.height)
  }
}
