import { useEffect, useRef, useState } from 'react'
import type { ComputerSnapshot, JaegerSource, PolicySources } from '../api/source'
import { nativeBridge } from '../platform/native'
import { LocalComputerPanel } from '../settings/LocalComputerPanel'
import './machine-control.css'
import { PageHeader } from '../components/PageHeader'
import { Badge, SubTabs } from '../unified/ui'
import { ResourcesCard } from '../machine/ResourcesCard'
import { HostCapabilitiesCard } from '../machine/HostCapabilitiesCard'
import { LogsPanel } from '../machine/LogsPanel'
import { AgentAppsPanel } from '../machine/AgentAppsPanel'

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
  const [attempt, setAttempt] = useState(0)
  const [inventoryState, setInventoryState] = useState<'loading' | 'unavailable' | 'error' | 'ready'>('loading')
  const [policyState, setPolicyState] = useState<'loading' | 'unavailable' | 'error' | 'ready'>('loading')
  const [inventoryError, setInventoryError] = useState<string>()
  const [policyError, setPolicyError] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string>()
  const [error, setError] = useState<string>()
  const [activeSubTab, setActiveSubTab] = useState<'overview' | 'apps' | 'logs' | 'permissions' | 'policy' | 'legacy'>('overview')
  const locked = useRef(false)
  const generation = useRef(0)

  const isNativeAvailable = Boolean(nativeBridge())

  useEffect(() => {
    let live = true
    setSnapshot(undefined)
    setPolicy(undefined)
    setInventoryError(undefined)
    setPolicyError(undefined)
    setInventoryState(source?.computers ? 'loading' : 'unavailable')
    setPolicyState(source?.policySources ? 'loading' : 'unavailable')
    if (source?.computers) void Promise.resolve().then(() => source.computers!()).then(data => {
      if (!live) return
      if (data?.scope !== 'gateway_process_only' || !Array.isArray(data.computers) ||
          !Array.isArray(data.limits) || !data.limits.every(limit => typeof limit === 'string') ||
          !data.computers.every(c => c && typeof c.id === 'string' && typeof c.state === 'string' &&
            typeof c.os === 'string' && typeof c.architecture === 'string' && Number.isSafeInteger(c.process_id) &&
            typeof c.screen_view === 'string' && typeof c.input_authorization === 'string')) {
        throw new Error('Unqualified computer inventory response')
      }
      setSnapshot(data)
      setInventoryState('ready')
    }).catch(e => {
      if (live) { setInventoryError(String(e)); setInventoryState('error') }
    })
    if (source?.policySources) void Promise.resolve().then(() => source.policySources!()).then(data => {
      if (!live) return
      if (data?.scope !== 'bound_instance_policy_sources' || data.action_authorized !== false ||
          data.mutation_supported !== false || data.hook_execution_performed !== false ||
          !['observed', 'runtime_not_bound'].includes(data.state) ||
          (data.commissioning_state !== undefined && typeof data.commissioning_state !== 'string') ||
          (data.persistent_skill_grants !== undefined && (!data.persistent_skill_grants ||
            typeof data.persistent_skill_grants.state !== 'string' ||
            (data.persistent_skill_grants.count !== null && !Number.isSafeInteger(data.persistent_skill_grants.count)))) ||
          !Array.isArray(data.sources) ||
          !data.sources.every(s => s && typeof s.id === 'string' && typeof s.source === 'string' &&
            ['string', 'boolean', 'number'].includes(typeof s.value)) ||
          !Array.isArray(data.limits) || !data.limits.every(limit => typeof limit === 'string')) {
        throw new Error('Unqualified policy-source response')
      }
      setPolicy(data)
      setPolicyState('ready')
    }).catch(e => {
      if (live) { setPolicyError(String(e)); setPolicyState('error') }
    })
    return () => { live = false }
  }, [source, attempt])

  useEffect(() => () => { generation.current++ }, [])

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
    if (isNativeAvailable) {
      void readNative()
    }
  }, [source])

  return (
    <div className="machine-control-page jg-u-page">
      <PageHeader title="Machine"
        subtitle="Gateway host observations, permissions, agent apps, logs and safety rules."
        actions={<>
          <Badge tone="warn">{inventoryState === 'loading' ? 'Loading inventory' : inventoryState === 'ready' ? (snapshot?.computers.length ? 'Gateway inventory observed' : 'No hosts reported') : 'Inventory unavailable'}</Badge>
          <button type="button" className="jg-u-btn" disabled={busy} onClick={() => { setAttempt(value => value + 1); if (isNativeAvailable) void readNative() }}>Refresh</button>
        </>} />
      {notice && <div className="machine-control-notice" role="status">{notice}</div>}
      {inventoryError && <div className="machine-control-error" role="alert">Inventory unavailable: {inventoryError}</div>}
      {policyError && <div className="machine-control-error" role="alert">Safety policy unavailable: {policyError}</div>}
      {error && <div className="machine-control-error" role="alert">{error}</div>}

      <SubTabs label="Machine sections" active={activeSubTab} onPick={(t) => setActiveSubTab(t as typeof activeSubTab)}
        tabs={[{ id: 'overview', title: 'Overview' }, { id: 'apps', title: 'Apps' }, { id: 'logs', title: 'Logs' }, { id: 'permissions', title: 'OS settings' },
          { id: 'policy', title: 'Safety' }, ...(source ? [{ id: 'legacy', title: 'Diagnostics' }] : [])]} />

      <div className="machine-control-content">
        {activeSubTab === 'overview' && <><HostCapabilitiesCard /><ResourcesCard /></>}
        {activeSubTab === 'logs' && <LogsPanel />}
        {activeSubTab === 'apps' && <AgentAppsPanel />}
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
                <h3>Gateway Host Inventory</h3>
              </div>
              <p className="machine-control-card__desc">
                Gateway process observations only. Serving proves transport, not verified agent or tool execution.
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
                      <span className="label">Reported Gateway State:</span>
                      <span className="value">{c.state} (transport observation only)</span>
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
                <p className="machine-control-empty">{inventoryState === 'loading' ? 'Loading gateway inventory…' : inventoryState === 'ready' ? 'No hosts reported by gateway inventory.' : 'Gateway inventory unavailable. Hardware and runtime status are unknown.'}</p>
              )}
              {snapshot?.limits.map((limit, index) => <p key={index} className="machine-control-card__desc">{limit}</p>)}
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
                  <span className="policy-stat-val">{policy.commissioning_state ?? 'Unknown'}</span>
                </div>
                <div className="policy-stat">
                  <span className="policy-stat-label">Persistent Skill Grants:</span>
                  <span className="policy-stat-val">
                    {policy.persistent_skill_grants?.state ?? 'Unknown'} ({policy.persistent_skill_grants?.count ?? 'unknown count'})
                  </span>
                </div>
                <div className="policy-list">
                  <h4>Admitted Sources:</h4>
                  {policy.sources.length === 0 && <p>No policy sources reported. This does not establish authorization.</p>}
                  <ul>
                    {policy.sources.map((s) => (
                      <li key={s.id}>
                        <code>{s.id}</code>: {String(s.value)} ({s.source})
                      </li>
                    ))}
                  </ul>
                </div>
                {policy.limits.map((limit, index) => <p key={index}>{limit}</p>)}
                <p>Read-only policy observation. No action is authorized by this status.</p>
              </div>
            ) : (
              <p className="machine-control-empty">{policyState === 'loading' ? 'Loading safety policy…' : 'Safety policy unavailable. Restrictions and authorization are unknown.'}</p>
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
