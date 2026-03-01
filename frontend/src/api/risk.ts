import { http } from './http'
import type { Analytics, RiskEvent, RiskPayload } from '../types/risk'

export async function scoreRisk(payload: RiskPayload) {
  return http<Record<string, unknown>>('/risk/score', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function getRecentEvents() {
  return http<{ events: RiskEvent[] }>('/events/recent?limit=50')
}

export async function getAnalytics() {
  return http<Analytics>('/analytics')
}
