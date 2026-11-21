import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router'
import { useAuth } from './auth/AuthProvider'
import { homeFor } from './auth/RequireRole'
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
// Phase 14: the partner and rider apps are separate downloads. A customer never
// fetches their code, and they never fetch the customer's checkout.
const PartnerApp = lazy(() => import('./partner/PartnerApp').then((m) => ({ default: m.PartnerApp })))
const OrdersBoard = lazy(() => import('./partner/OrdersBoard').then((m) => ({ default: m.OrdersBoard })))
const MenuManager = lazy(() => import('./partner/MenuManager').then((m) => ({ default: m.MenuManager })))
const SalesPage = lazy(() => import('./partner/SalesPage').then((m) => ({ default: m.SalesPage })))
const OffersPage = lazy(() => import('./partner/OffersPage').then((m) => ({ default: m.OffersPage })))
const RiderApp = lazy(() => import('./rider/RiderApp').then((m) => ({ default: m.RiderApp })))
const RiderHome = lazy(() => import('./rider/RiderApp').then((m) => ({ default: m.RiderHome })))
const EarningsPage = lazy(() => import('./rider/RiderApp').then((m) => ({ default: m.EarningsPage })))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then((m) => ({ default: m.NotFoundPage })))

function Shell() {
  const { pathname } = useLocation()
  const { user } = useAuth()
  // Restaurant partners and riders have their own apps, as on Zomato and Swiggy.
  const home = homeFor(user?.role)
  if (home !== '/') return <Navigate to={home} replace />
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
      <Route
        path="partner"
        element={
          <Suspense fallback={<Loading />}>
            <PartnerApp />
          </Suspense>
        }
      >
        <Route index element={<OrdersBoard />} />
        <Route path="menu" element={<MenuManager />} />
        <Route path="sales" element={<SalesPage />} />
        <Route path="offers" element={<OffersPage />} />
      </Route>
      <Route
        path="rider"
        element={
          <Suspense fallback={<Loading />}>
            <RiderApp />
          </Suspense>
        }
      >
        <Route index element={<RiderHome />} />
        <Route path="earnings" element={<EarningsPage />} />
      </Route>
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
