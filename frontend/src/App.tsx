import { useEffect, useMemo, useState } from 'react'
import { getAnalytics, getRecentEvents, scoreRisk } from './api/risk'
import { openLiveEventsSocket } from './api/ws'
import type { Analytics, RiskEvent, RiskPayload } from './types/risk'

const initialPayload: RiskPayload = {
  user_id: 'u-101',
  event_type: 'transaction',
  transaction_amount: 120,
  transaction_country: 'US',
  home_country: 'US',
  is_new_device: false,
  failed_login_attempts: 0,
  account_age_days: 800,
  credit_score: 760,
  debt_to_income: 0.22,
  chargeback_count_90d: 0,
  ip_reputation: 0.05,
  mode: 'sync',
  model_version: 'v1'
}

export default function App() {
  const [events, setEvents] = useState<RiskEvent[]>([])
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [selected, setSelected] = useState<RiskEvent | null>(null)
  const [payload, setPayload] = useState<RiskPayload>(initialPayload)
  const [error, setError] = useState<string>('')

  const connectionStatus = useMemo(() => (events.length ? 'Live' : 'Waiting'), [events.length])

  async function refreshData() {
    const [eventsResp, analyticsResp] = await Promise.all([getRecentEvents(), getAnalytics()])
    setEvents(eventsResp.events)
    setAnalytics(analyticsResp)
    if (!selected && eventsResp.events.length) {
      setSelected(eventsResp.events[0])
    }
  }

  useEffect(() => {
    refreshData().catch((err) => setError(String(err)))
    const socket = openLiveEventsSocket((message) => {
      if (message.type === 'risk_event') {
        const event = message.event as RiskEvent
        setEvents((current) => [event, ...current].slice(0, 50))
        setSelected((current) => current || event)
      }
      if (message.type === 'snapshot' && Array.isArray(message.events)) {
        setEvents(message.events)
      }
    })

    return () => socket.close()
  }, [])

  useEffect(() => {
    refreshData().catch(() => {})
  }, [events.length])

  async function runSimulation(preset: 'login' | 'transaction' | 'attack') {
    setError('')
    const next = { ...payload }

    if (preset === 'login') {
      next.event_type = 'login'
      next.transaction_amount = 20
      next.transaction_country = 'US'
      next.is_new_device = true
      next.failed_login_attempts = 2
      next.ip_reputation = 0.2
    }

    if (preset === 'transaction') {
      next.event_type = 'transaction'
      next.transaction_amount = 1800
      next.transaction_country = 'US'
      next.failed_login_attempts = 0
      next.chargeback_count_90d = 1
      next.ip_reputation = 0.12
    }

    if (preset === 'attack') {
      next.event_type = 'attack'
      next.transaction_amount = 9800
      next.transaction_country = 'NG'
      next.home_country = 'US'
      next.is_new_device = true
      next.failed_login_attempts = 7
      next.credit_score = 570
      next.debt_to_income = 0.71
      next.chargeback_count_90d = 4
      next.ip_reputation = 0.92
    }

    setPayload(next)
    try {
      await scoreRisk(next)
      await refreshData()
    } catch (err) {
      setError(String(err))
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>RiskGuard Console</h1>
        <div className="pill">Stream: {connectionStatus}</div>
      </header>

      <section className="cards">
        <div className="card"><span>Total</span><strong>{analytics?.total_events ?? 0}</strong></div>
        <div className="card"><span>Allow</span><strong>{analytics?.allow_count ?? 0}</strong></div>
        <div className="card"><span>Review</span><strong>{analytics?.review_count ?? 0}</strong></div>
        <div className="card"><span>Block</span><strong>{analytics?.block_count ?? 0}</strong></div>
        <div className="card"><span>Avg Score</span><strong>{analytics?.avg_risk_score ?? 0}</strong></div>
      </section>

      <section className="panel simulator">
        <h2>Event Simulator</h2>
        <div className="row">
          <button onClick={() => runSimulation('login')}>Simulate Login</button>
          <button onClick={() => runSimulation('transaction')}>Simulate Transaction</button>
          <button className="danger" onClick={() => runSimulation('attack')}>Simulate Attack</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
      </section>

      <section className="grid">
        <div className="panel">
          <h2>Live Risk Feed</h2>
          <table>
            <thead>
              <tr><th>User</th><th>Event</th><th>Score</th><th>Decision</th></tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id} onClick={() => setSelected(event)}>
                  <td>{event.user_id}</td>
                  <td>{event.event_type}</td>
                  <td>{event.risk_score}</td>
                  <td className={`decision ${event.decision}`}>{event.decision.toUpperCase()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel details">
          <h2>Risk Details</h2>
          {selected ? (
            <>
              <p><strong>User:</strong> {selected.user_id}</p>
              <p><strong>Score:</strong> {selected.risk_score}</p>
              <p><strong>Decision:</strong> <span className={`decision ${selected.decision}`}>{selected.decision.toUpperCase()}</span></p>
              <p><strong>Fraud:</strong> {selected.components.fraud_probability ?? 0}</p>
              <p><strong>Credit:</strong> {selected.components.credit_default_probability ?? 0}</p>
              <p><strong>Cyber:</strong> {selected.components.cyber_anomaly_probability ?? 0}</p>
              <p><strong>Factors:</strong> {selected.factors.join(', ') || 'none'}</p>
            </>
          ) : (
            <p>Select an event from the table.</p>
          )}
        </div>
      </section>
    </div>
  )
}
