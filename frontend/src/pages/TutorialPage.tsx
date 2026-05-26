import React, { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import PythonEditor from '../components/PythonEditor'

type Mode = 'battle-royale' | 'boss' | 'stocks'

// ── 셀 타입 ───────────────────────────────────────────────────────────────────

type CellType = 'me' | 'mineral' | 'rare' | 'enemy' | 'zone' | 'arrow' | 'empty'
type RawCell = [CellType, string?]

const CELL_STYLE: Record<CellType, { bg: string; fg: string; label: string }> = {
  me:      { bg: '#0EA5E9', fg: '#fff',                    label: '●' },
  mineral: { bg: '#EAB308', fg: '#fff',                    label: '◆' },
  rare:    { bg: '#A855F7', fg: '#fff',                    label: '◆' },
  enemy:   { bg: '#EF4444', fg: '#fff',                    label: '●' },
  zone:    { bg: 'rgba(239,68,68,.25)', fg: '#F87171',     label: '✕' },
  arrow:   { bg: 'rgba(14,165,233,.15)', fg: '#38BDF8',    label: '' },
  empty:   { bg: 'rgba(255,255,255,.04)', fg: '#374151',   label: '' },
}

function MiniGrid({ rows }: { rows: RawCell[][] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 3 }}>
      {rows.flat().map(([type, arrow], i) => {
        const s = CELL_STYLE[type]
        return (
          <div key={i} style={{
            width: 36, height: 36, background: s.bg, borderRadius: 6,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: s.fg, fontSize: type === 'arrow' ? 16 : 14, fontWeight: 700,
          }}>
            {type === 'arrow' ? arrow : s.label}
          </div>
        )
      })}
    </div>
  )
}

// ── 주식 차트 미니 시각화 ─────────────────────────────────────────────────────

function MiniStockChart({ bars, highlight }: { bars: number[]; highlight?: number }) {
  const max = Math.max(...bars)
  const min = Math.min(...bars)
  const range = max - min || 1
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 64 }}>
      {bars.map((v, i) => {
        const h = ((v - min) / range) * 52 + 12
        const isUp = i > 0 && v >= bars[i - 1]
        const isHighlight = i === highlight
        return (
          <div key={i} style={{
            width: 14, height: h,
            background: isHighlight ? '#818CF8' : isUp ? '#4ADE80' : '#F87171',
            borderRadius: 3,
            opacity: isHighlight ? 1 : 0.7,
            boxShadow: isHighlight ? '0 0 8px rgba(129,140,248,.6)' : 'none',
            transition: 'all .2s',
          }} />
        )
      })}
    </div>
  )
}

// ── 포트폴리오 시각화 ─────────────────────────────────────────────────────────

