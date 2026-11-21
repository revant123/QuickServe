import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler, tokenStore, unwrap, type Schemas } from '../api/client'

interface AuthApi {
  user: Schemas['UserOut'] | undefined
  loggedIn: boolean
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const Ctx = createContext<AuthApi | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [token, setToken] = useState<string | null>(() => tokenStore.get())

  const forget = useCallback(() => {
    tokenStore.clear()
    setToken(null)
    // Drop everything fetched as this user (orders, quotes), so the next person
    // on this device can't see it.
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'public' })
  }, [queryClient])

  useEffect(() => setUnauthorizedHandler(forget), [forget])

  const me = useQuery({
    queryKey: ['me', token],
    queryFn: async () => unwrap(await api.GET('/api/v1/users/me')),
    enabled: token !== null,
    staleTime: 5 * 60_000,
  })

  const login = useCallback(async (email: string, password: string) => {
    // The login endpoint takes a form (OAuth2 password flow), not JSON.
    const result = await api.POST('/api/v1/auth/login', {
      body: { username: email, password, scope: '' },
      bodySerializer: (body) => new URLSearchParams(body as Record<string, string>),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    const data = unwrap(result)
    tokenStore.set(data.access_token)
    setToken(data.access_token)
  }, [])

  const register = useCallback(
    async (name: string, email: string, password: string) => {
      unwrap(await api.POST('/api/v1/users', { body: { name, email, password, role: 'CUSTOMER' } }))
      await login(email, password)
    },
    [login],
  )

  const logout = useCallback(async () => {
    // Tell the server to revoke the token (Phase 3 keeps a deny-list in Redis),
    // then forget it here even if that call fails.
    try {
      await api.POST('/api/v1/auth/logout')
    } finally {
      forget()
    }
  }, [forget])

  const value = useMemo<AuthApi>(
    () => ({
      user: me.data,
      loggedIn: token !== null,
      loading: token !== null && me.isPending,
      login,
      register,
      logout,
    }),
    [me.data, me.isPending, token, login, register, logout],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
