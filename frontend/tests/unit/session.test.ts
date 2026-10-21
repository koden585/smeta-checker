import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { H3Event } from 'h3'
import { issueLocalSession, requireSession } from '../../server/utils/access'

const HOST = 'smeta.test'
let currentCookie = ''
let issued: string[] = []

// server/utils/access.ts reads Nuxt server auto-imports only inside function
// bodies, so stubbing the globals at module top level (before any call) is
// safe even with the static import above.
vi.stubGlobal('getRequestURL', () => new URL(`http://${HOST}/api/session`))
vi.stubGlobal('getHeader', (_event: unknown, name: string) =>
  name.toLowerCase() === 'origin' ? `http://${HOST}` : undefined,
)
vi.stubGlobal('getCookie', () => currentCookie)
vi.stubGlobal('setCookie', (_event: unknown, _name: string, value: string) => {
  issued.push(value)
  currentCookie = value
})
vi.stubGlobal('setHeader', () => {})
vi.stubGlobal('createError', (opts: { statusCode?: number; statusMessage?: string }) => {
  throw Object.assign(new Error(opts.statusMessage || 'error'), { statusCode: opts.statusCode })
})

const event = {} as H3Event

function statusOf(fn: () => void): number {
  try {
    fn()
  } catch (error) {
    if (error && typeof error === 'object' && 'statusCode' in error)
      return typeof error.statusCode === 'number' ? error.statusCode : 0
    return 0
  }
  return 200
}

describe('workspace session (world mode)', () => {
  const env = process.env
  beforeEach(() => {
    process.env = { ...env, NUXT_PUBLIC_HOST: HOST, WORKSPACE_PASSWORD: 'stand-secret' }
    currentCookie = ''
    issued = []
  })
  afterEach(() => {
    process.env = env
  })

  it('issues a session with the password, then renews it via connect() without one', () => {
    expect(statusOf(() => issueLocalSession(event, 'stand-secret'))).toBe(200)
    expect(issued).toHaveLength(1)
    // What every page does on load: POST /api/session with an empty password
    // and the stored cookie. Must renew (200), not bounce to /login.
    expect(statusOf(() => issueLocalSession(event, ''))).toBe(200)
    expect(issued).toHaveLength(2)
    expect(statusOf(() => requireSession(event))).toBe(200)
  })

  it('still rejects a missing cookie and a wrong password', () => {
    expect(statusOf(() => issueLocalSession(event, ''))).toBe(401)
    expect(statusOf(() => issueLocalSession(event, 'wrong'))).toBe(401)
  })

  it('rejects an expired or forged cookie even with an empty password', () => {
    expect(statusOf(() => issueLocalSession(event, 'stand-secret'))).toBe(200)
    currentCookie = '1.deadbeef.forged'
    expect(statusOf(() => issueLocalSession(event, ''))).toBe(401)
    expect(statusOf(() => requireSession(event))).toBe(401)
    currentCookie = `${Date.now() + 86400000}.deadbeef.wrongsig`
    expect(statusOf(() => issueLocalSession(event, ''))).toBe(401)
    expect(statusOf(() => requireSession(event))).toBe(401)
  })
})
