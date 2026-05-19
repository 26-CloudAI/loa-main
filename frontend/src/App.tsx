import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import LandingPage from './pages/LandingPage'
import AuthPage from './pages/AuthPage'
import MainPage from './pages/MainPage'
import GamesPage from './pages/GamesPage'
import GameSelectPage from './pages/GameSelectPage'
import GameNewPage from './pages/GameNewPage'
import BossBattlePage from './pages/BossBattlePage'
import WatchPage from './pages/WatchPage'
import MockStocksNewPage from './pages/MockStocksNewPage'
import MockStocksWatchPage from './pages/MockStocksWatchPage'
import MockStocksResultPage from './pages/MockStocksResultPage'
import BattleRoyaleReplayPage from './pages/BattleRoyaleReplayPage'
import MockStocksReplayPage from './pages/MockStocksReplayPage'
import RankingPage from './pages/RankingPage'
import UserBotDetailPage from './pages/UserBotDetailPage'
import MyPage from './pages/MyPage'

function LoadingScreen() {
  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-gray-400 text-sm">불러오는 중...</p>
      </div>
    </div>
  )
}

function IncompleteScreen() {
  const { authError, token, logout } = useAuth()

  const isNetworkError = token !== null  // token이 있으면 Firebase OK지만 서버 불가 상태

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-gray-800 rounded-2xl shadow-xl p-6 flex flex-col gap-4 text-center">
        <div className="text-3xl">⚠️</div>
        <p className="text-white font-medium">
          {isNetworkError ? '서버 연결 오류' : '회원가입 미완료'}
        </p>
        <p className="text-gray-400 text-sm">
          {authError ?? '알 수 없는 오류가 발생했습니다.'}
        </p>
        {isNetworkError ? (
          <div className="flex flex-col gap-2 mt-2">
            <button
              onClick={() => window.location.reload()}
              className="bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg py-2 transition-colors"
            >
              새로고침
            </button>
            <button
              onClick={logout}
              className="bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm font-medium rounded-lg py-2 transition-colors"
            >
              로그아웃
            </button>
          </div>
        ) : (
          <button
            onClick={() => window.location.replace('/login')}
            className="mt-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg py-2 transition-colors"
          >
            회원가입 하러 가기
          </button>
        )}
      </div>
    </div>
  )
}

function AppRoutes() {
  const { token, authStatus } = useAuth()

  if (authStatus === 'loading') return <LoadingScreen />
  if (authStatus === 'incomplete') return <IncompleteScreen />

  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      {/* 이미 로그인 상태이면 /login → /games 리다이렉트 */}
      <Route
        path="/login"
        element={token ? <Navigate to="/games" replace /> : <AuthPage />}
      />
      <Route path="/games" element={<MainPage />} />
      <Route path="/games/list" element={<GamesPage />} />
      <Route path="/games/new" element={<GameSelectPage />} />
      <Route path="/games/new/battle-royale" element={<GameNewPage />} />
      <Route path="/games/new/boss-battle" element={<BossBattlePage />} />
      <Route path="/games/:game_id/watch" element={<WatchPage />} />
      <Route path="/games/new/mock-stocks" element={<MockStocksNewPage />} />
      <Route path="/games/:game_id/mock-stocks/watch" element={<MockStocksWatchPage />} />
      <Route path="/games/:game_id/mock-stocks/result" element={<MockStocksResultPage />} />
      <Route path="/games/:game_id/replay" element={<BattleRoyaleReplayPage />} />
      <Route path="/games/:game_id/mock-stocks/replay" element={<MockStocksReplayPage />} />
      <Route path="/rankings" element={<RankingPage />} />
      <Route path="/users/:user_id/bots" element={<UserBotDetailPage />} />
      <Route path="/mypage" element={<MyPage />} />
      {/* 기본 진입점 */}
      <Route path="*" element={<Navigate to="/" replace />} />
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
