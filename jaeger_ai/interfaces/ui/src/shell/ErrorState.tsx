/* Shown wherever a real fetch failed. It never substitutes sample data. */
export function ErrorState({ title, error, onRetry, compact }: { title: string; error: string; onRetry?: () => void; compact?: boolean }) {
  return (
    <div className={`jg-error-state${compact ? " jg-error-state--compact" : ""}`} role="alert">
      <div className="jg-error-state__title">{title}</div>
      <div className="jg-error-state__detail">{error}</div>
      {onRetry && <button type="button" className="aui-button" onClick={onRetry}>Retry</button>}
    </div>
  );
}
