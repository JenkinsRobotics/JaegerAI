/**
 * Studio-grade VRM 0.x / 1.0 & GLB 3D Avatar Engine.
 *
 * Synthesizes production VTuber mechanics adapted from semperai/amica (MIT) and
 * @pixiv/three-vrm:
 * - 3-point studio key/fill/rim lighting + ACESFilmic tone mapping
 * - Procedural relaxed stance (eliminates frozen T-pose), gentle chest breathing,
 *   and organic head micro-sway + pointer eye-tracking saccades
 * - Randomized smooth AutoBlink and exponentially-lerped ExpressionController
 * - Real Kokoro lip_marks() viseme timeline playback + sigmoid audio-amplitude lip-sync
 * - 32 GB Apple Silicon GPU discipline: 0% GPU when paused/hidden, deepDispose on unmount
 */

import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";

export interface VisemeFrame {
  t_ms: number;
  duration_ms: number;
  viseme: string;
  weight: number;
}

export interface AvatarStageHandle {
  setEmotion(emotion: string, intensity?: number): void;
  setAmplitude(amplitude: number): void;
  playVisemes(frames: VisemeFrame[]): void;
  setPointer(nx: number, ny: number): void;
  setOrbit(yaw: number, pitch: number, zoom: number): void;
  setPaused(paused: boolean): void;
  stats(): { triangles: number; drawCalls: number; vrmVersion: string };
  dispose(): void;
}

const EMOTION_TO_VRM: Record<string, Record<string, number>> = {
  neutral: {},
  calm: { relaxed: 0.45 },
  warm: { happy: 0.35, relaxed: 0.4 },
  happy: { happy: 0.85 },
  focused: { neutral: 0.5, relaxed: 0.15 },
  curious: { surprised: 0.35, happy: 0.2 },
  concerned: { sad: 0.45 },
  surprised: { surprised: 0.75 },
  sad: { sad: 0.75 },
  relaxed: { relaxed: 0.8 },
  angry: { angry: 0.75 },
};

const VRM0_ALIAS: Record<string, string> = {
  happy: "joy",
  relaxed: "fun",
  sad: "sorrow",
};

const ALL_EXPRESSION_KEYS = ["happy", "joy", "angry", "sad", "sorrow", "relaxed", "fun", "surprised"];
const VISEME_KEYS = ["aa", "ih", "ou", "ee", "oh"];

function damp(current: number, target: number, lambda: number, dt: number): number {
  return THREE.MathUtils.lerp(current, target, 1 - Math.exp(-lambda * dt));
}

