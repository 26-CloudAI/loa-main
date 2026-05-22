import { useRef } from 'react'

interface Props {
  /** public/godot/index.html 기준 경로. 기본은 라이브 데모 빌드. */
  src?: string
  width?: number | string
  height?: number | string
}

/**
 * 새 Godot(HTML5) 배틀로얄 게임을 iframe 으로 임베드.
 * - public/godot/index.html (Godot HTML5 export 산출물) 을 로드
 * - 게임은 자체적으로 BattleRoyale2 WS(기본 ws://127.0.0.1:8765)에 연결,
 *   서버가 없으면 내부 데모 AI 로 폴백
 * - Phase A: 라이브 데모 임베드 검증용. game_id/리플레이 연동은 Phase B 이후.
 */
export default function GodotGame({ src = '/godot/index.html', width = '100%', height = '100%' }: Props) {
  const ref = useRef<HTMLIFrameElement | null>(null)
  return (
    <iframe
      ref={ref}
      src={src}
      title="LOA Battle Royale (Godot)"
      width={width}
      height={height}
      style={{ border: 'none', display: 'block', background: '#1a1a1a' }}
      allow="autoplay; fullscreen"
    />
  )
}
