import * as THREE from "three";
import type { ClipState } from "./avatar";

export interface JaegerStageHandle {
  setState(state: ClipState): void;
  setPointer(x: number, y: number): void;
  setPaused(paused: boolean): void;
  dispose(): void;
}

/** Live built-in Jaeger rig. It is deliberately procedural so the canonical
 * companion never depends on an operator-specific avatar record or download. */
export function mountJaegerStage(canvas: HTMLCanvasElement, initial: { state: ClipState; still: boolean }): JaegerStageHandle {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;

  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x30323a, 2.2)); // literal-ok (not CSS)
  const key = new THREE.DirectionalLight(0xffffff, 3.1); key.position.set(-2.5, 4, 4); scene.add(key);
  const rim = new THREE.DirectionalLight(0xb9c9ff, 1.4); rim.position.set(3, 1, -2); scene.add(rim); // literal-ok
  const camera = new THREE.PerspectiveCamera(27, 1, 0.1, 30); camera.position.set(0, -0.02, 7.75); camera.lookAt(0, -0.22, 0);

  const root = new THREE.Group(); scene.add(root);
  const bodyRoot = new THREE.Group(); root.add(bodyRoot);
  const porcelain = new THREE.MeshPhysicalMaterial({ color: 0xf3f3f5, roughness: 0.72, metalness: 0, clearcoat: 0.08 }); // literal-ok
  const shadow = new THREE.MeshStandardMaterial({ color: 0x111217, roughness: 0.9 }); // literal-ok
  const tooth = new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.52, clearcoat: 0.12 }); // literal-ok
  const accent = new THREE.MeshStandardMaterial({ color: 0x59657a, roughness: 0.5, metalness: 0.18 }); // literal-ok
  const signalMaterial = new THREE.MeshBasicMaterial({ color: 0x9fb8ff, transparent: true, opacity: 0.72 }); // literal-ok

  const mesh = (geometry: THREE.BufferGeometry, material: THREE.Material, parent: THREE.Object3D = bodyRoot) => {
    const value = new THREE.Mesh(geometry, material); value.castShadow = true; value.receiveShadow = true; parent.add(value); return value;
  };
  const headPivot = new THREE.Group(); headPivot.position.set(0, 0.78, 0); bodyRoot.add(headPivot);
  const head = mesh(new THREE.SphereGeometry(1.02, 36, 28), porcelain, headPivot); head.scale.set(1.03, 1.06, 0.98);
  const mouth = mesh(new THREE.SphereGeometry(0.61, 28, 14), shadow, headPivot); mouth.position.set(0, -0.2, 0.965); mouth.scale.set(1, 0.25, 0.1);
  for (let i = -3; i <= 3; i += 1) {
    const t = i / 3;
    const upper = mesh(new THREE.SphereGeometry(0.095, 12, 8), tooth, headPivot);
    upper.position.set(t * 0.44, -0.16 - 0.045 * t * t, 1.035); upper.scale.set(1, 0.9, 0.38);
    if (Math.abs(i) < 3) {
      const lower = mesh(new THREE.SphereGeometry(0.084, 12, 8), tooth, headPivot);
      lower.position.set(t * 0.39, -0.245 + 0.035 * t * t, 1.035); lower.scale.set(1, 0.72, 0.36);
    }
  }

  const torso = mesh(new THREE.CapsuleGeometry(0.64, 0.88, 8, 20), porcelain); torso.position.set(0, -0.84, -0.08); torso.scale.set(1, 1, 0.72);
  const leftArm = new THREE.Group(), rightArm = new THREE.Group(); bodyRoot.add(leftArm, rightArm);
  leftArm.position.set(-0.67, -0.43, 0); rightArm.position.set(0.67, -0.43, 0);
  const armGeometry = new THREE.CapsuleGeometry(0.17, 0.82, 6, 14);
  const lArm = mesh(armGeometry, porcelain, leftArm), rArm = mesh(armGeometry.clone(), porcelain, rightArm);
  lArm.position.y = -0.39; rArm.position.y = -0.39; leftArm.rotation.z = -0.34; rightArm.rotation.z = 0.34;
  const lHand = mesh(new THREE.SphereGeometry(0.24, 18, 12), porcelain, leftArm), rHand = mesh(new THREE.SphereGeometry(0.24, 18, 12), porcelain, rightArm);
  lHand.position.set(0, -0.91, 0); rHand.position.set(0, -0.91, 0);

  const leftLeg = mesh(new THREE.CapsuleGeometry(0.31, 0.78, 8, 16), porcelain), rightLeg = mesh(new THREE.CapsuleGeometry(0.31, 0.78, 8, 16), porcelain);
  leftLeg.position.set(-0.38, -1.75, 0.04); rightLeg.position.set(0.38, -1.75, 0.04); leftLeg.rotation.z = -0.16; rightLeg.rotation.z = 0.16;
  const floorShadow = mesh(new THREE.CircleGeometry(1.45, 40), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.15 }), root); // literal-ok
  floorShadow.rotation.x = -Math.PI / 2; floorShadow.position.set(0, -2.28, 0.18); floorShadow.scale.y = 0.42;

  const laptop = new THREE.Group(); root.add(laptop);
  const screen = mesh(new THREE.BoxGeometry(1.42, 0.78, 0.08), accent, laptop); screen.position.y = 0.36; screen.rotation.x = -0.12;
  const deck = mesh(new THREE.BoxGeometry(1.5, 0.08, 0.72), accent, laptop); deck.position.set(0, -0.03, 0.32); deck.rotation.x = -0.2;
  laptop.position.set(0, -1.2, 0.92); laptop.visible = false;

  const cube = mesh(new THREE.IcosahedronGeometry(0.38, 1), accent, root); cube.position.set(1.05, -0.2, 0.75); cube.visible = false;
  const signal = mesh(new THREE.TorusGeometry(1.28, 0.035, 8, 64), signalMaterial, root); signal.position.set(0, 0.68, -0.25); signal.visible = false;

  let state = initial.state, paused = false, pointerX = 0, pointerY = 0, frame = 0, last = 0;
  const clock = new THREE.Clock();
  const resize = () => {
    const width = Math.max(1, canvas.clientWidth), height = Math.max(1, canvas.clientHeight);
    renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize); ro.observe(canvas); resize();
  const setProps = () => {
    laptop.visible = state === "working";
    cube.visible = state === "making_something";
    signal.visible = state === "connecting" || state === "waiting";
  };
  setProps();
  const tick = (now: number) => {
    frame = requestAnimationFrame(tick);
    if (paused || document.hidden || now - last < 1000 / 45) return;
    last = now; const t = clock.getElapsedTime(); const motion = initial.still ? 0 : 1;
    const fast = state === "working" || state === "making_something";
    const milestone = state === "milestone_level_up";
    const breath = Math.sin(t * (fast ? 3.2 : 1.65));
    root.position.y = motion * (0.025 * breath + (milestone ? Math.abs(Math.sin(t * 4.2)) * 0.18 : 0));
    bodyRoot.scale.setScalar(1 + motion * 0.012 * breath);
    const autoYaw = state === "waiting" ? Math.sin(t * 0.8) * 0.22 : state === "connecting" ? Math.sin(t * 1.6) * 0.08 : 0;
    headPivot.rotation.y += ((pointerX * 0.28 + autoYaw) - headPivot.rotation.y) * 0.08;
    headPivot.rotation.x += ((pointerY * 0.16 + motion * 0.018 * breath) - headPivot.rotation.x) * 0.08;
    headPivot.rotation.z = motion * (fast ? Math.sin(t * 2.2) * 0.018 : Math.sin(t * 0.7) * 0.012);
    mouth.scale.y = 0.25 + motion * (milestone ? 0.055 : fast ? 0.018 : 0.008) * (1 + breath);
    if (laptop.visible) {
      leftArm.rotation.x = -0.58 + motion * Math.sin(t * 5.4) * 0.12;
      rightArm.rotation.x = -0.58 + motion * Math.sin(t * 5.4 + Math.PI) * 0.12;
    } else if (milestone) {
      leftArm.rotation.z = -1.25; rightArm.rotation.z = 1.25;
    } else {
      leftArm.rotation.z += (-0.34 - leftArm.rotation.z) * 0.08; rightArm.rotation.z += (0.34 - rightArm.rotation.z) * 0.08;
      leftArm.rotation.x *= 0.9; rightArm.rotation.x *= 0.9;
    }
    if (cube.visible) { cube.rotation.x = t * 0.8; cube.rotation.y = t * 1.2; cube.position.y = -0.18 + motion * Math.sin(t * 2) * 0.14; }
    if (signal.visible) { signal.rotation.z = t * (state === "connecting" ? 1.3 : 0.35); signal.scale.setScalar(1 + motion * 0.04 * breath); signalMaterial.opacity = 0.5 + motion * 0.22 * (1 + breath); }
    renderer.render(scene, camera);
  };
  frame = requestAnimationFrame(tick);
  return {
    setState(next) { state = next; setProps(); },
    setPointer(x, y) { pointerX = initial.still ? 0 : THREE.MathUtils.clamp(x, -1, 1); pointerY = initial.still ? 0 : THREE.MathUtils.clamp(y, -1, 1); },
    setPaused(next) { paused = next; },
    dispose() {
      cancelAnimationFrame(frame); ro.disconnect();
      root.traverse(value => { if (value instanceof THREE.Mesh) { value.geometry.dispose(); const materials = Array.isArray(value.material) ? value.material : [value.material]; materials.forEach(material => material.dispose()); } });
      renderer.dispose();
    },
  };
}
