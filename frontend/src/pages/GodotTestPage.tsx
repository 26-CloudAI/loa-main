import GodotGame from '../game/GodotGame'

/**
 * Phase A 검증용 페이지 — 새 Godot 배틀로얄을 전체화면 iframe 으로 띄움.
 * 라우트: /godot-test
 * BattleRoyale2 WS 서버(8765)가 떠 있으면 Python 봇 매치, 없으면 데모 AI 폴백.
 */
export default function GodotTestPage() {
  return (
    <div style={{ position: 'fixed', inset: 0, background: '#111' }}>
      <GodotGame />
    </div>
  )
}
