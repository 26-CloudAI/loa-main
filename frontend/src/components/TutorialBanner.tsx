import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

type Mode = 'battle-royale' | 'boss' | 'stocks'

const LABEL: Record<Mode, string> = {
  'battle-royale': '배틀로얄',
  'boss': '보스전',
  'stocks': '모의주식',
}

export default function TutorialBanner({ mode }: { mode: Mode }) {
  const key = `loa_tutorial_dismissed_${mode}`
  const [visible, setVisible] = useState(() => localStorage.getItem(key) !== '1')
  const navigate = useNavigate()

  if (!visible) return null

  function dismiss() {
    localStorage.setItem(key, '1')
    setVisible(false)
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      gap: 12, padding: '10px 16px',
      background: 'rgba(99,102,241,.08)',
      border: '1px solid rgba(99,102,241,.25)',
      borderRadius: 12,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 16 }}>📖</span>
        <p style={{ fontSize: 13, color: '#A5B4FC', margin: 0 }}>
          <span style={{ color: '#E0E7FF', fontWeight: 600 }}>{LABEL[mode]} 처음이신가요?</span>
          {'  '}단계별 튜토리얼로 봇 작성법을 익혀보세요.
        </p>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <button
          type="button"
          onClick={() => navigate(`/tutorial/${mode}`)}
          style={{
            padding: '5px 14px', borderRadius: 8,
            background: 'rgba(99,102,241,.2)',
            border: '1px solid rgba(99,102,241,.4)',
            color: '#A5B4FC', fontSize: 12, fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          튜토리얼 보기
        </button>
        <button
          type="button"
          onClick={dismiss}
          style={{
            background: 'none', border: 'none',
            color: '#4B5563', fontSize: 16, cursor: 'pointer',
            lineHeight: 1, padding: '2px 4px',
          }}
        >
          ✕
        </button>
      </div>
    </div>
  )
}
