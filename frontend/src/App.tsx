import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import LandingPage from './pages/LandingPage'
import GamesPage from './pages/GamesPage'
import GameNewPage from './pages/GameNewPage'
import WatchPage from './pages/WatchPage'

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
      <Route path="/games/new" element={<GameNewPage />} />
      <Route path="/games/:game_id/watch" element={<WatchPage />} />
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