function PortfolioVisual() {
  const stocks = [
    { sym: 'NeoChips',  pnl: +18.4, color: '#4ADE80' },
    { sym: 'AeroTech',  pnl: -8.2,  color: '#F87171' },
    { sym: 'DataCorp',  pnl: +5.1,  color: '#4ADE80' },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6B7280', marginBottom: 2 }}>
        <span>보유 종목</span><span>수익률</span>
      </div>
      {stocks.map(({ sym, pnl, color }) => (
        <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: '#D1D5DB', flex: 1 }}>{sym}</span>
          <div style={{ width: 80, height: 4, background: '#1F2937', borderRadius: 9999, overflow: 'hidden' }}>
            <div style={{
              width: `${Math.min(Math.abs(pnl) * 3, 100)}%`,
              height: '100%', background: color, borderRadius: 9999,
            }} />
          </div>
          <span style={{ fontSize: 11, color, width: 44, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
            {pnl > 0 ? '+' : ''}{pnl}%
          </span>
        </div>
      ))}
      <div style={{ borderTop: '1px solid #1F2937', marginTop: 4, paddingTop: 6, display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
        <span style={{ color: '#6B7280' }}>총 자산</span>
        <span style={{ color: '#4ADE80', fontWeight: 700 }}>₩112,340,000</span>
      </div>
    </div>
  )
}

// ── 헬퍼 ──────────────────────────────────────────────────────────────────────

const E: RawCell = ['empty']
const ME: RawCell = ['me']
const MIN: RawCell = ['mineral']
const EN: RawCell = ['enemy']
const Z: RawCell = ['zone']
function A(ch: string): RawCell { return ['arrow', ch] }

// ── 튜토리얼 단계 타입 ────────────────────────────────────────────────────────

interface Step {
  badge: string
  title: string
  subtitle: string
  description: string
  tips: { icon: string; text: string }[]
  code: string
  renderVisual: () => React.ReactElement
}

// ── 배틀로얄 단계 ─────────────────────────────────────────────────────────────

const BR_STEPS: Step[] = [
  {
    badge: 'Step 1', title: '봇의 기본 구조', subtitle: '함수 하나면 충분합니다',
    description: '엔진은 매 틱마다 action(state) 함수를 호출하고, \n반환된 문자열 하나를 봇의 행동으로 실행합니다.',
    tips: [
      { icon: '⚡', text: 'action(state) 함수 하나면 봇이 됩니다' },
      { icon: '📦', text: 'state 딕셔너리에 모든 게임 정보가 담겨 있습니다' },
      { icon: '🛡️', text: '잘못된 값을 반환하면 자동으로 STAY 처리됩니다' },
    ],
    code: `def action(state: dict) -> str:
    # 매 틱마다 엔진이 호출합니다.
    # 반환한 문자열이 이번 틱의 행동입니다.
    return "STAY"`,
    renderVisual: () => (
      <MiniGrid rows={[
        [E, E, E, E, E], [E, E, E, E, E],
        [E, E, ME, E, E],
        [E, E, E, E, E], [E, E, E, E, E],
      ]} />
    ),
  },
  {
    badge: 'Step 2', title: '내 봇 상태 읽기', subtitle: '나를 알아야 살아남습니다',
    description: 'state["my_bot"]에 내 위치, 에너지, 점수가 \n담겨 있습니다. 에너지가 0이 되면 즉시 사망합니다.',
    tips: [
      { icon: '📍', text: 'position은 [x, y] 형식. 좌상단이 [0, 0]' },
      { icon: '❤️', text: '에너지 20 이하는 위험 신호, SHIELD를 쓰세요' },
      { icon: '🛡️', text: 'SHIELD는 에너지 −3이지만 공격을 완전히 막습니다' },
    ],
    code: `def action(state: dict) -> str:
    my     = state["my_bot"]
    x, y   = my["position"]  # 현재 좌표
    energy = my["energy"]    # 남은 에너지

    # 에너지가 낮으면 방어
    if energy <= 20:
        return "SHIELD"

    return "STAY"`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <MiniGrid rows={[
          [E, E, E, E, E], [E, E, E, E, E],
          [E, E, ME, E, EN],
          [E, E, E, E, E], [E, E, E, E, E],
        ]} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width: '100%' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#9CA3AF' }}>
            <span>에너지</span><span style={{ color: '#F87171' }}>15 / 100</span>
          </div>
          <div style={{ height: 6, background: '#1F2937', borderRadius: 9999, overflow: 'hidden' }}>
            <div style={{ width: '15%', height: '100%', background: '#EF4444', borderRadius: 9999 }} />
          </div>
          <p style={{ fontSize: 10, color: '#F87171', margin: 0 }}>⚠ SHIELD 권장 구간</p>
        </div>
      </div>
    ),
  },
  {
    badge: 'Step 3', title: '8방향 이동', subtitle: '맵을 탐색하며 기회를 찾으세요',
    description: '봇은 매 틱 8방향 중 하나로 이동할 수 있습니다. \n이동할 때마다 에너지가 2씩 줄어듭니다.',
    tips: [
      { icon: '🗺️', text: '맵은 100×100 격자. MOVE_UP은 y 감소, \nMOVE_DOWN은 y 증가' },
      { icon: '↗️', text: '대각선 이동도 에너지 소모는 −2로 동일합니다' },
      { icon: '🎯', text: '목적 없는 랜덤 이동은 에너지 낭비입니다' },
    ],
    code: `import random

def action(state: dict) -> str:
    if state["my_bot"]["energy"] <= 20:
        return "SHIELD"

    return random.choice([
        "MOVE_UP",        "MOVE_DOWN",
        "MOVE_LEFT",      "MOVE_RIGHT",
        "MOVE_UP_LEFT",   "MOVE_UP_RIGHT",
        "MOVE_DOWN_LEFT", "MOVE_DOWN_RIGHT",
    ])`,
    renderVisual: () => (
      <MiniGrid rows={[
        [E, E, A('↑'), E, E],
        [E, A('↖'), A('↑'), A('↗'), E],
        [A('←'), A('←'), ME, A('→'), A('→')],
        [E, A('↙'), A('↓'), A('↘'), E],
        [E, E, A('↓'), E, E],
      ]} />
    ),
  },
  {
    badge: 'Step 4', title: '광물 채굴하기', subtitle: '점수의 핵심, 광물을 노려라',
    description: 'vision.grid는 내 주변 5×5 시야입니다. \n중심 grid[2][2]가 내 위치이고, 광물 위로 이동한 다음 \n틱에 MINE을 반환하면 채굴됩니다.',
    tips: [
      { icon: '⛏️', text: '일반 광물 +5점, 희귀 광물 +20점 & 에너지 +25' },
      { icon: '⏱️', text: 'MINE은 광물 위에 올라선 다음 틱에 써야 합니다' },
      { icon: '👁️', text: 'grid[row][col] — row/col 2가 중심(내 위치)' },
    ],
    code: `_mine_next = False

def action(state: dict) -> str:
    global _mine_next

    grid = state["vision"]["grid"]

    if _mine_next:
        _mine_next = False
        return "MINE"

    if grid[2][3] in ("mineral", "mineral_rare"):
        _mine_next = True
        return "MOVE_RIGHT"

    return "STAY"`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
        <MiniGrid rows={[
          [E, E, E, E, E], [E, E, E, E, E],
          [E, ME, A('→'), MIN, E],
          [E, E, E, E, E], [E, E, E, E, E],
        ]} />
        <p style={{ fontSize: 11, color: '#EAB308', margin: 0 }}>이동 → 다음 틱 MINE</p>
      </div>
    ),
  },
  {
    badge: 'Step 5', title: '자기장 생존', subtitle: '존 밖은 매 틱 에너지가 닳습니다',
    description: '76틱부터 자기장이 수축합니다. \nzone_bounds 바깥에 있으면 매 틱 에너지 −3. \n151틱부터는 수축 속도가 2배입니다.',
    tips: [
      { icon: '🌀', text: 'zone_bounds = (min_x, min_y, max_x, max_y) 형식' },
      { icon: '🏃', text: '존 밖에서는 채굴보다 복귀가 절대 우선입니다' },
      { icon: '🎯', text: '존 중심에 있을수록 여유 시간이 길어집니다' },
    ],
    code: `import random
_mine_next = False

def action(state: dict) -> str:
    global _mine_next
    my = state["my_bot"]
    x, y = my["position"]
    energy = my["energy"]
    min_x, min_y, max_x, max_y = state.get(
        "zone_bounds", (0, 0, 99, 99)
    )

    # 존 밖이면 중앙으로 복귀 (최우선)
    if not (min_x <= x <= max_x and min_y <= y <= max_y):
        _mine_next = False
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        if abs(cx - x) >= abs(cy - y):
            return "MOVE_RIGHT" if cx > x else "MOVE_LEFT"
        return "MOVE_DOWN" if cy > y else "MOVE_UP"

    if energy <= 20:
        return "SHIELD"

    grid = state["vision"]["grid"]
    if _mine_next:
        _mine_next = False
        return "MINE"
    for dc, mv in [(1,"MOVE_RIGHT"),(-1,"MOVE_LEFT")]:
        if grid[2][2+dc] in ("mineral","mineral_rare"):
            _mine_next = True
            return mv
    return random.choice(["MOVE_UP","MOVE_DOWN",
                           "MOVE_LEFT","MOVE_RIGHT"])`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
        <MiniGrid rows={[
          [Z, Z, Z, Z, Z],
          [Z, E, E, E, Z],
          [Z, E, ME, MIN, Z],
          [Z, E, E, E, Z],
          [Z, Z, Z, Z, Z],
        ]} />
        <p style={{ fontSize: 11, color: '#F87171', margin: 0 }}>빨간 테두리 = 자기장 (매틱 −3)</p>
      </div>
    ),
  },
]

