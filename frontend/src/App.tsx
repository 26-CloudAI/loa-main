import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import LandingPage from './pages/LandingPage'
import GamesPage from './pages/GamesPage'
import GameSelectPage from './pages/GameSelectPage'
import GameNewPage from './pages/GameNewPage'
import BossBattlePage from './pages/BossBattlePage'
import WatchPage from './pages/WatchPage'
import MockStocksNewPage from './pages/MockStocksNewPage'
import MockStocksWatchPage from './pages/MockStocksWatchPage'


function AppRoutes() {
  const { token } = useAuth()

  return (
    <Routes>
      {/* 이미 로그인 상태이면 /login → /games 리다이렉트 */}
      <Route
        path="/login"
        element={token ? <Navigate to="/games" replace /> : <LandingPage />}
      />
      <Route path="/games" element={<GamesPage />} />
      <Route path="/games/new" element={<GameSelectPage />} />
      <Route path="/games/new/battle-royale" element={<GameNewPage />} />
      <Route path="/games/new/boss-battle" element={<BossBattlePage />} />
      <Route path="/games/:game_id/watch" element={<WatchPage />} />
      <Route path="/games/new/mock-stocks" element={<MockStocksNewPage />} />
      <Route path="/games/:game_id/mock-stocks/watch" element={<MockStocksWatchPage />} />
      {/* 기본 진입점 */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
