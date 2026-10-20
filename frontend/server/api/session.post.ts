import { issueLocalSession } from '../utils/access'
export default defineEventHandler(async (event) => {
  const body: { password?: unknown } = (await readBody(event).catch(() => ({}))) || {}
  const password = typeof body.password === 'string' ? body.password : ''
  issueLocalSession(event, password)
  return { connected: true }
})
