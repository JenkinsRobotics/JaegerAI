import type { ReactNode } from "react";

export type NotificationKind = "success" | "warning" | "error" | "progress";
export interface NotificationItem { id: string; kind: NotificationKind; title: string; message?: string; timestamp?: string; read?: boolean; progress?: number; actionLabel?: string; persistent?: boolean }
export interface ToastStackProps { items: readonly NotificationItem[]; onAction?: (id: string) => void; onDismiss?: (id: string) => void; className?: string }

export function NotificationContent({ item, actions }: { item: NotificationItem; actions?: ReactNode }) {
  return <><span className="aui-notification-icon" aria-hidden>{item.kind === "success" ? "✓" : item.kind === "warning" ? "!" : item.kind === "error" ? "×" : "↻"}</span><span className="aui-notification-copy"><strong>{item.title}</strong>{item.message ? <span>{item.message}</span> : null}{item.kind === "progress" && item.progress !== undefined ? <progress max={100} value={item.progress} aria-label={`${item.title} progress`} /> : null}</span>{actions}</>;
}

export function ToastStack({ items, onAction, onDismiss, className }: ToastStackProps) {
  return <div className={["aui-toast-stack", className].filter(Boolean).join(" ")} aria-label="Notifications">{items.map((item) => <div key={item.id} className={`aui-toast aui-toast--${item.kind}`} role={item.kind === "error" ? "alert" : "status"} aria-label={item.title}><NotificationContent item={item} actions={<span className="aui-notification-actions">{item.actionLabel ? <button type="button" onClick={() => onAction?.(item.id)}>{item.actionLabel}</button> : null}{!item.persistent ? <button type="button" aria-label={`Dismiss ${item.title}`} onClick={() => onDismiss?.(item.id)}>×</button> : null}</span>} /></div>)}</div>;
}
