import { useState } from 'react'

type Mode = 'battle-royale' | 'boss' | 'stocks'

const CONTENT: Record<Mode, {
  sections: {
    title: string; sub?: string; footer?: string
    rows: { label: string; value: string; color?: string; dot?: string }[]
  }[]
  tips: { key: string; val: string }[]
}> = {
  'battle-royale': {
    sections: [
      {
        title: '액션', sub: '→ return 값',
        footer: '* = UP/DOWN/LEFT/RIGHT + 대각선',
        rows: [
          { label: 'MOVE_*',   value: '−2 EP', color: '#38BDF8' },
          { label: 'ATTACK_*', value: '−5 EP', color: '#F87171' },
          { label: 'MINE',     value: '−3 EP', color: '#FDE047' },
          { label: 'SHIELD',   value: '−3 EP', color: '#4ADE80' },
          { label: 'STAY',     value: '−1 EP', color: '#6B7280' },
        ],
      },
      {
        title: 'vision.grid', sub: '5×5 시야',
        footer: 'grid[2][2] = 내 위치 (중심)',
        rows: [
          { label: 'mineral',      value: '일반 광물', dot: '#EAB308' },
          { label: 'mineral_rare', value: '희귀 광물', dot: '#A855F7' },
          { label: 'bot_enemy',    value: '적 봇',     dot: '#EF4444' },
          { label: 'ME',           value: '내 위치',   dot: '#0EA5E9' },
          { label: 'empty',        value: '빈 칸',     dot: '#374151' },
        ],
      },
      {
        title: '점수',
        rows: [
          { label: '일반 광물', value: '+5',   color: '#FBBF24' },
          { label: '희귀 광물', value: '+20',  color: '#FBBF24' },
          { label: '킬',        value: '+30',  color: '#FBBF24' },
          { label: '방어 성공', value: '+10',  color: '#FBBF24' },
          { label: '생존/틱',   value: '+0.1', color: '#FBBF24' },
        ],
      },
    ],
    tips: [
      { key: 'MINE',     val: '이동 다음 틱에' },
      { key: '에너지=0', val: '즉시 사망' },
      { key: '76틱~',    val: '자기장 수축' },
      { key: '존 밖',    val: '매틱 −3 EP' },
    ],
  },
  'boss': {
    sections: [
      {
        title: 'action', sub: '→ return dict',
        footer: '매 결정 틱(0.1s) get_action(state)',
        rows: [
          { label: 'move_dir',   value: '[x,y]', color: '#38BDF8' },
          { label: 'aim_dir',    value: '[x,y]', color: '#38BDF8' },
          { label: 'attack',     value: 'bool',  color: '#F87171' },
          { label: 'guard',      value: 'bool',  color: '#4ADE80' },
          { label: 'dash',       value: 'bool',  color: '#A855F7' },
          { label: 'pickup',     value: 'bool',  color: '#FDE047' },
          { label: 'use_potion', value: 'bool',  color: '#FB923C' },
        ],
      },
      {
        title: 'state', sub: '주요 키',
        footer: '시야 반경 200px 내 객체만',
        rows: [
          { label: 'self',             value: 'pos·hp·atk' },
          { label: 'vision.enemies',   value: '보스',   dot: '#EF4444' },
          { label: 'vision.nodes',     value: '코인',   dot: '#EAB308' },
          { label: 'vision.items',     value: '아이템', dot: '#A855F7' },
          { label: 'zone',             value: '자기장', dot: '#38BDF8' },
        ],
      },
      {
        title: '점수',
        rows: [
          { label: '일반 코인', value: '+5',   color: '#FBBF24' },
          { label: '희귀 코인', value: '+20',  color: '#FBBF24' },
          { label: '보스 처치', value: '+100', color: '#FBBF24' },
          { label: '가드 성공', value: '+10',  color: '#FBBF24' },
          { label: '생존/초',   value: '+0.1', color: '#FBBF24' },
        ],
      },
    ],
    tips: [
      { key: '근접 사거리', val: '60px / 90°' },
      { key: '가드 쿨',     val: '10s · 대시 5s' },
      { key: '60s~',        val: '자기장 수축' },
      { key: '존 밖',       val: '2→3→5 dmg/s' },
    ],
  },
  'stocks': {
    sections: [
      {
        title: '액션', sub: '→ return dict',
        rows: [
          { label: 'BUY',     value: '즉시 매수',   color: '#4ADE80' },
          { label: 'SELL',    value: '즉시 매도',   color: '#F87171' },
          { label: 'SHORT',   value: '공매도',      color: '#F87171' },
          { label: 'COVER',   value: '공매도 청산', color: '#38BDF8' },
          { label: 'INQUIRY', value: '뉴스 힌트',   color: '#FDE047' },
          { label: 'HOLD',    value: '+0.01%/틱',  color: '#6B7280' },
        ],
      },
      {
        title: 'state 키',
        rows: [
          { label: 'my.cash',        value: '보유 현금', color: '#9CA3AF' },
          { label: 'my.total_value', value: '총 자산',   color: '#9CA3AF' },
          { label: 'my.portfolio',   value: '보유 종목', color: '#9CA3AF' },
          { label: 'market.stocks',  value: '전체 종목', color: '#9CA3AF' },
          { label: 'market.news',    value: '현재 뉴스', color: '#9CA3AF' },
        ],
      },
    ],
    tips: [
      { key: '수수료',   val: '매매 시 0.2%' },
      { key: '[G] 뉴스', val: '5~10턴 영향' },
      { key: '종료',     val: '200턴 후 총자산' },
      { key: 'SHORT',    val: '신용 800+ 필요' },
    ],
  },
}

