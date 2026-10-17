// Jaeger avatar v2: a 3D VRM companion (three.js + @pixiv/three-vrm, vendored).
// Loaded on demand by jaeger_avatar.js when the mode is 'vrm'. Same hooks as
// the v1 face: expression from presence, mouth from the 0..1 speech level.
// Blinks, breathes, sways and looks at you. It renders only.
import * as THREE from './vendor/three/0.186.1/three.module.js';
import { GLTFLoader } from './vendor/three/0.186.1/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from './vendor/three-vrm/3.5.5/three-vrm.module.min.js';

// presence DISPLAY label -> VRM preset expression weights
export const EXPRESSIONS = {
  idle: { relaxed: 0.25 },
  listening: { relaxed: 0.1, surprised: 0.1 },
  thinking: { neutral: 1, lookUp: 0.35 },
  focused: { neutral: 1 },
  waiting: { relaxed: 0.35 },
  ask_owner: { surprised: 0.35, happy: 0.2 },
  blocked: { sad: 0.55 },
  complete: { happy: 0.75 },
  safe_stopped: { sad: 0.25, relaxed: 0.2 },
  offline: { relaxed: 0.6 },
};
const ALL = ['happy', 'relaxed', 'surprised', 'sad', 'angry', 'neutral', 'lookUp'];

let running = null;

export async function start(api) {
  if (running) return running;
  if (typeof window !== 'undefined' && window.innerWidth <= 768) {
    throw new Error('3D avatar disabled on compact mobile viewport');
  }
  const stale = document.getElementById('jaegerAvatar3d');
  if (stale) stale.remove();

  const loader = new GLTFLoader();
  loader.register((parser) => {
    parser.textureLoader = new THREE.TextureLoader(parser.options.manager);
    parser.textureLoader.setCrossOrigin(parser.options.crossOrigin || 'anonymous');
    return { name: 'JAEGER_img_textures' };
  });
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync('api/jaeger/avatar/model.vrm');
  const vrm = gltf.userData.vrm;
  if (!vrm) throw new Error('not a VRM');

  const panel = document.createElement('div');
  panel.id = 'jaegerAvatar3d';
  panel.title = 'Jaeger (click to switch face / 3D / off)';
  panel.style.cssText = 'position:fixed;right:12px;bottom:calc(112px + var(--keyboard-bottom-inset, 0px));z-index:9999;width:170px;height:230px;border-radius:18px;overflow:hidden;cursor:pointer;background:radial-gradient(circle at 50% 35%,#2a3350,#11131c 75%);box-shadow:0 8px 30px rgba(0,0,0,.45)';
  document.body.appendChild(panel);
  panel.addEventListener('click', () => api.cycle());

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(170, 230);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  panel.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(22, 170 / 230, 0.1, 20);
  camera.position.set(0, 1.36, 1.95);
  camera.lookAt(0, 1.3, 0);
  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(0.6, 1.8, 1.4); scene.add(key);

  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons ? VRMUtils.combineSkeletons(gltf.scene) : null;
  VRMUtils.rotateVRM0(vrm);
  scene.add(vrm.scene);
  const lookTarget = new THREE.Object3D(); camera.add(lookTarget); scene.add(camera);
  if (vrm.lookAt) vrm.lookAt.target = lookTarget;
  const bone = (n) => vrm.humanoid && vrm.humanoid.getNormalizedBoneNode(n);
  const lu = bone('leftUpperArm'), ru = bone('rightUpperArm');
  if (lu) lu.rotation.z = -1.2; if (ru) ru.rotation.z = 1.2;
  const lf = bone('leftLowerArm'), rf = bone('rightLowerArm');
  if (lf) lf.rotation.z = -0.15; if (rf) rf.rotation.z = 0.15;

  const em = vrm.expressionManager;
  const weights = Object.fromEntries(ALL.map((k) => [k, 0]));
  let mouth = 0, blinkAt = performance.now() + 2000, blinkT = -1e9, raf = 0, last = performance.now();

  function frame() {
    raf = requestAnimationFrame(frame);
    const now = performance.now(), dt = Math.min(0.1, (now - last) / 1000), t = now / 1000;
    const s = api.raw();
    const want = EXPRESSIONS[s.display] || EXPRESSIONS.idle;
    for (const k of ALL) {
      weights[k] += ((want[k] || 0) - weights[k]) * Math.min(1, dt * 4);
      if (em) em.setValue(k, weights[k]);
    }
    const target = s.speaking ? s.level : 0;
    mouth += (target - mouth) * Math.min(1, dt * 18);
    if (em) { em.setValue('aa', Math.min(1, mouth * 1.1)); em.setValue('oh', mouth * 0.3); }
    if (now > blinkAt) { blinkT = now; blinkAt = now + 2000 + Math.random() * 3500; }
    const b = Math.max(0, 1 - Math.abs(now - blinkT - 75) / 75);
    if (em) em.setValue('blink', b * (1 - weights.happy * 0.6));
    const spine = bone('spine'), chest = bone('chest'), neck = bone('neck'), head = bone('head');
    if (spine) { spine.rotation.z = Math.sin(t * 0.6) * 0.025; spine.rotation.x = Math.sin(t * 1.4) * 0.012; }
    if (chest) chest.rotation.x = Math.sin(t * 1.4 + 0.6) * 0.015;
    if (neck) neck.rotation.y = Math.sin(t * 0.35) * 0.08;
    if (head) { head.rotation.z = Math.sin(t * 0.5) * 0.04; head.rotation.x = (s.display === 'thinking' ? -0.08 : 0) + mouth * 0.05 * Math.sin(t * 9); }
    lookTarget.position.set(Math.sin(t * 0.3) * 0.15, (s.display === 'thinking' ? 0.25 : 0), 0);
    vrm.update(dt);
    renderer.render(scene, camera);
    last = now;
  }
  frame();
  running = {
    panel, vrm,
    stop() {
      cancelAnimationFrame(raf);
      panel.remove();
      VRMUtils.deepDispose(vrm.scene);
      renderer.dispose();
      running = null;
    },
  };
  return running;
}

export function stop() { if (running) running.stop(); }
export function isRunning() { return !!running; }
