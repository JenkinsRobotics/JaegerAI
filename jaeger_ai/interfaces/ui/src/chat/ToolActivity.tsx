import { CommandExecution, CommandOutput, ToolCallCard, type AgentItemStatus } from 'codex-ui-kit';
import 'codex-ui-kit/styles.css';
import { FileText, Globe, Search, Terminal, Image, Workflow } from '../components/Icons';
import { stepLine, toolCategory, type ToolPart } from './activity';
import { extractFileDiff, FileDiff } from './fileDiff';
import './toolActivity.css';

export function ActivityIcon({ tool }: { tool?: ToolPart }) {
  const category = tool ? toolCategory(tool.toolName) : 'other';
  const Icon = category === 'shell' ? Terminal : ['search','fileSearch','list'].includes(category) ? Search : ['browser','web'].includes(category) ? Globe : category === 'image' ? Image : ['read','edit'].includes(category) ? FileText : Workflow;
  return <Icon size={16} />;
}
const preview = (value: unknown) => value === undefined ? undefined : typeof value === 'string' ? value : JSON.stringify(value, null, 2);

/** Presentation only: Gateway receipts own all labels, tool inputs and outputs. */
export function ToolActivity({ part }: { part: ToolPart }) {
  const { verb, target } = stepLine(part);
  const status: AgentItemStatus = part.state === 'completed' ? 'completed' : ['streaming','executing'].includes(part.state) ? 'running' : part.state === 'waitingForConfirmation' ? 'pending' : 'failed';
  const input = part.input && typeof part.input === 'object' ? part.input as Record<string,unknown> : {};
  const output = preview(part.output);
  const diff = toolCategory(part.toolName) === 'edit' ? extractFileDiff(part.input, part.output) : undefined;
  const label = <><span>{verb}</span> <span className="jg-tool-activity__target" title={target}>{target}</span>{diff ? <span className="jg-tool-activity__diffstat"> · +{diff.added} −{diff.removed}</span> : null}</>;
  const details = <div className="jg-tool-activity__details">
    {diff && <FileDiff model={diff} />}
    <small>{part.toolName} · {part.summary || part.state}</small>
    <details><summary>Input</summary><pre>{preview(part.input)?.slice(0,16000) || 'No input'}</pre></details>
    {!diff && <CommandOutput copyText={output} emptyLabel={status === 'running' ? 'Waiting for output…' : 'No output retained for this tool call.'}>{output?.slice(0,16000)}</CommandOutput>}
    {!diff && output && output.length > 16000 && <small>Showing the first 16,000 characters. Copy output for the full result.</small>}
  </div>;
  if (toolCategory(part.toolName) === 'shell') return <CommandExecution className="jg-tool-activity" command={target} summary={label}
    status={part.state === 'cancelled' ? 'interrupted' : status} cwd={typeof input.cwd === 'string' ? input.cwd : typeof input.workdir === 'string' ? input.workdir : undefined}
    footer={<small>{part.summary || part.state}</small>} terminalIcon={<ActivityIcon tool={part} />}>{details}</CommandExecution>;
  return <ToolCallCard className="jg-tool-activity" name={part.toolName} status={status} icon={<ActivityIcon tool={part} />}
    activeLabel={label} completedLabel={label} failedLabel={label} disclosureMode="button" collapsible>{details}</ToolCallCard>;
}
