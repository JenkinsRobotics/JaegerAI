/**
 * Standalone Settings view (Phase 3 UI Consolidation).
 *
 * Mounts SettingsDialog inline directly with its panels — eliminating the
 * legacy AppWindow -> App.tsx mount that loaded a second hidden Chat shell
 * merely to render Settings.
 */
import { lazy, Suspense, useEffect } from "react";
import type { JaegerSource } from "../api/source";
import type { Agent } from "../api/types";
import { AutomationsPanel } from "../automations/AutomationsPanel";
import { ChannelsPanel } from "../channels/ChannelsPanel";
import { LibraryPanel } from "../library/LibraryPanel";
import { MachineControlPanel } from "../machine-control/MachineControlPanel";
import { SkillsPanel } from "../skills/SkillsPanel";
import { ToolsPanel } from "../tools/ToolsPanel";
import { IntegrationsPage } from "../unified/IntegrationsPage";
import { SkeletonRows } from "../unified/ui";
import { WebhooksPanel } from "../webhooks/WebhooksPanel";
import { WorkflowsPanel } from "../workflows/WorkflowsPanel";
import { DangerReset } from "./DangerReset";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { EntityMemoryPanel } from "./EntityMemoryPanel";
import { LocalComputerPanel } from "./LocalComputerPanel";
import { NativeClipboardPanel } from "./NativeClipboardPanel";
import { NotificationsPanel } from "./NotificationsPanel";
import { OwnerProfilePanel } from "./OwnerProfilePanel";
import { SavedFactsPanel } from "./SavedFactsPanel";
import { SettingsDialog, type Tab as SettingsTab } from "./SettingsDialog";
import { UpdatePlanPanel } from "./UpdatePlanPanel";

const ModelsPage = lazy(() => import("../unified/ModelsPage").then((m) => ({ default: m.ModelsPage })));
const ComparePage = lazy(() => import("../unified/ComparePage").then((m) => ({ default: m.ComparePage })));
const UsagePage = lazy(() => import("../unified/UsagePage").then((m) => ({ default: m.UsagePage })));
const SharePointPanel = lazy(() => import("../sharepoint/SharePointPanel").then((m) => ({ default: m.SharePointPanel })));
const CheckpointsView = lazy(() => import("../unified/CheckpointsView").then((m) => ({ default: m.CheckpointsView })));
const DroidView = lazy(() => import("../droid/DroidView").then((m) => ({ default: m.DroidView })));

const Fallback = () => <div className="jg-u-page"><SkeletonRows n={4} /></div>;

function SectionJump({ active, sections }: { active?: string; sections: { id: string; title: string; body: React.ReactNode }[] }) {
  useEffect(() => {
    if (active) document.getElementById(`set-${active}`)?.scrollIntoView?.({ block: "start" });
  }, [active]);
  return (
    <>
      <nav className="jg-ui-toolbar" aria-label="Settings subsections">
        {sections.map((s) => (
          <a className="jg-u-btn" key={s.id} href={`#set-${s.id}`}>
            {s.title}
          </a>
        ))}
      </nav>
      {sections.map((s) => (
        <section id={`set-${s.id}`} key={s.id} aria-label={s.title}>
          <h2>{s.title}</h2>
          <Suspense fallback={<Fallback />}>{s.body}</Suspense>
        </section>
      ))}
    </>
  );
}

export interface SettingsViewProps {
  source: JaegerSource;
  agents: Agent[];
  sessionId?: string;
  tab?: SettingsTab;
  segment?: string;
  params: URLSearchParams;
  onTab: (tab: SettingsTab | "") => void;
  onOpenConversation: (sessionId: string) => void;
  onClose: () => void;
}

export function SettingsView({
  source,
  agents,
  sessionId,
  tab,
  segment,
  params,
  onTab,
  onOpenConversation,
  onClose,
}: SettingsViewProps) {
  const showDroid = params.get("section") === "droid";

  return (
    <div className="jg-settings-standalone" data-settings-standalone="1">
      <SettingsDialog
        inline
        open
        tab={tab}
        segment={segment}
        onTab={onTab}
        onClose={onClose}
        modelsContent={
          <SectionJump
            active={tab === "models" ? segment : undefined}
            sections={[
              { id: "library", title: "Library", body: <ModelsPage /> },
              { id: "compare", title: "Compare", body: <ComparePage /> },
              { id: "usage", title: "Usage", body: <UsagePage /> },
            ]}
          />
        }
        integrationsPanel={<IntegrationsPage source={source} />}
        integrationsExtras={
          <SectionJump
            active={tab === "integrations" ? segment : undefined}
            sections={[{ id: "sharepoint", title: "SharePoint", body: <SharePointPanel source={source} /> }]}
          />
        }
        checkpointsPanel={
          <Suspense fallback={<Fallback />}>
            <CheckpointsView source={source} params={params} />
          </Suspense>
        }
        computerPanel={
          <>
            <LocalComputerPanel source={source} />
            <MachineControlPanel source={source} />
            {showDroid && (
              <Suspense fallback={<Fallback />}>
                <DroidView />
              </Suspense>
            )}
          </>
        }
        clipboardPanel={<NativeClipboardPanel />}
        updatesPanel={source.updatePlan ? <UpdatePlanPanel source={source} /> : undefined}
        memoryPanel={
          source.ownerProfile || source.semanticClaims || source.memoryFacts ? (
            <>
              {source.ownerProfile && <OwnerProfilePanel source={source} />}
              {source.memoryFacts && <SavedFactsPanel source={source} />}
              {source.semanticClaims && <EntityMemoryPanel source={source} />}
            </>
          ) : undefined
        }
        notificationsPanel={
          source.notifications ? (
            <NotificationsPanel controls={source.notifications} agents={agents} onOpen={onOpenConversation} />
          ) : undefined
        }
        channelsPanel={source.channels ? <ChannelsPanel source={source} agents={agents} /> : undefined}
        workflowsPanel={source.workflows ? <WorkflowsPanel source={source} agents={agents} /> : undefined}
        diagnosticsPanel={source.diagnostics ? <DiagnosticsPanel source={source} /> : undefined}
        toolsPanel={source.tools ? <ToolsPanel source={source} sessionId={sessionId} /> : undefined}
        automationsPanel={
          source.schedules || source.webhooks ? (
            <>
              {source.schedules && <AutomationsPanel controls={source.schedules} />}
              {source.webhooks && <WebhooksPanel source={source} agents={agents} />}
            </>
          ) : undefined
        }
        skillsPanel={source.skills ? <SkillsPanel source={source} /> : undefined}
        libraryPanel={source.library ? <LibraryPanel controls={source.library} artifacts={source.taskArtifacts} /> : undefined}
        resetPanel={<DangerReset />}
      />
    </div>
  );
}