// ── 보스전 단계 ───────────────────────────────────────────────────────────────

const BOSS_STEPS: Step[] = [
  {
    badge: 'Step 1', title: '보스전 기본 구조', subtitle: '1대1, 더 치열한 싸움입니다',
    description: '배틀로얄과 동일한 action(state) 함수를 씁니다. \n차이는 단 하나 — 상대가 강화학습으로 훈련된 \n보스 봇 하나뿐입니다.',
    tips: [
      { icon: '🤖', text: '보스는 훈련된 RL 봇입니다. 랜덤하게 움직이지 않습니다' },
      { icon: '⚡', text: 'action(state) 반환값은 배틀로얄과 동일한 문자열' },
      { icon: '🎯', text: '상대가 하나이므로 vision.grid를 더 적극적으로 활용하세요' },
    ],
    code: `def action(state: dict) -> str:
    # 배틀로얄과 동일한 함수 구조
    my = state["my_bot"]
    energy = my["energy"]

    if energy <= 20:
        return "SHIELD"

    return "STAY"`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
        <MiniGrid rows={[
          [E, E, E, E, E],
          [E, E, E, E, E],
          [ME, E, E, E, EN],
          [E, E, E, E, E],
          [E, E, E, E, E],
        ]} />
        <p style={{ fontSize: 11, color: '#F87171', margin: 0 }}>나 vs 보스 1대1</p>
      </div>
    ),
  },
  {
    badge: 'Step 2', title: '보스 위치 파악', subtitle: '시야로 보스를 추적하세요',
    description: 'vision.grid의 "bot_enemy" 셀로 보스의 상대 위치를 알 수 있습니다. 보스가 시야에 들어오면 그 방향을 계산할 수 있습니다.',
    tips: [
      { icon: '👁️', text: 'grid[row][col] == "bot_enemy" 이면 \n그 위치에 보스가 있습니다' },
      { icon: '📐', text: 'grid 인덱스 (2,2)가 내 위치. (row-2, col-2)가 상대적 거리' },
      { icon: '📡', text: '보스가 시야 밖이면 other_bots 리스트로도 확인 가능' },
    ],
    code: `def action(state: dict) -> str:
    my = state["my_bot"]
    energy = my["energy"]
    grid = state["vision"]["grid"]

    if energy <= 20:
        return "SHIELD"

    # 시야 내 보스 위치 탐색
    for row in range(5):
        for col in range(5):
            if grid[row][col] == "bot_enemy":
                dr = row - 2  # 상대적 y 거리
                dc = col - 2  # 상대적 x 거리
                # 보스 방향 출력 (다음 단계에서 활용)
                print(f"보스: dx={dc}, dy={dr}")

    return "STAY"`,
    renderVisual: () => (
      <MiniGrid rows={[
        [E, E, E, E, E],
        [E, E, E, EN, E],
        [E, E, ME, E, E],
        [E, E, E, E, E],
        [E, E, E, E, E],
      ]} />
    ),
  },
  {
    badge: 'Step 3', title: '공격 타이밍', subtitle: '인접하면 바로 공격하세요',
    description: '보스가 인접(상하좌우 1칸)해 있으면 ATTACK_* 액션으로 공격합니다. 에너지 −5이지만 보스에게 25 피해를 줍니다.',
    tips: [
      { icon: '⚔️', text: 'ATTACK_UP/DOWN/LEFT/RIGHT로 \n인접 칸을 공격합니다' },
      { icon: '↖️', text: '대각선 ATTACK_UP_LEFT 등도 사용 가능합니다' },
      { icon: '🛡️', text: '보스가 SHIELD를 쓰면 공격이 무효화됩니다. 타이밍이 중요' },
    ],
    code: `def action(state: dict) -> str:
    my = state["my_bot"]
    energy = my["energy"]
    grid = state["vision"]["grid"]

    if energy <= 20:
        return "SHIELD"

    # 8방향 인접 공격
    attack_map = [
        (-1,-1,"ATTACK_UP_LEFT"),  (0,-1,"ATTACK_UP"),
        (1,-1,"ATTACK_UP_RIGHT"),  (-1,0,"ATTACK_LEFT"),
        (1,0,"ATTACK_RIGHT"),      (-1,1,"ATTACK_DOWN_LEFT"),
        (0,1,"ATTACK_DOWN"),       (1,1,"ATTACK_DOWN_RIGHT"),
    ]
    for dc, dr, atk in attack_map:
        if grid[2+dr][2+dc] == "bot_enemy":
            return atk

    return "STAY"`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
        <MiniGrid rows={[
          [E, E, E, E, E],
          [E, E, EN, E, E],
          [E, E, ME, E, E],
          [E, E, E, E, E],
          [E, E, E, E, E],
        ]} />
        <p style={{ fontSize: 11, color: '#EF4444', margin: 0 }}>→ ATTACK_UP 반환</p>
      </div>
    ),
  },
  {
    badge: 'Step 4', title: '추격 & 생존', subtitle: '보스를 향해 거리를 좁히세요',
    description: '보스가 시야 내에 있지만 인접하지 않았다면, 보스 방향으로 이동해 거리를 좁히세요. 자기장도 잊지 마세요.',
    tips: [
      { icon: '🏃', text: '보스 방향으로 이동해 공격 사거리 안으로 들어오세요' },
      { icon: '🌀', text: '76틱부터 자기장이 수축합니다. zone_bounds 항상 확인' },
      { icon: '💡', text: '1대1이라 광물 경쟁이 적습니다. 에너지 관리에 집중하세요' },
    ],
    code: `def action(state: dict) -> str:
    my = state["my_bot"]
    x, y = my["position"]
    energy = my["energy"]
    grid = state["vision"]["grid"]
    min_x, min_y, max_x, max_y = state.get(
        "zone_bounds", (0, 0, 99, 99)
    )

    # 존 밖 복귀
    if not (min_x <= x <= max_x and min_y <= y <= max_y):
        cx, cy = (min_x+max_x)//2, (min_y+max_y)//2
        if abs(cx-x) >= abs(cy-y):
            return "MOVE_RIGHT" if cx > x else "MOVE_LEFT"
        return "MOVE_DOWN" if cy > y else "MOVE_UP"

    if energy <= 20:
        return "SHIELD"

    # 인접 공격
    for dc, dr, atk in [
        (0,-1,"ATTACK_UP"),(0,1,"ATTACK_DOWN"),
        (-1,0,"ATTACK_LEFT"),(1,0,"ATTACK_RIGHT"),
    ]:
        if grid[2+dr][2+dc] == "bot_enemy":
            return atk

    # 보스 방향으로 이동
    for row in range(5):
        for col in range(5):
            if grid[row][col] == "bot_enemy":
                dr, dc = row-2, col-2
                if abs(dc) >= abs(dr):
                    return "MOVE_RIGHT" if dc > 0 else "MOVE_LEFT"
                return "MOVE_DOWN" if dr > 0 else "MOVE_UP"

    return "STAY"`,
    renderVisual: () => (
      <MiniGrid rows={[
        [Z, Z, Z, Z, Z],
        [Z, E, EN, E, Z],
        [Z, ME, A('↑'), E, Z],
        [Z, E, E, E, Z],
        [Z, Z, Z, Z, Z],
      ]} />
    ),
  },
  {
    badge: 'Step 5', title: '완성 전략', subtitle: '공격·방어·생존을 조합하세요',
    description: '에너지 관리, 자기장 대응, 보스 추격을 조합하면 됩니다. \n보스가 강할수록 SHIELD 타이밍이 승패를 가릅니다.',
    tips: [
      { icon: '🏆', text: '보스를 쓰러뜨리면 즉시 게임 종료. 생존만으로도 점수가 됩니다' },
      { icon: '🔄', text: '보스는 패턴이 있습니다. 몇 번 관전하며 패턴을 파악하세요' },
      { icon: '⚡', text: '에너지를 80 이상으로 유지하면 더 공격적으로 싸울 수 있습니다' },
    ],
    code: `import random
def action(state: dict) -> str:
    my = state["my_bot"]
    x, y = my["position"]
    energy = my["energy"]
    grid = state["vision"]["grid"]
    min_x, min_y, max_x, max_y = state.get(
        "zone_bounds", (0, 0, 99, 99)
    )
    if not (min_x<=x<=max_x and min_y<=y<=max_y):
        cx,cy=(min_x+max_x)//2,(min_y+max_y)//2
        if abs(cx-x)>=abs(cy-y):
            return "MOVE_RIGHT" if cx>x else "MOVE_LEFT"
        return "MOVE_DOWN" if cy>y else "MOVE_UP"

    if energy <= 15:
        return "SHIELD"

    atk_dirs=[(-1,-1,"ATTACK_UP_LEFT"),(0,-1,"ATTACK_UP"),
              (1,-1,"ATTACK_UP_RIGHT"),(-1,0,"ATTACK_LEFT"),
              (1,0,"ATTACK_RIGHT"),(-1,1,"ATTACK_DOWN_LEFT"),
              (0,1,"ATTACK_DOWN"),(1,1,"ATTACK_DOWN_RIGHT")]
    for dc,dr,atk in atk_dirs:
        if grid[2+dr][2+dc]=="bot_enemy": return atk

    for row in range(5):
        for col in range(5):
            if grid[row][col]=="bot_enemy":
                dr,dc=row-2,col-2
                if abs(dc)>=abs(dr):
                    return "MOVE_RIGHT" if dc>0 else "MOVE_LEFT"
                return "MOVE_DOWN" if dr>0 else "MOVE_UP"

    return random.choice(["MOVE_UP","MOVE_DOWN",
                           "MOVE_LEFT","MOVE_RIGHT"])`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
        <MiniGrid rows={[
          [Z, Z, Z, Z, Z],
          [Z, E, EN, E, Z],
          [Z, ME, A('↑'), E, Z],
          [Z, E, MIN, E, Z],
          [Z, Z, Z, Z, Z],
        ]} />
        <p style={{ fontSize: 11, color: '#A855F7', margin: 0 }}>추격 + 존 생존 + 광물</p>
      </div>
    ),
  },
]

