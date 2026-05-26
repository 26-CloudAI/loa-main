import { useRef } from 'react'

interface Props {
  /** public/godot/index.html 기준 경로. 기본은 라이브 데모 빌드. */
  src?: string
  /** 매치 식별자. Godot 이 {wsBase}{matchId} 로 연결. 없으면 게임이 'dev' 사용. */
  matchId?: string
  /** WS 매치 베이스(끝 /match/). 배포 백엔드 주소를 Godot 에 주입. 없으면 Godot 내부 기본(localhost). */
  wsBase?: string
  /** Firebase 토큰. Godot 이 WS ?token= 로 전달 (인증된 게임 관전용). */
  token?: string | null
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
export default function GodotGame({ src = '/godot/index.html', matchId, wsBase, token, width = '100%', height = '100%' }: Props) {
  const ref = useRef<HTMLIFrameElement | null>(null)
  // 쿼리(?) 대신 해시(#) 사용 — Godot HTML5 정적 파일 로딩(.pck/.wasm) 경로 해석을 방해하지 않음
  // match + ws + token 을 해시 파라미터로 전달 (ws=배포 백엔드 주소, token=WS 인증)
  let fullSrc = src
  const params: string[] = []
  if (matchId) params.push(`match=${encodeURIComponent(matchId)}`)
  if (wsBase) params.push(`ws=${encodeURIComponent(wsBase)}`)
  if (token) params.push(`token=${encodeURIComponent(token)}`)
  if (params.length) fullSrc = `${src}#${params.join('&')}`
  return (
    <iframe
      ref={ref}
      src={fullSrc}
      title="LOA Battle Royale (Godot)"
      width={width}
      height={height}
      style={{ border: 'none', display: 'block', background: '#1a1a1a' }}
      allow="autoplay; fullscreen"
    />
  )
}
