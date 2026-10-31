/** Rive 2D stage (MIT runtime). Feeds `state` and `emotion` into the first state machine when it has those inputs. */
import { Rive } from "@rive-app/canvas";

export async function mountRive(canvas: HTMLCanvasElement, url: string) {
  const r = await new Promise<Rive>((resolve, reject) => {
    const rive: Rive = new Rive({ src: url, canvas, autoplay: true, onLoad: () => { rive.resizeDrawingSurfaceToCanvas(); resolve(rive); }, onLoadError: () => reject(new Error("Rive file failed to load")) });
    const sm = rive.stateMachineNames?.[0]; if (sm) rive.play(sm);
  });
  const sm = r.stateMachineNames[0];
  const input = (n: string) => (sm ? r.stateMachineInputs(sm)?.find((i) => i.name === n) : undefined);
  return {
    inputs: () => (sm ? (r.stateMachineInputs(sm) ?? []).map((i) => i.name) : []),
    set(name: string, value: number | boolean) { const i = input(name); if (i) i.value = value; },
    setPaused(p: boolean) { if (p) r.pause(); else r.play(); },
    dispose: () => r.cleanup(),
  };
}