// ── 모의주식 단계 ─────────────────────────────────────────────────────────────

const STOCKS_STEPS: Step[] = [
  {
    badge: 'Step 1', title: '봇의 기본 구조', subtitle: '반환값이 dict인 점이 다릅니다',
    description: '배틀로얄과 달리 action()은 문자열이 아니라 딕셔너리를 \n반환합니다. 200턴 동안 주식을 사고팔아 총 자산을 \n최대화하는 게 목표입니다.',
    tips: [
      { icon: '💰', text: '초기 자본 1억 원. 200턴 후 총 자산이 가장 높은 봇이 우승' },
      { icon: '📋', text: '{"action": "HOLD"} 를 반환하면 아무것도 하지 않습니다' },
      { icon: '⚡', text: 'HOLD 중에도 현금은 매 틱 0.01% 이자가 붙습니다' },
    ],
    code: `def action(state: dict) -> dict:
    # 배틀로얄과 달리 dict를 반환합니다
    tick = state["tick"]  # 현재 턴 (1~200)

    # 아무것도 하지 않기
    return {"action": "HOLD"}`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <MiniStockChart bars={[60, 65, 58, 70, 68, 75, 72, 80]} />
        <p style={{ fontSize: 11, color: '#6B7280', margin: 0, textAlign: 'center' }}>200턴 주가 변동</p>
      </div>
    ),
  },
  {
    badge: 'Step 2', title: '시장 정보 읽기', subtitle: '주가와 뉴스가 핵심 데이터입니다',
    description: 'state["market"]["stocks"]에 15개 종목의 \n현재가·등락률이, state["market"]["news"]에 \n이번 틱 뉴스가 담겨 있습니다.',
    tips: [
      { icon: '📊', text: 'stocks는 리스트입니다. \nsymbol, price, change_pct 키를 확인하세요' },
      { icon: '📰', text: 'news는 매 10~20턴마다 생성됩니다. \nheadline, symbol 키가 있습니다' },
      { icon: '🤖', text: '[G] 접두사 뉴스는 Gemini AI가 생성한 것입니다' },
    ],
    code: `def action(state: dict) -> dict:
    market = state["market"]

    # 종목별 현재 주가 딕셔너리로 변환
    stocks = {s["symbol"]: s for s in market["stocks"]}

    # 뉴스 확인
    for news in market["news"]:
        sym     = news["symbol"]    # 관련 종목
        headline = news["headline"] # 뉴스 제목
        print(f"{sym}: {headline}")

    return {"action": "HOLD"}`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
        {[
          { sym: 'NeoChips', price: '₩142,300', chg: '+3.2%', up: true },
          { sym: 'AeroTech', price: '₩89,500',  chg: '-1.8%', up: false },
          { sym: 'DataCorp', price: '₩213,700', chg: '+0.5%', up: true },
        ].map(({ sym, price, chg, up }) => (
          <div key={sym} style={{
            display: 'flex', justifyContent: 'space-between',
            alignItems: 'center', fontSize: 11,
            background: 'rgba(255,255,255,.03)', borderRadius: 6,
            padding: '4px 8px',
          }}>
            <span style={{ color: '#D1D5DB' }}>{sym}</span>
            <span style={{ color: '#9CA3AF' }}>{price}</span>
            <span style={{ color: up ? '#4ADE80' : '#F87171', fontWeight: 600 }}>{chg}</span>
          </div>
        ))}
        <div style={{
          background: 'rgba(245,166,36,.1)', border: '1px solid rgba(245,166,36,.3)',
          borderRadius: 6, padding: '4px 8px', fontSize: 11, color: '#FFC76A',
        }}>
          📰 [G] NeoChips, 신규 반도체 계약 체결
        </div>
      </div>
    ),
  },
  {
    badge: 'Step 3', title: '매수 / 매도', subtitle: '타이밍이 수익을 결정합니다',
    description: 'BUY로 매수하고 SELL로 매도합니다. 수량과 종목을 \n지정해야 합니다. 보유 현금과 수량 범위를 넘으면 \n자동으로 무시됩니다.',
    tips: [
      { icon: '💳', text: 'BUY: 현금 내에서만 체결됩니다. 수수료 0.2% 발생' },
      { icon: '📤', text: 'SELL: 보유 수량을 초과하면 무시됩니다' },
      { icon: '📉', text: 'SHORT(공매도)는 신용점수 800+ 필요합니다' },
    ],
    code: `def action(state: dict) -> dict:
    my   = state["my_bot"]
    cash = my["cash"]
    stocks = {s["symbol"]: s
              for s in state["market"]["stocks"]}

    target = "NeoChips"
    stock  = stocks.get(target, {})
    price  = stock.get("price", 0)

    # 보유 현금의 10%만큼 매수
    qty = int(cash * 0.10 / (price * 1.002))
    if qty > 0:
        return {
            "action":   "BUY",
            "symbol":   target,
            "quantity": qty,
        }

    return {"action": "HOLD"}`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <MiniStockChart bars={[55, 60, 58, 65, 70, 68, 75, 80]} highlight={4} />
        <div style={{ display: 'flex', gap: 6 }}>
          <div style={{ flex: 1, background: 'rgba(74,222,128,.1)', border: '1px solid rgba(74,222,128,.3)', borderRadius: 6, padding: '4px 8px', fontSize: 11, color: '#4ADE80', textAlign: 'center' }}>
            BUY
          </div>
          <div style={{ flex: 1, background: 'rgba(248,113,113,.1)', border: '1px solid rgba(248,113,113,.3)', borderRadius: 6, padding: '4px 8px', fontSize: 11, color: '#F87171', textAlign: 'center' }}>
            SELL
          </div>
        </div>
      </div>
    ),
  },
  {
    badge: 'Step 4', title: '포트폴리오 관리', subtitle: '손절과 익절 기준을 만드세요',
    description: 'my_bot.portfolio에 보유 종목별 수량·평균단가·수익률(pnl_pct)이 담겨 있습니다. \n이를 기반으로 손절·익절 전략을 짭니다.',
    tips: [
      { icon: '📊', text: 'portfolio는 dict. \n키는 종목 심볼, 값은 quantity·pnl_pct 등' },
      { icon: '🔴', text: '−15% 이하면 손절 매도로 더 큰 손실을 막으세요' },
      { icon: '🟢', text: '+20% 이상이면 절반 익절로 이익을 실현하세요' },
    ],
    code: `def action(state: dict) -> dict:
    portfolio = state["my_bot"]["portfolio"]

    # 손절: 수익률 -15% 이하
    for sym, pos in portfolio.items():
        if pos["pnl_pct"] <= -15:
            return {
                "action":   "SELL",
                "symbol":   sym,
                "quantity": pos["quantity"],
            }

    # 익절: 수익률 +20% 이상, 절반만 매도
    for sym, pos in portfolio.items():
        if pos["pnl_pct"] >= 20:
            qty = pos["quantity"] // 2
            if qty > 0:
                return {
                    "action":   "SELL",
                    "symbol":   sym,
                    "quantity": qty,
                }

    return {"action": "HOLD"}`,
    renderVisual: () => <PortfolioVisual />,
  },
  {
    badge: 'Step 5', title: '뉴스 기반 전략', subtitle: '정보가 수익을 만듭니다',
    description: '뉴스 키워드로 호재·악재를 판단해 매수·매도를 결정합니다. [G] 뉴스는 AI가 생성한 신뢰도 높은 시그널입니다.',
    tips: [
      { icon: '📰', text: '"계약", "실적", "파트너십"은 보통 호재 신호입니다' },
      { icon: '⚠️', text: '"리콜", "적자", "소송"은 악재 신호. 보유 시 매도 검토' },
      { icon: '🤖', text: '[G] 뉴스는 5~10턴 동안 주가에 영향을 줍니다' },
    ],
    code: `def action(state: dict) -> dict:
    my   = state["my_bot"]
    cash = my["cash"]
    portfolio = my["portfolio"]
    stocks = {s["symbol"]: s
              for s in state["market"]["stocks"]}
    news = state["market"]["news"]

    BULLISH = ["계약", "실적", "파트너십", "출시", "[G]"]
    BEARISH  = ["리콜", "적자", "소송", "하락"]

    for item in news:
        sym = item["symbol"]
        hl  = item["headline"]

        # 호재 → 매수
        if any(k in hl for k in BULLISH):
            stock = stocks.get(sym, {})
            if stock.get("delisted") or sym in portfolio:
                continue
            price = stock["price"]
            qty = int(cash * 0.15 / (price * 1.002))
            if qty > 0:
                return {"action":"BUY",
                        "symbol":sym,"quantity":qty}

        # 악재 → 보유 중이면 매도
        if any(k in hl for k in BEARISH):
            if sym in portfolio:
                return {"action":"SELL","symbol":sym,
                        "quantity":portfolio[sym]["quantity"]}

    # 손절 / 익절
    for sym, pos in portfolio.items():
        if pos["pnl_pct"] <= -15:
            return {"action":"SELL","symbol":sym,
                    "quantity":pos["quantity"]}
        if pos["pnl_pct"] >= 20:
            qty = pos["quantity"] // 2
            if qty > 0:
                return {"action":"SELL","symbol":sym,
                        "quantity":qty}

    return {"action": "HOLD"}`,
    renderVisual: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
        <MiniStockChart bars={[60, 62, 65, 63, 70, 78, 82, 88]} highlight={5} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {[
            { label: '호재 키워드', tags: ['계약', '실적', '[G]'], color: '#4ADE80', bg: 'rgba(74,222,128,.1)' },
            { label: '악재 키워드', tags: ['리콜', '적자', '소송'], color: '#F87171', bg: 'rgba(248,113,113,.1)' },
          ].map(({ label, tags, color, bg }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 10, color: '#6B7280', width: 64 }}>{label}</span>
              <div style={{ display: 'flex', gap: 4 }}>
                {tags.map(t => (
                  <span key={t} style={{ fontSize: 10, color, background: bg, borderRadius: 4, padding: '1px 6px' }}>{t}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    ),
  },
]

// ── 모드별 설정 ───────────────────────────────────────────────────────────────

const MODE_CONFIG: Record<Mode, {
  label: string
  accent: string
  steps: Step[]
  returnRoute: string
  returnState?: object
}> = {
  'battle-royale': {
    label: '배틀로얄',
    accent: '#818CF8',
    steps: BR_STEPS,
    returnRoute: '/games/new/battle-royale',
  },
  'boss': {
    label: '보스전',
    accent: '#F05E70',
    steps: BOSS_STEPS,
    returnRoute: '/games/new/boss-battle',
  },
  'stocks': {
    label: '모의주식',
    accent: '#FFC76A',
    steps: STOCKS_STEPS,
    returnRoute: '/games/new/mock-stocks',
  },
}

// ── 코드 블록 ─────────────────────────────────────────────────────────────────


// ── 메인 ─────────────────────────────────────────────────────────────────────

export default function TutorialPage() {
  const navigate = useNavigate()
  const { mode = 'battle-royale' } = useParams<{ mode: string }>()
  const cfg = MODE_CONFIG[(mode as Mode)] ?? MODE_CONFIG['battle-royale']
  const [step, setStep] = useState(0)
  const cur = cfg.steps[step]
  const isLast = step === cfg.steps.length - 1
  const progress = ((step + 1) / cfg.steps.length) * 100

  function goNext() {
    if (isLast) {
      navigate(cfg.returnRoute, {
        state: { templateCode: cur.code },
      })
    } else {
      setStep(s => s + 1)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0D0F14',
      backgroundImage:
        'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px),' +
        'linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
      backgroundSize: '24px 24px',
      color: '#E8EAF0',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* 헤더 */}
      <header style={{
        position: 'sticky', top: 0, zIndex: 20,
        height: 56, padding: '0 24px',
        display: 'flex', alignItems: 'center', gap: 12,
        background: 'rgba(13,15,20,.92)',
        backdropFilter: 'blur(14px)',
        borderBottom: '1px solid rgba(255,255,255,.05)',
      }}>
        <button onClick={() => navigate(-1)} style={ghostBtn}>◀ 뒤로</button>
        <span style={{ color: '#374151' }}>|</span>
        <span style={{ fontWeight: 700 }}>{cfg.label} 튜토리얼</span>

        {/* 진행 바 */}
        <div style={{ flex: 1, margin: '0 24px', height: 3, background: '#1F2937', borderRadius: 9999 }}>
          <div style={{
            height: '100%', borderRadius: 9999,
            background: `linear-gradient(90deg, ${cfg.accent}, ${cfg.accent}aa)`,
            width: `${progress}%`,
            transition: 'width .4s ease',
            boxShadow: `0 0 8px ${cfg.accent}66`,
          }} />
        </div>

        {!isLast && (
          <button onClick={() => navigate(cfg.returnRoute)} style={{ ...ghostBtn, color: '#6B7280' }}>
            건너뛰기
          </button>
        )}
      </header>

      <main style={{
        flex: 1,
        maxWidth: 960, margin: '0 auto', width: '100%',
        padding: '36px 24px',
        display: 'flex', flexDirection: 'column', gap: 28,
      }}>

        {/* 스텝 닷 */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
          {cfg.steps.map((_, i) => (
            <button key={i} onClick={() => setStep(i)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px 0' }}>
              <div style={{
                height: 6, borderRadius: 9999,
                width: i === step ? 24 : 6,
                background: i === step ? cfg.accent : i < step ? '#4B5563' : '#1F2937',
                boxShadow: i === step ? `0 0 10px ${cfg.accent}99` : 'none',
                transition: 'all .3s ease',
              }} />
            </button>
          ))}
        </div>

        {/* 메인 카드 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 32 }}>
          {/* 왼쪽 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.1em', color: cfg.accent, textTransform: 'uppercase' }}>
                {cur.badge} / {cfg.steps.length}
              </span>
              <h2 style={{ fontSize: 26, fontWeight: 800, lineHeight: 1.2, margin: 0 }}>{cur.title}</h2>
              <p style={{ fontSize: 13, color: '#6B7280', margin: 0 }}>{cur.subtitle}</p>
            </div>

            <p style={{ fontSize: 14, color: '#D1D5DB', lineHeight: 1.7, margin: 0, whiteSpace: 'pre-line' }}>{cur.description}</p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 'auto' }}>
              {cur.tips.map((tip, i) => (
                <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <span style={{ fontSize: 16, lineHeight: 1, width: 22, flexShrink: 0 }}>{tip.icon}</span>
                  <p style={{ fontSize: 12, color: '#9CA3AF', lineHeight: 1.6, margin: 0, whiteSpace: 'pre-line' }}>{tip.text}</p>
                </div>
              ))}
            </div>
          </div>

          {/* 오른쪽 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{
              background: 'rgba(255,255,255,.03)',
              border: '1px solid rgba(255,255,255,.07)',
              borderRadius: 14, padding: '20px 24px',
              display: 'flex', flexDirection: 'column', gap: 10,
            }}>
              <p style={{ fontSize: 11, color: '#4B5563', margin: 0 }}>
                {mode === 'stocks' ? '시장 미리보기' : '시야 미리보기 (5×5)'}
              </p>
              {cur.renderVisual()}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <p style={{ fontSize: 11, color: '#4B5563', margin: 0 }}>이번 단계 코드</p>
              <PythonEditor
                value={cur.code}
                onChange={() => {}}
                readOnly
                height={`${Math.min(Math.max(cur.code.split('\n').length * 21 + 19, 100), 280)}px`}
              />
            </div>
          </div>
        </div>

        {/* 하단 네비게이션 */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          paddingTop: 20, borderTop: '1px solid #1F2937',
        }}>
          <button
            onClick={() => setStep(s => s - 1)}
            disabled={step === 0}
            style={{ ...ghostBtn, opacity: step === 0 ? 0.25 : 1, cursor: step === 0 ? 'not-allowed' : 'pointer' }}
          >
            ← 이전
          </button>

          <button onClick={goNext} style={{
            padding: '10px 28px', borderRadius: 12,
            fontSize: 14, fontWeight: 700, cursor: 'pointer', border: 'none',
            background: isLast
              ? `linear-gradient(135deg, ${cfg.accent}, ${cfg.accent}bb)`
              : `${cfg.accent}1a`,
            color: isLast ? (mode === 'stocks' ? '#000' : '#fff') : cfg.accent,
            boxShadow: isLast ? `0 0 28px ${cfg.accent}55` : 'none',
            transition: 'all .2s',
          }}>
            {isLast ? `🚀 이 코드로 게임 시작하기` : '다음 단계 →'}
          </button>
        </div>
      </main>
    </div>
  )
}

const ghostBtn: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer',
  color: '#9CA3AF', fontSize: 14, transition: 'color .2s',
}
