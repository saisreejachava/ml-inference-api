import { apiBase } from './http'

export function openLiveEventsSocket(onMessage: (payload: any) => void) {
  const wsBase = apiBase.replace(/^http/, 'ws')
  const socket = new WebSocket(`${wsBase}/ws/live-events`)

  socket.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data))
    } catch {
      // ignore malformed messages
    }
  }

  return socket
}