export async function mountStudioVrmStage(
  canvas: HTMLCanvasElement,
  url: string,
  opts: { fps?: number; still?: boolean } = {},
): Promise<AvatarStageHandle> {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;

  const scene = new THREE.Scene();

  // 3-point studio lighting (warm key + cool fill + crisp rim backlight)
  const hemi = new THREE.HemisphereLight(0xf5f8ff, 0x262c3a, 1.35); // literal-ok
  scene.add(hemi);
  const keyLight = new THREE.DirectionalLight(0xfff4ea, 1.55); // literal-ok
  keyLight.position.set(1.4, 2.2, 2.4);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0xb8d4ff, 0.7); // literal-ok
  fillLight.position.set(-2.0, 1.2, 1.5);
  scene.add(fillLight);
  const rimLight = new THREE.DirectionalLight(0x9ec5ff, 0.95); // literal-ok
  rimLight.position.set(-0.6, 2.0, -2.2);
  scene.add(rimLight);

  const camera = new THREE.PerspectiveCamera(28, 1, 0.05, 40);
  const lookTarget = new THREE.Object3D();
  camera.add(lookTarget);
  scene.add(camera);

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync(url);
  const vrm = gltf.userData.vrm as VRM | undefined;
  const root = vrm?.scene ?? gltf.scene;
  const vrmVersion = vrm ? (String(vrm.meta?.metaVersion || "1.0")) : "glb";

  if (vrm) {
    VRMUtils.rotateVRM0(vrm);
    VRMUtils.removeUnnecessaryVertices(root);
    if (vrm.lookAt) {
      vrm.lookAt.target = lookTarget;
    }
  }
  scene.add(root);

  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const focusTarget = vrm
    ? new THREE.Vector3(0, box.max.y - size.y * 0.14, 0)
    : center;
  const baseDist = vrm ? Math.max(0.75, size.y * 0.44) : Math.max(size.x, size.y, size.z) * 1.55;

  const mixer = gltf.animations.length ? new THREE.AnimationMixer(root) : null;
  if (mixer && !opts.still) {
    mixer.clipAction(gltf.animations[0]).play();
  }

  // State for smooth expressions, blinking, saccades, lip-sync & orbit
  let yaw = 0;
  let pitch = 4;
  let zoom = 1;
  let paused = false;
  let ptrX = 0;
  let ptrY = 0;
  let targetEmotion = "warm";
  let targetIntensity = 0.7;
  let liveAmplitude = 0;
  let visemeTimeline: VisemeFrame[] = [];
  let visemeStartedAt = 0;

  const currentWeights: Record<string, number> = {};
  const currentVisemes: Record<string, number> = {};

  // Randomized natural AutoBlink state (Amica-derived smooth curve)
  let blinkTimer = 2.4;
  let blinkPhase = 0; // 0 = open, >0 = blinking progress [0..1]
  let saccadeTimer = 1.6;
  let saccadeX = 0;
  let saccadeY = 0;

  const placeCamera = () => {
    const d = baseDist / Math.max(0.4, zoom);
    const y = THREE.MathUtils.degToRad(yaw);
    const p = THREE.MathUtils.degToRad(pitch);
    camera.position.set(
      focusTarget.x + d * Math.sin(y) * Math.cos(p),
      focusTarget.y + d * Math.sin(p),
      focusTarget.z + d * Math.cos(y) * Math.cos(p),
    );
    camera.lookAt(focusTarget);
  };

  const resize = () => {
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();
  placeCamera();

  const clock = new THREE.Clock();
  const minDtMs = 1000 / Math.max(15, opts.fps ?? 45);
  let lastFrameMs = 0;
  let rafId = 0;
  let elapsed = 0;

  const applyProceduralPose = (t: number) => {
    if (!vrm?.humanoid || mixer) return;
    // Drop stiff T-pose arms into a natural relaxed companion stance + subtle breathing
    const lUpper = vrm.humanoid.getNormalizedBoneNode("leftUpperArm");
    const rUpper = vrm.humanoid.getNormalizedBoneNode("rightUpperArm");
    const lLower = vrm.humanoid.getNormalizedBoneNode("leftLowerArm");
    const rLower = vrm.humanoid.getNormalizedBoneNode("rightLowerArm");
    const chest = vrm.humanoid.getNormalizedBoneNode("chest") ?? vrm.humanoid.getNormalizedBoneNode("spine");
    const head = vrm.humanoid.getNormalizedBoneNode("head");

    const breath = Math.sin(t * 1.45) * 0.018;
    if (lUpper) {
      lUpper.rotation.z = -1.18 + breath * 0.6;
      lUpper.rotation.x = 0.08;
    }
    if (rUpper) {
      rUpper.rotation.z = 1.18 - breath * 0.6;
      rUpper.rotation.x = 0.08;
    }
    if (lLower) lLower.rotation.y = 0.14;
    if (rLower) rLower.rotation.y = -0.14;
    if (chest) {
      chest.rotation.x = breath;
      chest.rotation.y = Math.sin(t * 0.42) * 0.025;
    }
    if (head) {
      const targetHeadY = ptrX * 0.22 + Math.sin(t * 0.63) * 0.035 + saccadeX * 0.06;
      const targetHeadX = -ptrY * 0.14 + Math.cos(t * 0.51) * 0.02 + saccadeY * 0.04;
      head.rotation.y = THREE.MathUtils.lerp(head.rotation.y, targetHeadY, 0.08);
      head.rotation.x = THREE.MathUtils.lerp(head.rotation.x, targetHeadX, 0.08);
    }
  };

  const applyExpressionsAndLipSync = (dt: number) => {
    const em = vrm?.expressionManager;
    if (!em) return;

    // 1. Smooth AutoBlink
    let blinkWeight = 0;
    if (blinkPhase > 0) {
      blinkPhase += dt * 7.5;
      blinkWeight = blinkPhase < 0.5 ? blinkPhase * 2 : Math.max(0, (1 - blinkPhase) * 2);
      if (blinkPhase >= 1) {
        blinkPhase = 0;
        blinkTimer = 2.6 + Math.random() * 3.8;
      }
    } else {
      blinkTimer -= dt;
      if (blinkTimer <= 0) blinkPhase = 0.001;
    }
    em.setValue("blink", blinkWeight);

    // 2. Smoothly lerped Emotion weights
    const desired = EMOTION_TO_VRM[targetEmotion] ?? {};
    for (const key of ALL_EXPRESSION_KEYS) {
      let want = (desired[key] ?? 0) * targetIntensity;
      if (want === 0) {
        for (const [v1, v0] of Object.entries(VRM0_ALIAS)) {
          if (v0 === key && desired[v1]) want = desired[v1] * targetIntensity;
        }
      }
      currentWeights[key] = damp(currentWeights[key] ?? 0, want, 6.5, dt);
      if (em.getExpression(key)) {
        em.setValue(key, currentWeights[key]);
      }
    }

    // 3. Viseme timeline (Kokoro lip_marks) OR live amplitude lip-sync
    const desiredVis: Record<string, number> = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
    if (visemeTimeline.length > 0) {
      const elapsedMs = performance.now() - visemeStartedAt;
      const last = visemeTimeline[visemeTimeline.length - 1];
      if (elapsedMs > last.t_ms + last.duration_ms + 120) {
        visemeTimeline = [];
      } else {
        for (const f of visemeTimeline) {
          if (elapsedMs >= f.t_ms && elapsedMs <= f.t_ms + f.duration_ms) {
            if (f.viseme !== "closed" && f.viseme in desiredVis) {
              desiredVis[f.viseme] = Math.min(0.85, f.weight);
            }
            break;
          }
        }
      }
    } else if (liveAmplitude > 0.04) {
      const cooked = 1 / (1 + Math.exp(-10 * liveAmplitude + 3.2));
      desiredVis.aa = Math.min(0.8, cooked * 0.72);
      desiredVis.oh = Math.min(0.4, cooked * 0.24);
    }

    for (const v of VISEME_KEYS) {
      currentVisemes[v] = damp(currentVisemes[v] ?? 0, desiredVis[v], 18.0, dt);
      if (em.getExpression(v)) {
        em.setValue(v, currentVisemes[v]);
      }
    }
  };

  const tick = (nowMs: number) => {
    rafId = requestAnimationFrame(tick);
    if (paused || document.hidden || nowMs - lastFrameMs < minDtMs) return;
    lastFrameMs = nowMs;
    const dt = Math.min(0.05, clock.getDelta());
    elapsed += dt;

    saccadeTimer -= dt;
    if (saccadeTimer <= 0) {
      saccadeTimer = 1.4 + Math.random() * 2.8;
      saccadeX = (Math.random() - 0.5) * 0.5;
      saccadeY = (Math.random() - 0.5) * 0.3;
    }
    lookTarget.position.set(ptrX * 0.45 + saccadeX * 0.25, ptrY * 0.3 + saccadeY * 0.15, -1.5);

    if (!opts.still) {
      mixer?.update(dt);
      applyProceduralPose(elapsed);
      applyExpressionsAndLipSync(dt);
      vrm?.update(dt);
    } else {
      vrm?.update(0);
    }
    renderer.render(scene, camera);
  };
  rafId = requestAnimationFrame(tick);

  return {
    setEmotion(emotion, intensity = 0.7) {
      targetEmotion = emotion || "warm";
      targetIntensity = Math.max(0, Math.min(1, intensity));
    },
    setAmplitude(amp) {
      liveAmplitude = Math.max(0, Math.min(1, amp));
    },
    playVisemes(frames) {
      visemeTimeline = frames;
      visemeStartedAt = performance.now();
    },
    setPointer(nx, ny) {
      ptrX = Math.max(-1, Math.min(1, nx));
      ptrY = Math.max(-1, Math.min(1, ny));
    },
    setOrbit(a, b, z) {
      yaw = a;
      pitch = b;
      zoom = z;
      placeCamera();
    },
    setPaused(p) {
      paused = p;
    },
    stats: () => ({
      triangles: renderer.info.render.triangles,
      drawCalls: renderer.info.render.calls,
      vrmVersion,
    }),
    dispose() {
      cancelAnimationFrame(rafId);
      ro.disconnect();
      if (vrm) VRMUtils.deepDispose(root);
      renderer.dispose();
    },
  };
}
