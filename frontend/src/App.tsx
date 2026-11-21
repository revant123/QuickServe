import { lazy, Suspense } from 'react'
import { Outlet, Route, Routes, useLocation } from 'react-router'
import { RequireAuth } from './auth/RequireAuth'
import { BottomNav, Loading } from './components/ui'
import { HomePage } from './pages/HomePage'
import { RestaurantPage } from './pages/RestaurantPage'
import { SearchPage } from './pages/SearchPage'
import { ArtDefs } from './theme/Art'

// Browsing screens load with the app. Checkout, orders and login are fetched
// the first time someone opens them, so the first visit downloads less.
const CartPage = lazy(() => import('./pages/CartPage').then((m) => ({ default: m.CartPage })))
const OrderPage = lazy(() => import('./pages/OrderPage').then((m) => ({ default: m.OrderPage })))
const OrdersPage = lazy(() => import('./pages/OrdersPage').then((m) => ({ default: m.OrdersPage })))
const LoginPage = lazy(() => import('./pages/AuthPages').then((m) => ({ default: m.LoginPage })))
const RegisterPage = lazy(() => import('./pages/AuthPages').then((m) => ({ default: m.RegisterPage })))
const ProfilePage = lazy(() => import('./pages/AuthPages').then((m) => ({ default: m.ProfilePage })))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then((m) => ({ default: m.NotFoundPage })))

function Shell() {
  const { pathname } = useLocation()
  // The bottom bar would sit on top of the checkout button and the menu's cart bar.
  const showNav = !pathname.startsWith('/r/') && pathname !== '/cart'
  return (
    <div className="app">
      <ArtDefs />
      <Suspense fallback={<Loading />}>
        <Outlet />
      </Suspense>
      {showNav && <BottomNav />}
    </div>
  )
}

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomePage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="r/:id" element={<RestaurantPage />} />
        <Route path="cart" element={<CartPage />} />
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route
          path="orders"
          element={
            <RequireAuth>
              <OrdersPage />
            </RequireAuth>
          }
        />
        <Route
          path="orders/:id"
          element={
            <RequireAuth>
              <OrderPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
