import { useNavigate, useParams } from 'react-router-dom'
import GodotGame from '../game/GodotGame'
import { BR2_API_BASE } from '../br2'
import { useAuth } from '../context/AuthContext'

/**
 * BR2(Godot) 리플레이 페이지.
 * Godot 을 replay 모드로 띄우면 {BR2_API_BASE}/api/games/{id}/replay 를 받아
 * frame_player 로 재생한다(재생/일시정지/배속 컨트롤은 Godot 캔버스 안에 표시).
 */
export default function BattleRoyale2ReplayPage() {
  const navigate = useNavigate()
  const { game_id } = useParams()
  const { token } = useAuth()
  const matchId = game_id ?? ''
  const shortId = matchId ? matchId.slice(0, 8) : ''

  return (
    <div className="fixed inset-0 bg-gray-950 flex items-center justify-center p-6">
      {/* 상단 바 */}
      <div className="absolute top-3 left-4 z-50 flex items-center gap-2 rounded-xl bg-gray-900/85 backdrop-blur px-3 py-1.5 ring-1 ring-gray-700 text-sm">
        <button
          onClick={() => navigate('/games')}
          className="flex items-center gap-1 text-gray-300 hover:text-white transition-colors font-medium"
        >
          ◀ 나가기
        </button>
        <span className="text-gray-600">|</span>
        <span className="flex items-center gap-1.5 font-semibold text-indigo-300">
          🎬 배틀로얄 2D 리플레이
          {shortId && <span className="text-gray-500 font-mono text-xs">#{shortId}</span>}
        </span>
      </div>

      {/* 게임 화면 (정사각형) — 리플레이 모드 */}
      <div
        className="relative rounded-xl overflow-hidden ring-1 ring-gray-800 shadow-2xl h-full shrink-0"
        style={{ aspectRatio: '1 / 1', maxWidth: '100%' }}
      >
        <GodotGame matchId={matchId || undefined} replay apiBase={BR2_API_BASE} token={token} />
      </div>
    </div>
  )
}
