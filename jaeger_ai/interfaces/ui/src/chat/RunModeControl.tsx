import { useCallback, useEffect, useRef, useState } from 'react';
import type { RuntimeTier, RuntimeTierSnapshot } from '../api/source';
import { Check, ChevronDown, FileText, MessageSquare, Wrench } from '../components/Icons';
import { useExclusivePopup } from '../popups/coordinator';
import type { ChatHost } from './host';

type ModeHost = Pick<ChatHost, 'runtimeTier' | 'setRuntimeTier'>;
const label = (tier: RuntimeTier) => tier.charAt(0).toUpperCase() + tier.slice(1);
const MODE_COPY: Record<string, { icon: typeof MessageSquare; description: string }> = {
  chat: { icon: MessageSquare, description: "Talk only — no tools." },
  agent: { icon: Wrench, description: "Use tools to get the work done." },
  plan: { icon: FileText, description: "Look around, then propose a plan for you to approve." },
};
const modeMeta = (tier: RuntimeTier) => MODE_COPY[tier] ?? { icon: Wrench, description: "" };

/** Edits the existing Gateway-wide interaction tier; does not grant tool authority. */
export function RunModeControl({host, disabled = false, onTier}: {host: ModeHost; disabled?: boolean; onTier?: (tier: RuntimeTier) => void}) {
  const [snapshot, setSnapshot] = useState<RuntimeTierSnapshot>();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [error, setError] = useState<string>();
  const trigger = useRef<HTMLButtonElement>(null);
  const locked = useRef(false);
  const generation = useRef(0);
  useExclusivePopup(open, () => setOpen(false), trigger.current);
  const refresh = useCallback(async () => {
    if (!host.runtimeTier || locked.current) return;
    const owner = ++generation.current;
    setLoading(true);
    try {
      const value = await host.runtimeTier();
      if (!value.options?.includes(value.tier)) throw Error('Run mode response is invalid');
      if (owner !== generation.current) return;
      setSnapshot(value); setError(undefined); setNeedsRefresh(false); onTier?.(value.tier);
    } catch (cause) {
      if (owner === generation.current) {setError(String((cause as Error).message ?? cause)); setNeedsRefresh(true);}
    } finally {if (owner === generation.current) setLoading(false);}
  }, [host]);
  useEffect(() => {void refresh(); return () => {generation.current++;};}, [refresh]);
  if (!host.runtimeTier || !host.setRuntimeTier) return null;
  const select = async (tier: RuntimeTier) => {
    if (disabled || locked.current || loading || needsRefresh || !snapshot?.options.includes(tier)) return;
    if (tier === snapshot.tier) {setOpen(false); return;}
    locked.current = true; setSaving(true); setError(undefined);
    const owner = generation.current;
    try {
      const value = await host.setRuntimeTier!(tier);
      if (value.tier !== tier || !value.options?.includes(tier)) throw Error('Gateway returned a different run mode');
      if (owner === generation.current) {setSnapshot({...value, descriptions:snapshot.descriptions}); setOpen(false); onTier?.(value.tier);}
    } catch (cause) {
      if (owner === generation.current) {setError(`Change unconfirmed: ${String((cause as Error).message ?? cause)}. Refresh before changing it again.`); setNeedsRefresh(true);}
    } finally {locked.current = false; if (owner === generation.current) setSaving(false);}
  };
  return <div className="jg-runmode">
    <button ref={trigger} type="button" className="jg-composer__policy jg-runmode__trigger" aria-label={`Run mode: ${snapshot ? label(snapshot.tier) : 'unavailable'}`} aria-haspopup="menu" aria-expanded={open} disabled={disabled || saving} title={disabled ? 'Run mode can change after this turn' : 'Choose Chat, Agent, or Plan mode'} onClick={() => {setOpen(value=>!value); if (!open) void refresh();}}>
      {(() => { const Icon = snapshot ? modeMeta(snapshot.tier).icon : Wrench; return <Icon size={20}/>; })()}<span className="jg-composer__policy-label">{snapshot ? label(snapshot.tier) : 'Run mode'}</span><ChevronDown size={14} className="jg-composer__chevron"/>
    </button>
    {open && <div className="jg-autonomy-menu jg-runmode-menu" role="menu" aria-label="Run mode">
      <header>How should Jaeger work?</header>
      {snapshot?.options.map(tier => { const Icon = modeMeta(tier).icon; return <button type="button" role="menuitemradio" aria-checked={snapshot.tier === tier} disabled={disabled || loading || saving || needsRefresh} key={tier} onClick={() => void select(tier)}>
        <Icon size={18}/><span><strong>{label(tier)}</strong><small>{modeMeta(tier).description}</small></span>{snapshot.tier === tier && <Check size={18}/>}
      </button>; })}
      {error && <p className="jg-autonomy-error" role="alert">{error}{needsRefresh ? ' Reopen this menu to retry.' : ''}</p>}
    </div>}
  </div>;
}
