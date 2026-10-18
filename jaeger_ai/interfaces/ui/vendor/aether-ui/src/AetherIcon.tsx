import menuSvg from "../../assets/icons/menu.svg?raw";
import linkSvg from "../../assets/icons/link.svg?raw";
import visibleSvg from "../../assets/icons/visible.svg?raw";
import hiddenSvg from "../../assets/icons/hidden.svg?raw";
import commentSvg from "../../assets/icons/comment.svg?raw";
import notesSvg from "../../assets/icons/notes.svg?raw";
import tasksSvg from "../../assets/icons/tasks.svg?raw";
import modeFloatingSvg from "../../assets/icons/mode-floating.svg?raw";
import modeDockedSvg from "../../assets/icons/mode-docked.svg?raw";
import modeCanvasSvg from "../../assets/icons/mode-canvas.svg?raw";
import windowsSvg from "../../assets/icons/windows.svg?raw";
import exportSvg from "../../assets/icons/export.svg?raw";
import appearanceSystemSvg from "../../assets/icons/appearance-system.svg?raw";
import appearanceLightSvg from "../../assets/icons/appearance-light.svg?raw";
import appearanceDarkSvg from "../../assets/icons/appearance-dark.svg?raw";
import { useSyncExternalStore } from "react";
import type { SVGProps } from "react";
import aetherSvg from "../../assets/icons/aether.svg?raw";
import appearanceSvg from "../../assets/icons/appearance.svg?raw";
import commandsSvg from "../../assets/icons/commands.svg?raw";
import designSvg from "../../assets/icons/design.svg?raw";
import documentSvg from "../../assets/icons/document.svg?raw";
import fitSvg from "../../assets/icons/fit.svg?raw";
import helpSvg from "../../assets/icons/help.svg?raw";
import historySvg from "../../assets/icons/history.svg?raw";
import hardwareSvg from "../../assets/icons/hardware.svg?raw";
import homeSvg from "../../assets/icons/home.svg?raw";
import importSvg from "../../assets/icons/import.svg?raw";
import newSvg from "../../assets/icons/new.svg?raw";
import openSvg from "../../assets/icons/open.svg?raw";
import animateSvg from "../../assets/icons/animate.svg?raw";
import redoSvg from "../../assets/icons/redo.svg?raw";
import saveSvg from "../../assets/icons/save.svg?raw";
import settingsSvg from "../../assets/icons/settings.svg?raw";
import gaugeSvg from "../../assets/icons/gauge.svg?raw";
import fileCharacterSvg from "../../assets/icons/file-character.svg?raw";
import fileClipSvg from "../../assets/icons/file-clip.svg?raw";
import fileShowSvg from "../../assets/icons/file-show.svg?raw";
import filePartSvg from "../../assets/icons/file-part.svg?raw";
import fileAssemblySvg from "../../assets/icons/file-assembly.svg?raw";
import fileDrawingSvg from "../../assets/icons/file-drawing.svg?raw";
import fileProjectSvg from "../../assets/icons/file-project.svg?raw";
import layoutSvg from "../../assets/icons/layout.svg?raw";
import sidebarSvg from "../../assets/icons/sidebar.svg?raw";
import cubeSvg from "../../assets/icons/cube.svg?raw";
import paletteSvg from "../../assets/icons/palette.svg?raw";
import layersSvg from "../../assets/icons/layers.svg?raw";
import lightingSvg from "../../assets/icons/lighting.svg?raw";
import mouseSvg from "../../assets/icons/mouse.svg?raw";
import hammerSvg from "../../assets/icons/hammer.svg?raw";
import showSvg from "../../assets/icons/show.svg?raw";
import undoSvg from "../../assets/icons/undo.svg?raw";
import windowSvg from "../../assets/icons/window.svg?raw";
import assemblySvg from "../../assets/icons/assembly.svg?raw";
import chevronSvg from "../../assets/icons/chevron.svg?raw";
import connectorSvg from "../../assets/icons/connector.svg?raw";
import folderSvg from "../../assets/icons/folder.svg?raw";
import itemsSvg from "../../assets/icons/items.svg?raw";
import mateSvg from "../../assets/icons/mate.svg?raw";
import searchSvg from "../../assets/icons/search.svg?raw";
import sketchSvg from "../../assets/icons/sketch.svg?raw";
import stepSvg from "../../assets/icons/step.svg?raw";
import viewSvg from "../../assets/icons/view.svg?raw";
import closeSvg from "../../assets/icons/close.svg?raw";
import deleteSvg from "../../assets/icons/delete.svg?raw";
import playSvg from "../../assets/icons/play.svg?raw";
import fastenedSvg from "../../assets/icons/fastened.svg?raw";
import parallelSvg from "../../assets/icons/parallel.svg?raw";
import revoluteSvg from "../../assets/icons/revolute.svg?raw";
import sliderSvg from "../../assets/icons/slider.svg?raw";
import cylindricalSvg from "../../assets/icons/cylindrical.svg?raw";
import pin_slotSvg from "../../assets/icons/pin_slot.svg?raw";
import planarSvg from "../../assets/icons/planar.svg?raw";
import ballSvg from "../../assets/icons/ball.svg?raw";

