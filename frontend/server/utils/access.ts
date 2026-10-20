import { createHash, randomBytes, timingSafeEqual } from 'node:crypto'
import type { H3Event } from 'h3'
const localSecret = randomBytes(32)

function publicHost(): string {
  return (process.env.NUXT_PUBLIC_HOST || '').trim().toLowerCase()
}

function workspacePassword(): string {
  return (process.env.WORKSPACE_PASSWORD || '').trim()
}

/**
 * Access modes (see docs/docker-quickstart.md):
 * - localhost (default): loopback peer + loopback Host, session without password.
 * - intranet: NUXT_PUBLIC_HOST=<lan-ip-or-name>, port on LAN; session without
 *   password, but only from the exact Host. Anyone on the LAN segment with the
 *   address can open the UI — this mode trusts the local network.
 * - world: NUXT_PUBLIC_HOST=<domain> + WORKSPACE_PASSWORD=<secret>.
 *   Session requires the password; serve strictly behind TLS (reverse proxy).
 */
export function assertLocal(event: H3Event) {
  const host = publicHost()
  if (!host) {
    // Compose publishes the port on host loopback only; inside the container
    // the peer is the Docker gateway, not 127.0.0.1. NUXT_TRUST_PROXY=1 skips
    // the peer check but keeps Host allowlist, same-origin and session.
    // Never set it when the port is reachable from an untrusted network.
    if (process.env.NUXT_TRUST_PROXY !== '1') {
      const address = event.node.req.socket.remoteAddress
      if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(address || ''))
        throw createError({ statusCode: 403, statusMessage: 'Доступен только локальный стенд' })
    }
    const url = getRequestURL(event)
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
      throw createError({ statusCode: 403, statusMessage: 'Недопустимый адрес' })
    if (!['GET', 'HEAD'].includes(event.method) && getHeader(event, 'origin') !== url.origin)
      throw createError({ statusCode: 403, statusMessage: 'Запрос должен поступить из приложения' })
    return
  }
  const url = getRequestURL(event)
  if (url.hostname.toLowerCase() !== host)
    throw createError({ statusCode: 403, statusMessage: 'Недопустимый адрес' })
  if (!['GET', 'HEAD'].includes(event.method)) {
    const origin = getHeader(event, 'origin') || ''
    let originHost = ''
    try {
      originHost = new URL(origin).hostname.toLowerCase()
    } catch {
      throw createError({ statusCode: 403, statusMessage: 'Запрос должен поступить из приложения' })
    }
    if (originHost !== host)
      throw createError({ statusCode: 403, statusMessage: 'Запрос должен поступить из приложения' })
  }
}

function signature(value: string) {
  return createHash('sha256').update(localSecret).update(value).digest('hex')
}

function passwordOk(presented: string): boolean {
  const expected = Buffer.from(workspacePassword())
  const received = Buffer.from((presented || '').trim())
  return (
    expected.length > 0 &&
    received.length === expected.length &&
    timingSafeEqual(received, expected)
  )
}

function issueSession(event: H3Event) {
  const value = String(Date.now() + 86400000) + '.' + randomBytes(24).toString('hex')
  setCookie(event, 'kdfp_workspace', value + '.' + signature(value), {
    httpOnly: true,
    sameSite: 'strict',
    path: '/',
    maxAge: 86400,
    secure: getRequestURL(event).protocol === 'https:',
  })
  setHeader(event, 'Cache-Control', 'no-store')
}

export function issueLocalSession(event: H3Event, password = '') {
  assertLocal(event)
  if (workspacePassword() && !passwordOk(password))
    throw createError({ statusCode: 401, statusMessage: 'Неверный пароль' })
  issueSession(event)
}

export function requireSession(event: H3Event) {
  assertLocal(event)
  const cookie = getCookie(event, 'kdfp_workspace') || ''
  const parts = cookie.split('.')
  const received = Buffer.from(parts[2] || ''),
    expected = Buffer.from(signature(parts.slice(0, 2).join('.')))
  if (
    parts.length !== 3 ||
    Number(parts[0]) < Date.now() ||
    received.length !== expected.length ||
    !timingSafeEqual(received, expected)
  )
    throw createError({ statusCode: 401, statusMessage: 'Обновите подключение' })
}

export function workspaceGate(): { locked: boolean } {
  return { locked: workspacePassword().length > 0 }
}
