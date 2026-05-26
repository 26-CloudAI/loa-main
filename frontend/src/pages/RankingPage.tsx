import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8080/battleroyale'

interface RankingEntry {
  rank: number
  user_id: number
  username: string
  display_name: string
  elo: number
  wins: number
  losses: number
  games_played: number
  win_rate: number
}

function getTierLabel(elo: number): { label: string; color: string } {
  if (elo >= 2000) return { label: 'Grandmaster', color: 'text-red-400' }
  if (elo >= 1800) return { label: 'Master', color: 'text-purple-400' }
  if (elo >= 1600) return { label: 'Diamond', color: 'text-cyan-400' }
  if (elo >= 1450) return { label: 'Platinum', color: 'text-teal-400' }
  if (elo >= 1300) return { label: 'Gold', color: 'text-yellow-400' }
  if (elo >= 1150) return { label: 'Silver', color: 'text-gray-300' }
  if (elo >= 1000) return { label: 'Bronze', color: 'text-amber-600' }
  return { label: 'Iron', color: 'text-gray-500' }
}

const MUTED = '#5A6270'
const navBtn: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer',
  color: MUTED, fontSize: 13, padding: 0, transition: 'color .15s',
}

export default function RankingPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [rankings, setRankings] = useState<RankingEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/api/rankings`)
      .then((r) => {
        if (!r.ok) throw new Error(`서버 오류 (${r.status})`)
        return r.json()
      })
      .then((data) => setRankings(data.rankings ?? []))
      .catch((e) => setError(e instanceof Error ? e.message : '랭킹을 불러오지 못했습니다.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div style={{
      position: 'relative',
      minHeight: '100vh',
      background: '#0D0F14',
      color: '#E8EAF0',
      backgroundImage: 'linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px)',
      backgroundSize: '24px 24px',
    }}>
      <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        background: 'radial-gradient(ellipse 60% 70% at 50% 40%, rgba(99,102,241,.15) 0%, transparent 70%)',
      }} />
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

      <main className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold">리더보드</h2>
          <span className="text-sm text-gray-500">ELO 기준 전체 유저 랭킹</span>
        </div>

        {error && (
          <div className="mb-4 text-sm text-red-400 bg-red-500/10 rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <span className="text-gray-500 text-sm">불러오는 중...</span>
          </div>
        ) : rankings.length === 0 ? (
          <div className="flex justify-center py-20">
            <p className="text-gray-500 text-sm">아직 랭킹 데이터가 없습니다.</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-gray-700">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-800 text-gray-400 text-center">
                  <th className="px-2 py-3">순위</th>
                  <th className="px-4 py-3">유저</th>
                  <th className="px-4 py-3">티어</th>
                  <th className="px-4 py-3">ELO</th>
                  <th className="px-4 py-3">전적</th>
                  <th className="px-4 py-3">승률</th>
                  <th className="px-4 py-3">코드 보기</th>
                </tr>
              </thead>
              <tbody>
                {rankings.map((entry, i) => {
                  const tier = getTierLabel(entry.elo)
                  const isMe = user && entry.username === user.username
                  return (
                    <tr
                      key={entry.user_id}
                      className={`border-t transition-colors ${
                        isMe
                          ? 'border-l-4 border-l-indigo-400 border-t-gray-700 bg-indigo-600/25'
                          : 'border-t-gray-700 hover:bg-gray-800/60'
                      }`}
                    >
                      <td className="px-4 py-3 font-mono text-gray-400 text-center">
                        {i < 3 ? (
                          <span
                            className={
                              i === 0
                                ? 'text-yellow-400 font-bold'
                                : i === 1
                                ? 'text-gray-300 font-bold'
                                : 'text-amber-600 font-bold'
                            }
                          >
                            {entry.rank}
                          </span>
                        ) : (
                          entry.rank
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <div className={`font-medium ${isMe ? 'text-indigo-300' : 'text-white'}`}>
                          {entry.display_name}
                        </div>
                        <div className="text-xs text-gray-500">{entry.username}</div>
                      </td>
                      <td className={`px-4 py-3 text-center font-medium ${tier.color}`}>
                        {tier.label}
                      </td>
                      <td className="px-4 py-3 text-center font-mono font-semibold text-white">
                        {entry.elo}
                      </td>
                      <td className="px-4 py-3 text-center text-gray-300">
                        <span className="text-green-400">{entry.wins}승</span>
                        {' / '}
                        <span className="text-red-400">{entry.losses}패</span>
                      </td>
                      <td className="px-4 py-3 text-center text-gray-300">
                        {(entry.win_rate * 100).toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => navigate(`/users/${entry.user_id}/bots`)}
                          className="text-xs text-indigo-400 hover:text-indigo-300 underline underline-offset-2 transition-colors"
                        >
                          봇 코드
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  )
}
