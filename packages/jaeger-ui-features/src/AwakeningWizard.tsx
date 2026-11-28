import { useEffect, useState } from "react";

export interface AwakeningWizardProps {
  baseUrl: string;
  open: boolean;
  initialOwnerName?: string;
  initialAiName?: string;
  initialMission?: string;
  models: Array<{ id: string }>;
  initialRouting?: { primary?: string; background?: string; vision?: string; fallback?: string };
  droidAvailable?: boolean;
  onWakeDroid?: () => Promise<boolean>;
  onSleepDroid?: () => Promise<boolean>;
  onComplete: (result: Record<string, any>) => void;
  onDismiss: () => void;
}

export function AwakeningWizard({
  baseUrl,
  open,
  initialOwnerName = "",
  initialAiName = "Jaeger",
  initialMission = "",
  models,
  initialRouting,
  droidAvailable = false,
  onWakeDroid,
  onSleepDroid,
  onComplete,
  onDismiss,
}: AwakeningWizardProps) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [ownerName, setOwnerName] = useState(initialOwnerName);
  const [aiName, setAiName] = useState(initialAiName || "Jaeger");
  const [mission, setMission] = useState(initialMission);
  const [firstGoal, setFirstGoal] = useState("");
  const [primaryModel, setPrimaryModel] = useState(initialRouting?.primary || "");
  const [backgroundModel, setBackgroundModel] = useState(initialRouting?.background || "");
  const [visionModel, setVisionModel] = useState(initialRouting?.vision || "qwen3-vl:8b-instruct");
  const [fallbackModel, setFallbackModel] = useState(initialRouting?.fallback || "");
  const [autonomyEnabled, setAutonomyEnabled] = useState(true);
  const [droidTestMsg, setDroidTestMsg] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    if (initialOwnerName && initialOwnerName.toLowerCase() !== "owner") setOwnerName(initialOwnerName);
    if (initialAiName) setAiName(initialAiName);
    if (initialMission) setMission(initialMission);
    if (initialRouting?.primary) setPrimaryModel(initialRouting.primary);
    if (initialRouting?.background) setBackgroundModel(initialRouting.background);
    if (initialRouting?.vision) setVisionModel(initialRouting.vision);
    if (initialRouting?.fallback) setFallbackModel(initialRouting.fallback);
  }, [open, initialOwnerName, initialAiName, initialMission, initialRouting]);

  if (!open) return null;

  const submitOnboarding = async () => {
    setSaving(true);
    setError("");
    try {
      const payload: Record<string, unknown> = {
        owner_name: ownerName.trim() || "Owner",
        ai_name: aiName.trim() || "Jaeger",
        autonomy_enabled: autonomyEnabled,
      };
      if (mission.trim()) payload.mission = mission.trim();
      if (firstGoal.trim()) payload.first_goal = firstGoal.trim();
      if (primaryModel.trim()) payload.primary_model = primaryModel.trim();
      if (backgroundModel.trim()) payload.background_model = backgroundModel.trim();
      if (visionModel.trim()) payload.vision_model = visionModel.trim();
      if (fallbackModel.trim()) payload.fallback_model = fallbackModel.trim();

      const res = await fetch(`${baseUrl}/v1/onboarding/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || "Could not save Day-1 setup.");
      }
      onComplete(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save Day-1 setup.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Jaeger Day-1 Awakening Setup"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
        background: "color-mix(in srgb, var(--jg-bg) 72%, transparent)",
        backdropFilter: "blur(8px)",
      }}
    >
      <div
        className="jg-card"
        style={{
          width: "100%",
          maxWidth: 560,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          padding: 22,
          boxShadow: "0 20px 60px color-mix(in srgb, var(--jg-text-primary) 18%, transparent)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <div>
            <div className="jg-muted" style={{ fontSize: 12 }}>Day-1 Guided Sync · Step {step} of 3</div>
            <h2 style={{ margin: "4px 0 0" }}>
              {step === 1 && "Meet Your Jaeger"}
              {step === 2 && "Hybrid Cloud + Local Models"}
              {step === 3 && "Body, Privacy & Autonomy"}
            </h2>
          </div>
          <button type="button" className="jg-btn-ghost" onClick={onDismiss}>
            Skip for now
          </button>
        </div>

        {step === 1 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <p className="jg-muted" style={{ margin: 0 }}>
              Hey — I just came online. Everything I learn stays in your own <code>~/.jaeger</code> folder. Let&apos;s get introduced.
            </p>
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span>What should I call you?</span>
              <input
                className="jg-input"
                aria-label="Owner name"
                placeholder="Your name"
                value={ownerName}
                onChange={(e) => setOwnerName(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span>Assistant name</span>
              <input
                className="jg-input"
                aria-label="Assistant name"
                placeholder="Jaeger"
                value={aiName}
                onChange={(e) => setAiName(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span>What are we working on together? (optional)</span>
              <input
                className="jg-input"
                aria-label="Mission"
                placeholder="e.g. Ship clean software, manage research, organize projects"
                value={mission}
                onChange={(e) => setMission(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span>First multi-day goal to track (optional)</span>
              <input
                className="jg-input"
                aria-label="First goal"
                placeholder="e.g. Prepare Q4 product launch checklist"
                value={firstGoal}
                onChange={(e) => setFirstGoal(e.target.value)}
              />
            </label>
          </div>
        )}

        {step === 2 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <p className="jg-muted" style={{ margin: 0 }}>
              Use the best model for each job: cloud flagship for heavy work, a fast tier for background autonomy, and local models for private vision and offline fallback.
            </p>
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span>Primary brain (chat &amp; coding)</span>
              <input
                className="jg-input"
                list="jg-awakening-models"
                aria-label="Primary model"
                placeholder="e.g. mistral-large-4:cloud"
                value={primaryModel}
                onChange={(e) => setPrimaryModel(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span>Background tier (self-actions &amp; subagents, optional)</span>
              <input
                className="jg-input"
                list="jg-awakening-models"
                aria-label="Background model"
                placeholder="Leave blank to reuse primary"
                value={backgroundModel}
                onChange={(e) => setBackgroundModel(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span>Droid Vision model</span>
              <input
                className="jg-input"
                list="jg-awakening-models"
                aria-label="Vision model"
                placeholder="qwen3-vl:8b-instruct"
                value={visionModel}
                onChange={(e) => setVisionModel(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span>Local offline fallback (optional)</span>
              <input
                className="jg-input"
                list="jg-awakening-models"
                aria-label="Fallback model"
                placeholder="e.g. gemma4:12b"
                value={fallbackModel}
                onChange={(e) => setFallbackModel(e.target.value)}
              />
            </label>
            <datalist id="jg-awakening-models">
              {models.map((m) => (
                <option key={m.id} value={m.id} />
              ))}
            </datalist>
          </div>
        )}

        {step === 3 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <p className="jg-muted" style={{ margin: 0 }}>
              You are always in control. The camera stays parked downward until you wake it, E-Stop halts motion immediately, and external messages/actions always wait for your approval.
            </p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <span className="jg-pill">Droid hardware: {droidAvailable ? "Detected" : "Optional (not connected)"}</span>
              <span className="jg-pill">Starter skills: 6 verified playbooks ready</span>
            </div>
            {droidAvailable && (onWakeDroid || onSleepDroid) && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                {onWakeDroid && (
                  <button
                    type="button"
                    className="jg-btn"
                    onClick={async () => {
                      const ok = await onWakeDroid();
                      setDroidTestMsg(ok ? "Camera woke and centered." : "Could not wake camera (check E-Stop).");
                    }}
                  >
                    Test Wake Camera
                  </button>
                )}
                {onSleepDroid && (
                  <button
                    type="button"
                    className="jg-btn"
                    onClick={async () => {
                      const ok = await onSleepDroid();
                      setDroidTestMsg(ok ? "Privacy park engaged (-85° lens down)." : "Could not park camera.");
                    }}
                  >
                    Demo Privacy Park (-85°)
                  </button>
                )}
                {droidTestMsg && <span className="jg-muted">{droidTestMsg}</span>}
              </div>
            )}
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={autonomyEnabled}
                onChange={(e) => setAutonomyEnabled(e.target.checked)}
              />
              <span>Allow gentle autonomous self-actions when idle (read-only goals, memory sync &amp; Minecraft)</span>
            </label>
          </div>
        )}

        {error && <div role="alert" className="jg-muted">{error}</div>}

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
          <button
            type="button"
            className="jg-btn"
            disabled={step === 1 || saving}
            onClick={() => setStep((s) => (s === 3 ? 2 : 1))}
          >
            Back
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            {step < 3 ? (
              <button
                type="button"
                className="jg-btn jg-btn-primary"
                onClick={() => setStep((s) => (s === 1 ? 2 : 3))}
              >
                Next
              </button>
            ) : (
              <button
                type="button"
                className="jg-btn jg-btn-primary"
                disabled={saving}
                onClick={() => void submitOnboarding()}
              >
                {saving ? "Saving..." : "Finish Setup"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
