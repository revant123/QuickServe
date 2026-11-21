/**
 * The one place the app talks to the API.
 *
 * Types come from the API's own contract: openapi.json is exported from FastAPI
 * (python -m scripts.export_openapi) and `npm run gen:api` turns it into
 * schema.d.ts. If the backend renames a field, this app stops compiling: the
 * mistake is caught by `tsc` instead of by a customer.
 */
import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schemas = components['schemas']

const TOKEN_KEY = 'qs.token'

/**
 * Where the login token lives: sessionStorage, not localStorage. It's gone when
 * the tab closes, and OWASP advises against keeping session tokens in
 * localStorage, because any injected script could read them. An httpOnly cookie
 * would be safer still; see the README for that trade-off.
 */
export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set(token: string) {
    try {
      sessionStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* private mode: the token simply isn't kept across reloads */
    }
  },
  clear() {
    try {
      sessionStorage.removeItem(TOKEN_KEY)
    } catch {
      /* nothing to clear */
    }
  },
}

/** Called when the API says the token is no longer valid (expired after 30 minutes, or logged out). */
let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = tokenStore.get()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  onResponse({ request, response }) {
    if (response.status === 401 && request.headers.has('Authorization')) onUnauthorized()
    return response
  },
}

// Same origin: in development Vite forwards /api to the API; in Kubernetes the
// Gateway does. The browser never makes a cross-origin call, so no CORS.
// fetch is looked up on every call (not captured once), so tests can stub it.
export const api = createClient<paths>({
  baseUrl: typeof window === 'undefined' ? '' : window.location.origin,
  fetch: (request) => globalThis.fetch(request),
})
api.use(auth)

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown
  /** The API's trace ID for this request (X-Trace-Id, Phase 15), if tracing is on. */
  readonly traceId: string | null
  constructor(status: number, message: string, body: unknown, traceId: string | null = null) {
    super(message)
    this.status = status
    this.body = body
    this.traceId = traceId
  }
}

/** Turn FastAPI's error body into one readable sentence. */
export function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      // A 422 from validation: [{loc: ["body", "email"], msg: "..."}]
      const first = detail[0] as { loc?: unknown[]; msg?: string }
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined
      return field ? `${String(field)}: ${first.msg ?? 'invalid'}` : (first.msg ?? 'Invalid input')
    }
  }
  if (status >= 500) return 'Something went wrong on our side. Please try again.'
  return `Request failed (${status})`
}

/** openapi-fetch returns {data} or {error}; screens want the data or an exception. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(
      result.response.status,
      errorMessage(result.error, result.response.status),
      result.error,
      result.response.headers.get('X-Trace-Id'),
    )
  }
  return result.data as T
}
