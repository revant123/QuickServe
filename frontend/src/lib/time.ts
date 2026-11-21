import { useEffect, useState } from 'react'

/** The current time, updated every `ms`. For countdowns ("Accept within 3:12"). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

/** "3:07" for 187 seconds; "0:00" once it's past. */
export function countdown(untilIso: string, now: number): string {
  const left = Math.max(0, Math.round((new Date(untilIso).getTime() - now) / 1000))
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`
}

export function secondsLeft(untilIso: string, now: number): number {
  return Math.round((new Date(untilIso).getTime() - now) / 1000)
}

/** "just now", "4 min ago", "2 h ago". */
export function ago(iso: string, now: number): string {
  const min = Math.floor((now - new Date(iso).getTime()) / 60_000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  return `${Math.floor(min / 60)} h ago`
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })
}

/** Today's date as YYYY-MM-DD in the browser's time zone (for <input type="date">). */
export function todayLocal(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}