const icons = {
  menu: menuSvg,
  link: linkSvg,
  visible: visibleSvg,
  hidden: hiddenSvg,
  comment: commentSvg,
  notes: notesSvg,
  tasks: tasksSvg,
  "mode-floating": modeFloatingSvg,
  "mode-docked": modeDockedSvg,
  "mode-canvas": modeCanvasSvg,
  windows: windowsSvg,
  export: exportSvg,
  "appearance-system": appearanceSystemSvg,
  "appearance-light": appearanceLightSvg,
  "appearance-dark": appearanceDarkSvg,
  aether: aetherSvg,
  appearance: appearanceSvg,
  commands: commandsSvg,
  design: designSvg,
  document: documentSvg,
  fit: fitSvg,
  help: helpSvg,
  history: historySvg,
  hardware: hardwareSvg,
  home: homeSvg,
  import: importSvg,
  layout: layoutSvg,
  new: newSvg,
  open: openSvg,
  animate: animateSvg,
  redo: redoSvg,
  save: saveSvg,
  settings: settingsSvg,
  gauge: gaugeSvg,
  "file-character": fileCharacterSvg,
  "file-clip": fileClipSvg,
  "file-show": fileShowSvg,
  "file-part": filePartSvg,
  "file-assembly": fileAssemblySvg,
  "file-drawing": fileDrawingSvg,
  "file-project": fileProjectSvg,
  sidebar: sidebarSvg,
  cube: cubeSvg,
  palette: paletteSvg,
  layers: layersSvg,
  lighting: lightingSvg,
  mouse: mouseSvg,
  hammer: hammerSvg,
  show: showSvg,
  undo: undoSvg,
  window: windowSvg,
  assembly: assemblySvg,
  chevron: chevronSvg,
  connector: connectorSvg,
  folder: folderSvg,
  items: itemsSvg,
  mate: mateSvg,
  model: designSvg,
  search: searchSvg,
  sketch: sketchSvg,
  step: stepSvg,
  view: viewSvg,
  close: closeSvg,
  delete: deleteSvg,
  play: playSvg,
  fastened: fastenedSvg,
  parallel: parallelSvg,
  revolute: revoluteSvg,
  slider: sliderSvg,
  cylindrical: cylindricalSvg,
  pin_slot: pin_slotSvg,
  planar: planarSvg,
  ball: ballSvg
} as const;

export type AetherIconName = keyof typeof icons;
export const aetherIconNames = Object.keys(icons) as AetherIconName[];
export interface AetherIconProps extends Omit<SVGProps<SVGSVGElement>, "children" | "dangerouslySetInnerHTML" | "ref"> {
  name: AetherIconName;
}

/** Artwork lives in core/assets/icons. This component only supplies presentation.
 * The markup is trusted, repository-owned SVG imported at build time, never user data.
 * Buttons/controls provide accessible labels; their icon is decorative. */
/** Icon-pack seam: a pack registers alternate markup for the same names.
 * Partial packs fall back to the default artwork per icon. Registration is a
 * hot swap — every mounted icon re-renders immediately via the pack store. */
let activeIconPack: Partial<Record<AetherIconName, string>> | null = null;
let iconPackVersion = 0;
const iconPackListeners = new Set<() => void>();
const subscribeIconPack = (listener: () => void) => {
  iconPackListeners.add(listener);
  return () => iconPackListeners.delete(listener);
};
export function registerIconPack(pack: Partial<Record<AetherIconName, string>> | null) {
  activeIconPack = pack;
  iconPackVersion += 1;
  for (const listener of iconPackListeners) listener();
}

export function AetherIcon({ name, ...props }: AetherIconProps) {
  useSyncExternalStore(subscribeIconPack, () => iconPackVersion, () => iconPackVersion);
  const source = activeIconPack?.[name] ?? icons[name];
  const markup = source.replace(/^<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "");
  return <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"
    width="1em" height="1em" fill="none" stroke="currentColor"
    strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7"
    {...props} dangerouslySetInnerHTML={{ __html: markup }} />;
}
