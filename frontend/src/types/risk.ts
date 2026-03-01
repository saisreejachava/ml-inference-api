export type RiskEvent = {
  id: string
  timestamp: string
  user_id: string
  event_type: string
  decision: 'allow' | 'review' | 'block'
  risk_score: number
  transaction_amount: number | null
  country: string | null
  factors: string[]
  components: {
    fraud_probability?: number
    credit_default_probability?: number
    cyber_anomaly_probability?: number
  }
}

export type RiskPayload = {
  user_id: string
  event_type: string
  transaction_amount: number
  transaction_country: string
  home_country: string
  is_new_device: boolean
  failed_login_attempts: number
  account_age_days: number
  credit_score: number
  debt_to_income: number
  chargeback_count_90d: number
  ip_reputation: number
  mode: 'sync' | 'async'
  model_version: string
}

export type Analytics = {
  total_events: number
  allow_count: number
  review_count: number
  block_count: number
  avg_risk_score: number
  top_factors: string[]
}
