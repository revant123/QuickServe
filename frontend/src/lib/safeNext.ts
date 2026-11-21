/**
 * Where to go after logging in. Only paths on this site: "?next=https://evil.example"
 * or "?next=//evil.example" must not bounce someone to a look-alike page after a
 * real login (an "open redirect", in OWASP's list of unvalidated redirects).
 */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return '/'
  return next
}
