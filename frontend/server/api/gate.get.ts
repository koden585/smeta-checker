import { assertLocal, workspaceGate } from '../utils/access'
export default defineEventHandler((event) => {
  assertLocal(event)
  return workspaceGate()
})
