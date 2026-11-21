import { useSyncExternalStore } from 'react'

/**
 * True while a CSS media query matches, updating when the window is resized.
 * For layout decisions CSS can't make alone, like showing three order columns
 * side by side instead of tabs. Keep the breakpoint in step with theme.css.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia?.(query)
      list?.addEventListener('change', onChange)
      return () => list?.removeEventListener('change', onChange)
    },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  )
}

export const DESKTOP = '(min-width: 1024px)'
