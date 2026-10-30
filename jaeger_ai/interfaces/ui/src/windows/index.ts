/**
 * windows/index.ts — Export all window-related components
 */

export { AppWindow, default as AppWindowDefault } from './AppWindow'
export { WindowDock } from './WindowDock'
export {
  useWindowManager,
  WINDOW_DEFINITIONS,
  type WindowId,
  type WindowInstance,
  type WindowDefinition,
} from './WindowManager'
