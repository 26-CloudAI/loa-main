import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import PythonEditor from '../components/PythonEditor'

const MUTED = '#5A6270'
const navBtn: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer',
  color: MUTED, fontSize: 13, padding: 0, transition: 'color .15s',
}

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'

const MODE_STYLE: Record<string, string> = {
  '배틀로얄': 'bg-indigo-600/30 text-indigo-300 border border-indigo-600/50',
  '보스전':   'bg-red-700/30 text-red-300 border border-red-700/50',
  '모의주식': 'bg-emerald-600/30 text-emerald-300 border border-emerald-600/50',
}

interface BotInfo {
  id: number
  name: string
  game_mode: string | null
  game_name: string | null
  code: string | null
  is_public: boolean
  version: number
  wins: number
  losses: number
  games_played: number
  updated_at: string
}

interface UserInfo {
  user_id: number
  username: string
  display_name: string
  elo: number
  wins: number
  losses: number
  games_played: number
}

export default function UserBotDetailPage() {
  const { user_id } = useParams<{ user_id: string }>()
  const navigate = useNavigate()
  const { user, token, logout } = useAuth()

  const [userInfo, setUserInfo] = useState<UserInfo | null>(null)
  const [bots, setBots] = useState<BotInfo[]>([])
  const [selectedBot, setSelectedBot] = useState<BotInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user_id) return
    fetch(`${API_BASE}/api/users/${user_id}/bots`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error(`서버 오류 (${r.status})`)
        return r.json()
      })
      .then((data) => {
        setUserInfo(data.user)
        setBots(data.bots ?? [])
        if (data.bots?.length > 0) setSelectedBot(data.bots[0])
      })
      .catch((e) => setError(e instanceof Error ? e.message : '봇 정보를 불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }, [user_id])

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0D0F14',
      color: '#E8EAF0',
      backgroundImage: 'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
      backgroundSize: '24px 24px',
    }}>
      <nav style={{
        background: 'rgba(13,15,20,.92)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        height: 56,
        padding: '0 28px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        position: 'sticky',
        top: 0,
        zIndex: 20,
      }}>
        <button
          onClick={() => navigate('/games')}
          style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          <span style={{ color: '#E8334A', fontSize: 16, lineHeight: 1 }}>◆</span>
          <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.1em', color: '#F0EBFF' }}>LEAGUE OF AGENTS</span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
          <button onClick={() => navigate('/rankings')} style={navBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>리더보드</button>
          <button onClick={() => navigate('/games/list')} style={navBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>게임 목록</button>
          {user && (
            <button
              onClick={() => navigate('/mypage')}
              style={{ ...navBtn, display: 'flex', alignItems: 'center', gap: 6, color: '#F0EBFF' }}
            >
              {user.display_name ?? user.username}
              <span style={{
                padding: '1px calc(6px - 0.05em) 1px 6px',
                fontSize: 10, fontWeight: 500,
                background: 'rgba(155,89,245,.15)', color: '#C8A8FF',
                border: '1px solid rgba(155,89,245,.35)',
                borderRadius: 4, letterSpacing: '0.05em',
              }}>
                {user.role}
              </span>
            </button>
          )}
          <button onClick={handleLogout} style={navBtn} onMouseEnter={e => (e.currentTarget.style.color = '#F0EBFF')} onMouseLeave={e => (e.currentTarget.style.color = MUTED)}>로그아웃</button>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-6 py-8">

        {error && (
          <div className="mb-4 text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <span className="text-gray-500 text-sm">불러오는 중...</span>
          </div>
        ) : (
          <>
            {/* 유저 프로필 카드 */}
            {userInfo && (
              <div className="bg-gray-800 border border-gray-700 rounded-xl px-6 py-5 mb-6 flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold">{userInfo.display_name}</h2>
                  <p className="text-sm text-gray-500">{userInfo.username}</p>
                </div>
                <div className="flex items-center gap-6 text-sm">
                  <div className="text-center">
                    <div className="text-xl font-bold text-indigo-400">{userInfo.elo}</div>
                    <div className="text-xs text-gray-500">ELO</div>
                  </div>
                  <div className="text-center">
                    <div className="text-lg font-semibold text-green-400">{userInfo.wins}</div>
                    <div className="text-xs text-gray-500">승</div>
                  </div>
                  <div className="text-center">
                    <div className="text-lg font-semibold text-red-400">{userInfo.losses}</div>
                    <div className="text-xs text-gray-500">패</div>
                  </div>
                  <div className="text-center">
                    <div className="text-lg font-semibold text-gray-300">{userInfo.games_played}</div>
                    <div className="text-xs text-gray-500">총 게임</div>
                  </div>
                </div>
              </div>
            )}

            {bots.length === 0 ? (
              <div className="flex justify-center py-16">
                <p className="text-gray-500 text-sm">공개된 봇이 없습니다.</p>
              </div>
            ) : (
              <div className="flex gap-4 h-[600px]">
                {/* 봇 목록 */}
                <div className="w-56 shrink-0 flex flex-col gap-2 overflow-y-auto">
                  {bots.map((bot) => (
                    <button
                      key={bot.id}
                      onClick={() => setSelectedBot(bot)}
                      className={`text-left rounded-lg px-4 py-3 border transition-colors ${
                        selectedBot?.id === bot.id
                          ? 'bg-indigo-600/30 border-indigo-500 text-white'
                          : 'bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1.5">
                        <span className="font-medium text-sm truncate">{bot.name}</span>
                        {bot.game_mode && (
                          <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full ${MODE_STYLE[bot.game_mode] ?? 'bg-gray-600/20 text-gray-400'}`}>
                            {bot.game_mode}
                          </span>
                        )}
                      </div>
                      {bot.game_name && (
                        <div className="text-xs text-gray-500 mt-0.5 truncate">{bot.game_name}</div>
                      )}
                      <div className="text-xs mt-1 flex items-center gap-1.5">
                        {bot.games_played === 0 ? (
                          <span className="text-gray-500">미경기</span>
                        ) : bot.wins > 0 ? (
                          <span className="text-green-400">승</span>
                        ) : (
                          <span className="text-red-400">패</span>
                        )}
                        {!bot.is_public && (
                          <span className="text-gray-600">🔒</span>
                        )}
                      </div>
                    </button>
                  ))}
                </div>

                {/* 코드 뷰어 */}
                {selectedBot && (
                  <div className="flex-1 flex flex-col bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
                    <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
                      <div>
                        <span className="font-medium">{selectedBot.name}</span>
                        <span className="ml-2 text-xs text-gray-500">v{selectedBot.version}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {selectedBot.game_mode && (
                          <span className={`text-xs px-2 py-0.5 rounded-full ${MODE_STYLE[selectedBot.game_mode] ?? 'bg-gray-600/20 text-gray-400'}`}>
                            {selectedBot.game_mode}
                          </span>
                        )}
                        <span className={`text-xs px-2 py-0.5 rounded-full ${selectedBot.is_public ? 'bg-green-600/20 text-green-400 border border-green-600/50' : 'bg-gray-600/20 text-gray-400 border border-gray-600/50'}`}>
                          {selectedBot.is_public ? '공개' : '비공개'}
                        </span>
                      </div>
                    </div>
                    <div className="flex-1 overflow-hidden">
                      {selectedBot.code ? (
                        <PythonEditor
                          value={selectedBot.code}
                          onChange={() => {}}
                          readOnly
                          height="520px"
                        />
                      ) : (
                        <div className="flex items-center justify-center h-full">
                          <p className="text-gray-500 text-sm">🔒 비공개 코드입니다.</p>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
