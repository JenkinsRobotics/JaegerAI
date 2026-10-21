/* Keeps html[data-mode] (read by the generated jaeger.css) in step with Aether's .aether-light-theme class,
 * which every existing appearance path toggles (SettingsDialog.applyAppearance, vendored StudioChrome). */
export function syncModeAttribute(root: HTMLElement = document.documentElement) {
  const mode = root.classList.contains("aether-light-theme") ? "light" : "dark";
  if (root.dataset.mode !== mode) root.dataset.mode = mode;
}

export function installModeSync(root: HTMLElement = document.documentElement): () => void {
  syncModeAttribute(root);
  if (typeof MutationObserver !== "function") return () => {};
  const observer = new MutationObserver(() => syncModeAttribute(root));
  observer.observe(root, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}
