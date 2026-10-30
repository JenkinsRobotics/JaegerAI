import { useEffect, useRef, useState } from 'react'
import type { ComputerSnapshot, JaegerSource, PolicySources } from '../api/source'
import { nativeBridge } from '../platform/native'
import { LocalComputerPanel } from '../settings/LocalComputerPanel'
import './machine-control.css'

interface NativeStatus {
  scope: 'native_shell_process'
  process_id: number
  screen_os_permission: 'granted' | 'not_granted_or_undetermined'
  input_os_permission: 'granted' | 'not_granted_or_undetermined'
}

interface MachineControlPanelProps {
  source?: JaegerSource
}

export function MachineControlPanel({ source }: MachineControlPanelProps) {
  const [snapshot, setSnapshot] = useState<ComputerSnapshot>()
  const [native, setNative] = useState<NativeStatus>()
  const [policy, setPolicy] = useState<PolicySources>()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string>()
  const [error, setError] = useState<string>()
  const [activeSubTab, setActiveSubTab] = useState<'overview' | 'permissions' | 'policy' | 'legacy'>('overview')
  const locked = useRef(false)
  const generation = useRef(0)

  const isNativeAvailable = Boolean(nativeBridge())

  const refreshInventory = async () => {
    if (!source?.computers) return
    try {
      setError(undefined)
      const data = await source.computers()
      setSnapshot(data)
    } catch (e) {
      setError(String(e))
    }
  }

  const readNative = async () => {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    setError(undefined)
    const owner = ++generation.current
    try {
      const bridge = nativeBridge()
      if (!bridge) throw new Error('No native OS bridge detected in this environment')
      const row = (await bridge.post('computer.status')) as NativeStatus
      if (owner !== generation.current) return
      setNative(row)
      setNotice('Refreshed native OS permissions successfully.')
    } catch (e) {
      if (owner === generation.current) setError(String(e))
    } finally {
      locked.current = false
      if (owner === generation.current) setBusy(false)
    }
  }

  const openSettings = async (target: 'accessibility' | 'screen_recording') => {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    setNotice(undefined)
    setError(undefined)
    const owner = ++generation.current
    try {
      const bridge = nativeBridge()
      if (!bridge) throw new Error('Native settings broker not available')
      await bridge.post('computer.settings', { target })
      if (owner !== generation.current) return
      setNotice(`Requested macOS to open ${target === 'accessibility' ? 'Accessibility' : 'Screen Recording'} settings.`)
    } catch (e) {
      if (owner === generation.current) setError(String(e))
    } finally {
      locked.current = false
      if (owner === generation.current) setBusy(false)
    }
  }

  useEffect(() => {
    if (source?.computers) {
      void refreshInventory()
    }
    if (source?.policySources) {
      void source.policySources().then((p) => setPolicy(p)).catch(() => {})
    }
    if (isNativeAvailable) {
      void readNative()
    }
  }, [source])

  return (
    <div className="machine-control-page">
      <header className="machine-control-header">
        <div className="machine-control-header__info">
          <div className="machine-control-header__badge">
            <span className="machine-control-status-dot online" />
            <span>Host Active</span>
          </div>
          <h1 className="machine-control-title">Machine Control & Hardware Telemetry</h1>
          <p className="machine-control-subtitle">
            Local computer inventory, screen capture authorization, accessibility automation, and runtime safety policies.
          </p>
        </div>
        <div className="machine-control-actions">
          <button
            type="button"
            className="machine-control-button"
            disabled={busy}
            onClick={() => {
              void refreshInventory()
              if (isNativeAvailable) void readNative()
            }}
          >
            Refresh Status
          </button>
        </div>
      </header>

      {notice && <div className="machine-control-notice" role="status">{notice}</div>}
      {error && <div className="machine-control-error" role="alert">{error}</div>}

      <div className="machine-control-nav">
        <button
          type="button"
          className={`machine-control-nav-tab ${activeSubTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('overview')}
        >
          Host & Permissions
        </button>
        <button
          type="button"
          className={`machine-control-nav-tab ${activeSubTab === 'permissions' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('permissions')}
        >
          OS Settings
        </button>
        <button
          type="button"
          className={`machine-control-nav-tab ${activeSubTab === 'policy' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('policy')}
        >
          Safety Policies
        </button>
        {source && (
          <button
            type="button"
            className={`machine-control-nav-tab ${activeSubTab === 'legacy' ? 'active' : ''}`}
            onClick={() => setActiveSubTab('legacy')}
          >
            Diagnostics Inspector
          </button>
        )}
      </div>

      <div className="machine-control-content">
        {activeSubTab === 'overview' && (
          <div className="machine-control-grid">
            <div className="machine-control-card">
              <div className="machine-control-card__header">
                <h3>Native Shell Permissions</h3>
                <span className={`badge ${native?.screen_os_permission === 'granted' ? 'badge-success' : 'badge-warning'}`}>
                  {native ? (native.screen_os_permission === 'granted' ? 'Authorized' : 'Action Required') : 'Detecting'}
                </span>
              </div>
              <p className="machine-control-card__desc">
                Screen recording and accessibility control grants required for computer-use actions.
              </p>
              <div className="machine-control-stat-list">
                <div className="machine-control-stat-row">
                  <span className="label">Native Shell PID:</span>
                  <span className="value">{native?.process_id ?? 'Unknown'}</span>
                </div>
                <div className="machine-control-stat-row">
                  <span className="label">Screen Recording:</span>
                  <span className={`value ${native?.screen_os_permission === 'granted' ? 'granted' : 'pending'}`}>
                    {native?.screen_os_permission?.replaceAll('_', ' ') ?? 'Unknown / Not Granted'}
                  </span>
                </div>
                <div className="machine-control-stat-row">
                  <span className="label">Input / Accessibility:</span>
                  <span className={`value ${native?.input_os_permission === 'granted' ? 'granted' : 'pending'}`}>
                    {native?.input_os_permission?.replaceAll('_', ' ') ?? 'Unknown / Not Granted'}
                  </span>
                </div>
              </div>
              <div className="machine-control-card__actions">
                <button
                  type="button"
                  className="machine-control-btn-secondary"
                  disabled={!isNativeAvailable || busy}
                  onClick={() => void readNative()}
                >
                  Query Permission Status
                </button>
              </div>
            </div>

            <div className="machine-control-card">
              <div className="machine-control-card__header">
                <h3>Gateway Execution Host</h3>
                <span className="badge badge-info">127.0.0.1:33418</span>
              </div>
              <p className="machine-control-card__desc">
                Current runtime hardware host running the gateway control plane and tool executors.
              </p>
              {snapshot?.computers && snapshot.computers.length > 0 ? (
                snapshot.computers.map((c) => (
                  <div key={c.id} className="machine-control-stat-list">
                    <div className="machine-control-stat-row">
                      <span className="label">Host Identifier:</span>
                      <span className="value">{c.id}</span>
                    </div>
                    <div className="machine-control-stat-row">
                      <span className="label">Operating System / Arch:</span>
                      <span className="value">{c.os} ({c.architecture})</span>
                    </div>
                    <div className="machine-control-stat-row">
                      <span className="label">Process ID:</span>
                      <span className="value">{c.process_id}</span>
                    </div>
                    <div className="machine-control-stat-row">
                      <span className="label">Screen View Policy:</span>
                      <span className="value">{c.screen_view.replaceAll('_', ' ')}</span>
                    </div>
                    <div className="machine-control-stat-row">
                      <span className="label">Input Authorization:</span>
                      <span className="value">{c.input_authorization.replaceAll('_', ' ')}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="machine-control-stat-list">
                  <div className="machine-control-stat-row">
                    <span className="label">Architecture:</span>
                    <span className="value">Apple Silicon / Darwin</span>
                  </div>
                  <div className="machine-control-stat-row">
                    <span className="label">Gateway Status:</span>
                    <span className="value granted">Online (Local Daemon)</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {activeSubTab === 'permissions' && (
          <div className="machine-control-card full-width">
            <h3>macOS Privacy & Security Shortcut Panes</h3>
            <p className="machine-control-card__desc">
              To grant or revoke computer control permissions, open the native macOS System Settings panes below. Jaeger never modifies system permissions directly.
            </p>
            <div className="machine-control-card__buttons">
              <button
                type="button"
                className="machine-control-btn-primary"
                disabled={!isNativeAvailable || busy}
                onClick={() => void openSettings('accessibility')}
              >
                Open Accessibility Settings
              </button>
              <button
                type="button"
                className="machine-control-btn-primary"
                disabled={!isNativeAvailable || busy}
                onClick={() => void openSettings('screen_recording')}
              >
                Open Screen Recording Settings
              </button>
            </div>
          </div>
        )}

        {activeSubTab === 'policy' && (
          <div className="machine-control-card full-width">
            <h3>Tool Execution Policy Sources</h3>
            <p className="machine-control-card__desc">
              Instance and commissioning policies that govern tool authorization and dangerous action guards.
            </p>
            {policy ? (
              <div className="machine-control-policy-grid">
                <div className="policy-stat">
                  <span className="policy-stat-label">Instance Policy:</span>
                  <span className="policy-stat-val">{policy.state}</span>
                </div>
                <div className="policy-stat">
                  <span className="policy-stat-label">Commissioning:</span>
                  <span className="policy-stat-val">{policy.commissioning_state ?? 'Standard'}</span>
                </div>
                <div className="policy-stat">
                  <span className="policy-stat-label">Persistent Skill Grants:</span>
                  <span className="policy-stat-val">
                    {policy.persistent_skill_grants?.state ?? 'Enforced'} ({policy.persistent_skill_grants?.count ?? 0})
                  </span>
                </div>
                <div className="policy-list">
                  <h4>Admitted Sources:</h4>
                  <ul>
                    {policy.sources.map((s) => (
                      <li key={s.id}>
                        <code>{s.id}</code>: {String(s.value)} ({s.source})
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <p className="machine-control-empty">No active policy restrictions detected or mock provider running.</p>
            )}
          </div>
        )}

        {activeSubTab === 'legacy' && source && (
          <div className="machine-control-card full-width">
            <LocalComputerPanel source={source} />
          </div>
        )}
      </div>
    </div>
  )
}
export default MachineControlPanel
