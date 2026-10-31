/** One loader for VRM 1.0 and plain GLB (three.js + @pixiv/three-vrm). Lazy-imported; disposed on unmount. */
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";

export interface StageHandle {
  setOrbit(yaw: number, pitch: number, zoom: number): void;
  setExpression(weights: Record<string, number>): void;
  setMouth(viseme: string | null): void;
  setPaused(paused: boolean): void;
  stats(): { triangles: number; drawCalls: number };
  dispose(): void;
}

export async function mountThree(canvas: HTMLCanvasElement, url: string, opts: { still: boolean; fps?: number }): Promise<StageHandle> {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.6)); // literal-ok (not CSS)
  const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(1, 2, 2); scene.add(key);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 50);
  const loader = new GLTFLoader();
  loader.register((p) => new VRMLoaderPlugin(p));
  const gltf = await loader.loadAsync(url);
  const vrm = gltf.userData.vrm as VRM | undefined;
  const root = vrm?.scene ?? gltf.scene;
  if (vrm) { VRMUtils.rotateVRM0(vrm); VRMUtils.removeUnnecessaryVertices(root); }
  scene.add(root);
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3()); const center = box.getCenter(new THREE.Vector3());
  const target = vrm ? new THREE.Vector3(0, box.max.y - size.y * 0.12, 0) : center;
  const baseDist = vrm ? Math.max(0.8, size.y * 0.45) : Math.max(size.x, size.y, size.z) * 1.6;
  const mixer = gltf.animations.length ? new THREE.AnimationMixer(root) : null;
  if (mixer && !opts.still) mixer.clipAction(gltf.animations[0]).play();
  let yaw = 0, pitch = 0, zoom = 1, paused = false, frame = 0, last = 0;
  const clock = new THREE.Clock();
  const place = () => {
    const d = baseDist / zoom, y = THREE.MathUtils.degToRad(yaw), p = THREE.MathUtils.degToRad(pitch);
    camera.position.set(target.x + d * Math.sin(y) * Math.cos(p), target.y + d * Math.sin(p), target.z + d * Math.cos(y) * Math.cos(p));
    camera.lookAt(target);
  };
  const resize = () => {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize); ro.observe(canvas); resize(); place();
  const minDt = 1000 / (opts.fps ?? 60);
  const tick = (t: number) => {
    frame = requestAnimationFrame(tick);
    if (paused || t - last < minDt) return;
    last = t;
    const dt = clock.getDelta();
    if (!opts.still) { mixer?.update(dt); vrm?.update(dt); } else vrm?.update(0);
    renderer.render(scene, camera);
  };
  frame = requestAnimationFrame(tick);
  const em = vrm?.expressionManager;
  return {
    setOrbit(a, b, z) { yaw = a; pitch = b; zoom = z; place(); },
    setExpression(w) { if (!em) return; for (const n of ["happy", "angry", "sad", "relaxed", "surprised", "neutral"]) em.setValue(n, 0); for (const [n, v] of Object.entries(w)) if (n !== "neutral") em.setValue(n.replace(/^custom:/, ""), v); },
    setMouth(v) { if (!em) return; for (const n of ["aa", "ih", "ou", "ee", "oh"]) em.setValue(n, 0); if (v) em.setValue(v, opts.still ? 0.6 : 1); },
    setPaused(p) { paused = p; },
    stats: () => ({ triangles: renderer.info.render.triangles, drawCalls: renderer.info.render.calls }),
    dispose() { cancelAnimationFrame(frame); ro.disconnect(); if (vrm) VRMUtils.deepDispose(root); renderer.dispose(); },
  };
}