// ── 컴포넌트 ──────────────────────────────────────────────────────────────────

export default function QuickRefPanel({ mode }: { mode: Mode }) {
  const key = `loa_quickref_closed_${mode}`
  const [open, setOpen] = useState(() => localStorage.getItem(key) !== '1')

  function close() { localStorage.setItem(key, '1'); setOpen(false) }
  function reopen() { localStorage.removeItem(key); setOpen(true) }

  const { sections, tips } = CONTENT[mode]

  return (
    // aside 자체에 width transition → 부모 flex-1(에디터)이 자연스럽게 확장됨
    <aside
      style={{
        width: open ? 208 : 28,
        flexShrink: 0,
        overflow: 'hidden',
        transition: 'width 320ms cubic-bezier(.4,0,.2,1)',
        ...(open
          ? { position: 'sticky', top: 80, alignSelf: 'flex-start' }
          : { alignSelf: 'center' }
        ),
      }}
    >
      {/* ── 열린 상태 ── */}
      <div style={{
        width: 208,
        display: open ? 'flex' : 'none',
        flexDirection: 'column', gap: 8,
      }}>
        {/* 헤더 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: 2 }}>
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', color: '#4B5563', textTransform: 'uppercase' }}>
            Quick Ref
          </span>
          <button
            type="button"
            onClick={close}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 11, color: '#4B5563', padding: '2px 0',
              transition: 'color .15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = '#9CA3AF')}
            onMouseLeave={e => (e.currentTarget.style.color = '#4B5563')}
          >
            닫기 ›
          </button>
        </div>

        {/* 섹션 */}
        {sections.map(sec => (
          <div key={sec.title} style={{ borderRadius: 10, overflow: 'hidden', border: '1px solid rgba(255,255,255,.07)' }}>
            <div style={{
              background: 'rgba(255,255,255,.04)', padding: '6px 10px',
              borderBottom: '1px solid rgba(255,255,255,.06)',
              display: 'flex', alignItems: 'baseline', gap: 6,
            }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#E5E7EB' }}>{sec.title}</span>
              {sec.sub && <span style={{ fontSize: 10, color: '#4B5563' }}>{sec.sub}</span>}
            </div>
            <div style={{ background: 'rgba(0,0,0,.25)' }}>
              {sec.rows.map(({ label, value, color, dot }, i) => (
                <div key={label} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '5px 10px',
                  borderTop: i > 0 ? '1px solid rgba(255,255,255,.04)' : 'none',
                }}>
                  {dot && <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot, flexShrink: 0 }} />}
                  <span style={{
                    fontFamily: 'monospace', fontSize: 10.5,
                    color: '#D1D5DB', flex: 1,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {label}
                  </span>
                  <span style={{ fontSize: 10, color: color ?? '#6B7280', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                    {value}
                  </span>
                </div>
              ))}
            </div>
            {sec.footer && (
              <div style={{ background: 'rgba(255,255,255,.02)', borderTop: '1px solid rgba(255,255,255,.05)', padding: '4px 10px' }}>
                <p style={{ fontSize: 9.5, color: '#374151', margin: 0 }}>{sec.footer}</p>
              </div>
            )}
          </div>
        ))}

        {/* 주의 팁 */}
        <div style={{
          borderRadius: 10, border: '1px solid rgba(251,191,36,.15)',
          background: 'rgba(251,191,36,.05)', padding: '8px 10px',
          display: 'flex', flexDirection: 'column', gap: 5,
        }}>
          <p style={{ fontSize: 10, fontWeight: 700, color: '#FCD34D', margin: 0 }}>주의</p>
          {tips.map(({ key: k, val }) => (
            <div key={k} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
              <span style={{ fontFamily: 'monospace', fontSize: 9.5, color: '#FDE68A', flexShrink: 0 }}>{k}</span>
              <span style={{ fontSize: 9.5, color: '#9CA3AF' }}>{val}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── 닫힌 상태: 세로 탭 ── */}
      <button
        type="button"
        onClick={reopen}
        style={{
          display: open ? 'none' : 'flex',
          width: 28, padding: '12px 0',
          background: 'none', border: 'none', cursor: 'pointer',
          alignItems: 'center', justifyContent: 'center',
        }}
        title="Quick Ref 열기"
      >
        <span style={{
          writingMode: 'vertical-rl', textOrientation: 'mixed',
          fontSize: 11, fontWeight: 700, letterSpacing: '0.1em',
          color: '#9CA3AF', userSelect: 'none',
          transition: 'color .15s',
        }}
          onMouseEnter={e => ((e.target as HTMLElement).style.color = '#E5E7EB')}
          onMouseLeave={e => ((e.target as HTMLElement).style.color = '#9CA3AF')}
        >
          REF ↑
        </span>
      </button>
    </aside>
  )
}
