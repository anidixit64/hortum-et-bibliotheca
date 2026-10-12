import type { FormEvent } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AdminUsage, ProviderEntry } from '../api/types'

const PIN_KEY = 'admin_pin'

function getPin(): string {
  try {
    return sessionStorage.getItem(PIN_KEY) ?? ''
  } catch {
    return ''
  }
}
function setPin(pin: string) {
  try {
    sessionStorage.setItem(PIN_KEY, pin)
  } catch {
    // private browsing
  }
}

function fmt(n: number): string {
  return n.toLocaleString()
}

function tierLabel(tier: string): string {
  switch (tier) {
    case 'subscription':
      return 'Subscription'
    case 'permanent':
      return 'Free forever'
    case 'credit':
      return 'Free credit'
    case 'renewable':
      return 'Renewable'
    default:
      return tier
  }
}

function UsageBar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  const level = pct >= 80 ? 'danger' : pct >= 50 ? 'caution' : 'ok'
  return (
    <div className="usage-row">
      <span className="usage-label">{label}</span>
      <div className="usage-bar">
        <div className={`usage-fill usage-${level}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="usage-value">
        {fmt(value)} / {fmt(max)}
      </span>
    </div>
  )
}

function ProviderCard({ name, entry }: { name: string; entry: ProviderEntry }) {
  const { today, week, all_time } = entry.usage
  const todayTokens = today.input_tokens + today.output_tokens
  const weekTokens = week.input_tokens + week.output_tokens
  const allTokens = all_time.input_tokens + all_time.output_tokens
  const limits = entry.limits

  return (
    <div className={`card admin-provider ${entry.configured ? '' : 'unconfigured'}`}>
      <div className="provider-header">
        <h3>{entry.label}</h3>
        <span className={`pill ${entry.tier}`}>{tierLabel(entry.tier)}</span>
      </div>
      <p className={`muted small ${entry.configured ? '' : 'unconfigured-note'}`}>
        {entry.configured ? `Provider: ${name}` : 'No API key configured'}
      </p>

      {entry.warnings.length > 0 && (
        <div className="admin-warnings">
          {entry.warnings.map((w, i) => (
            <p key={i} className="admin-warning">
              {w}
            </p>
          ))}
        </div>
      )}

      {entry.configured && (
        <div className="usage-stats">
          {limits.rpd != null && (
            <UsageBar value={today.requests} max={limits.rpd} label="Requests today" />
          )}
          {limits.tpd != null && (
            <UsageBar value={todayTokens} max={limits.tpd} label="Tokens today" />
          )}
          {limits.rpd == null && limits.rpd_per_model == null && (
            <div className="usage-row">
              <span className="usage-label">Requests today</span>
              <span className="usage-value">{fmt(today.requests)}</span>
            </div>
          )}
          <div className="usage-row">
            <span className="usage-label">Tokens today</span>
            <span className="usage-value">{fmt(todayTokens)}</span>
          </div>
          <div className="usage-row">
            <span className="usage-label">Tokens this week</span>
            <span className="usage-value">{fmt(weekTokens)}</span>
          </div>
          <div className="usage-row">
            <span className="usage-label">Tokens all time</span>
            <span className="usage-value">{fmt(allTokens)}</span>
          </div>
          {limits.credit_usd != null && (
            <div className="usage-row">
              <span className="usage-label">Credit</span>
              <span className="usage-value">
                ${limits.credit_usd} / {limits.credit_days ?? '?'} days
              </span>
            </div>
          )}
        </div>
      )}

      {entry.dashboard && (
        <a
          href={entry.dashboard}
          target="_blank"
          rel="noopener noreferrer"
          className="dashboard-link"
        >
          Check balance
        </a>
      )}
    </div>
  )
}

function JobQueue({ jobs }: { jobs: Record<string, Record<string, number>> }) {
  const kinds = Object.keys(jobs)
  if (!kinds.length) return <p className="muted small">No jobs in queue.</p>
  return (
    <div className="job-grid">
      {kinds.map((kind) => {
        const counts = jobs[kind]
        const parts = Object.entries(counts)
          .filter(([, n]) => n > 0)
          .map(([status, n]) => `${n} ${status}`)
        return (
          <div key={kind} className="job-row">
            <span className="job-kind">{kind}</span>
            <span className="muted">{parts.join(', ') || 'idle'}</span>
          </div>
        )
      })}
    </div>
  )
}

export function SettingsPage() {
  const [pin, setPinInput] = useState('')
  const [authed, setAuthed] = useState(false)
  const [data, setData] = useState<AdminUsage | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (p: string) => {
    setLoading(true)
    setError('')
    try {
      const usage = await api.adminUsage(p)
      setData(usage)
      setAuthed(true)
      setPin(p)
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        setError('Invalid PIN')
        setAuthed(false)
        try {
          sessionStorage.removeItem(PIN_KEY)
        } catch {
          // private browsing
        }
      } else {
        setError('Could not load usage data')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const saved = getPin()
    if (saved) load(saved)
  }, [load])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (pin.trim()) load(pin.trim())
  }

  if (!authed) {
    return (
      <div className="admin-gate">
        <form onSubmit={submit} className="card admin-pin-form">
          <h2>Settings</h2>
          <p className="muted">Enter your admin PIN to view usage and provider status.</p>
          <div className="pin-row">
            <input
              type="password"
              value={pin}
              onChange={(e) => setPinInput(e.target.value)}
              placeholder="PIN"
              autoFocus
              className="pin-input"
            />
            <button type="submit" className="primary" disabled={loading || !pin.trim()}>
              {loading ? 'Checking...' : 'Enter'}
            </button>
          </div>
          {error && <p className="error small">{error}</p>}
        </form>
      </div>
    )
  }

  if (!data) return <p className="muted">Loading...</p>

  const configured = Object.entries(data.providers).filter(([, e]) => e.configured)
  const unconfigured = Object.entries(data.providers).filter(([, e]) => !e.configured)

  return (
    <div className="admin-page">
      <h1>Settings</h1>

      <section className="admin-section">
        <h2>Provider Usage</h2>
        <p className="muted small">
          Tracks API calls made by the content worker. Token counts are for successful generations
          only.
        </p>
        <div className="provider-grid">
          {configured.map(([name, entry]) => (
            <ProviderCard key={name} name={name} entry={entry} />
          ))}
        </div>
      </section>

      {unconfigured.length > 0 && (
        <section className="admin-section">
          <h2>Available Providers</h2>
          <p className="muted small">
            Add API keys to <code>.env</code> to enable these as fallback backends.
          </p>
          <div className="provider-grid">
            {unconfigured.map(([name, entry]) => (
              <ProviderCard key={name} name={name} entry={entry} />
            ))}
          </div>
        </section>
      )}

      <section className="admin-section">
        <h2>Generation Queue</h2>
        <JobQueue jobs={data.jobs} />
      </section>

      <button
        className="admin-refresh"
        onClick={() => {
          const saved = getPin()
          if (saved) load(saved)
        }}
        disabled={loading}
      >
        {loading ? 'Refreshing...' : 'Refresh'}
      </button>
    </div>
  )
}
