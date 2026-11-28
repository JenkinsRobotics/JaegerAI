// An artist-made model (VRM, or a humanoid glTF/GLB) on the same rig, timing, flattening and cel look as the code-built characters.
// Every primitive gets one toon material that keeps the artist's textures and MToon colours. The look comes from: a head flattened
// along the camera axis, sphere normals on the face, hard two-tone light, a hard hair shadow, and an ink pass over a G-buffer.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMHumanoid, VRMUtils } from '@pixiv/three-vrm';
import { drawFx } from './rig.js';
import { moveNow, MOVES, STANCE } from './motion.js';
import { AnimeChar, TIMING } from './render-anime.js';
import { faceShapes, humanBone, MORPHS, EXPRESSIONS, ACTING, CAMERA } from './model-map.js';
import { Mood, drawMarks } from './anime-fx.js';

const FLAT = 0.6, FOV = 14, LIGHT = new THREE.Vector3(-0.28, 0.5, 0.82).normalize();
const lerp = (a, b, t) => a + (b - a) * t, clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const euler = (x, y, z) => new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z, 'YXZ'));
const part = (q, f) => new THREE.Quaternion().slerp(q, f);
const orth = (x, y) => y.clone().addScaledVector(x, -y.dot(x)).normalize();
const frame = (x, y) => { const z = V().crossVectors(x, y); return new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z)); };

const VERT = `
#include <common>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
attribute float aHead;
uniform vec3 uHeadV, uMouth, uIrisP, uIrisN; uniform vec2 uBrow; uniform float uFlat, uFace, uKind, uFlipS, uMouthX, uMouthR, uIrisS;
varying vec2 vUv; varying vec3 vN, vWorld; varying float vZ;
void main(){
  vUv = uv;
  #include <morphinstance_vertex>
  #include <beginnormal_vertex>
  #include <morphnormal_vertex>
  #include <skinbase_vertex>
  #include <skinnormal_vertex>
  #include <defaultnormal_vertex>
  #include <begin_vertex>
  #include <morphtarget_vertex>
  // What these models have no morph for, drawn the way a 2D animator would: one brow at a time, a mouth that slides into a smirk, pupils that shrink in shock.
  if (uKind == 1.) transformed.y += transformed.x * uFlipS < 0. ? uBrow.x : uBrow.y;
  if (uKind == 2.) { vec3 c = transformed.x > 0. ? uIrisP : uIrisN; transformed.xy = c.xy + (transformed.xy - c.xy) * uIrisS; }
  if (uFace > .5 && uMouthR > 0. && abs(transformed.z - uMouth.z) < uMouthR) {
    float m = 1. - smoothstep(.45, 1., length(transformed.xy - uMouth.xy) / uMouthR);
    transformed.x += uMouthX * uMouthR * .28 * uFlipS * m;
    transformed.y += uMouthX * (transformed.x - uMouth.x) * uFlipS * .3 * m;
  }
  #include <skinning_vertex>
  vec4 mv = modelViewMatrix * vec4(transformed, 1.);
  vWorld = (modelMatrix * vec4(transformed, 1.)).xyz;
  vN = normalize(mix(normalize(transformedNormal), normalize(mv.xyz - uHeadV), uFace * aHead));
  mv.z = mix(mv.z, uHeadV.z + (mv.z - uHeadV.z) * uFlat, aHead);   // the flatten: depth squeezes toward the head's centre, x and y stay
  vZ = uHeadV.z - mv.z;
  gl_Position = projectionMatrix * mv;
}`;

const FRAG = `
precision highp float;
layout(location=0) out vec4 outC;
layout(location=1) out vec4 outG;
uniform sampler2D map, shadeMap, emMap, uShadow;
uniform vec3 uColor, uShadeC, uEm, uL, uCenter, uRim;
uniform mat3 uHeadR;
uniform mat4 uLightVP;
uniform float uAlpha, uCut, uShift, uId, uRecv, uBlend, uFace, uCheek, uBlush, uR;
varying vec2 vUv; varying vec3 vN, vWorld; varying float vZ;
void main(){
  vec4 t = texture(map, vUv) * vec4(uColor, uAlpha);
  if (t.a < uCut) discard;
  vec3 n = normalize(vN) * (gl_FrontFacing ? 1. : -1.);
  float lit = step(0., dot(n, uL) + uShift);
  if (uRecv > .5 && lit > .5) {
    vec4 p = uLightVP * vec4(vWorld, 1.);
    vec3 s = p.xyz * .5 + .5;
    if (texture(uShadow, s.xy).r < s.z - .0025 && s.x > 0. && s.x < 1. && s.y > 0. && s.y < 1.) lit = 0.;
  }
  vec3 col = mix(texture(shadeMap, vUv).rgb * uShadeC, t.rgb, lit) + texture(emMap, vUv).rgb * uEm;
  if (uCheek > .5 && uBlush > 0.) {
    vec3 h = (vWorld - uCenter) * uHeadR / uR;
    float c = smoothstep(.34, .2, length(vec2(abs(h.x) - .5, (h.y + .38) * 1.7))) * step(0., h.z);
    col = mix(col, col * vec3(1., .62, .62), c * uBlush * .8);
  }
  if (uFace < .5) col += uRim * step(.74, 1. - abs(n.z)) * step(0., dot(n.xy, vec2(.8, .3)));    // a hard back light keeps her off the background
  outC = vec4(pow(max(col, vec3(0.)), vec3(1. / 2.2)), t.a);
  outG = vec4(uId, n.xy, uBlend > .5 ? 0. : vZ);   // blended decals write alpha 0, which leaves the G-buffer as it was
  if (uBlend > .5) outG.a = 0.;
}`;

const INK = `
precision highp float;
uniform sampler2D color, gbuf; uniform vec2 res; uniform float lineW, uK;
out vec4 frag;
float far_(vec4 g){ return g.x < .5 ? 1e4 : g.a; }
void main(){
  vec2 uv = gl_FragCoord.xy / res, e = lineW / res;
  vec4 c = texture(color, uv), g = texture(gbuf, uv);
  float edge = 0., nearest = far_(g), alphaNear = c.a; vec3 src = c.rgb;
  bool bg = g.x < .5, hair = g.x >= 1000., face = abs(g.x - 1.) < .5;
  for (int i = 0; i < 16; i++) {
    float a = float(i) * .7854;
    vec2 off = vec2(cos(a), sin(a)) * e * (i < 8 ? 1. : 1.5);
    vec4 o = texture(gbuf, uv + off);
    bool obg = o.x < .5;
    if (i >= 8 && !(bg || obg)) continue;      // the wider ring only counts for the outer silhouette
    float dep = abs(o.a - g.a), dn = length(o.yz - g.yz), thisE = 0.;
    bool other = abs(o.x - g.x) > .5, bothHair = hair && o.x >= 1000., bothFace = face && abs(o.x - 1.) < .5;
    if (bg || obg) thisE = bg && obg ? 0. : 1.;
    else if (bothHair) thisE = other && dep > .03 * uK ? .55 : 0.;
    else if (bothFace) thisE = dep > .35 * uK ? 1. : 0.;
    else if (other) thisE = 1.;
    else if (dep > .09 * uK) thisE = 1.;
    else if (dn > .7 && !hair) thisE = .7;
    edge = max(edge, thisE);
    float d = far_(o);
    if (d < nearest) { nearest = d; vec4 oc = texture(color, uv + off); src = oc.rgb; alphaNear = oc.a; }
  }
  vec3 ink = src * src * .22 + vec3(.012, .008, .02);   // coloured ink, not a black marker
  float al = max(c.a, edge * alphaNear);
  frag = vec4(mix(c.rgb, ink, edge) * al, al);
}`;

const DEPTH_V = `
#include <common>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
void main(){
  #include <morphinstance_vertex>
  #include <skinbase_vertex>
  #include <begin_vertex>
  #include <morphtarget_vertex>
  #include <skinning_vertex>
  gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.);
}`;

const white = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1); white.needsUpdate = true;
const FINGERS = ['Index', 'Middle', 'Ring', 'Little'], Y_AXIS = new THREE.Vector3(0, 1, 0);
export const STAGE = { calm: false, backdrop: true };   // calm: no zooms or shake
const VITA_HEIGHT = 1.713;   // the moves were keyed in metres on this body; other models scale from her height

export class VrmChar {
  constructor(canvas, overlay, url, who = 'nori') {
    this.c = canvas; this.ov = overlay; this.oc = overlay.getContext('2d'); this.who = who;
    this.room = document.createElement('canvas');
    this.room.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block';
    this.room.className = 'bgl';
    canvas.parentNode.insertBefore(this.room, canvas);
    this.mood = new Mood(canvas);
    const r = this.r = new THREE.WebGLRenderer({ canvas, alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: 'high-performance', preserveDrawingBuffer: true });
    this.gl = r.getContext();
    r.setClearColor(0, 0); r.autoClear = true;
    this.scene = new THREE.Scene();
    this.cam = new THREE.PerspectiveCamera(FOV, 1, 0.1, 50);
    this.U = {
      uHeadV: { value: V() }, uFlat: { value: FLAT }, uL: { value: LIGHT }, uCenter: { value: V() }, uHeadR: { value: new THREE.Matrix3() },
      uLightVP: { value: new THREE.Matrix4() }, uBlush: { value: 0 }, uR: { value: 0.12 },
      uBrow: { value: new THREE.Vector2() }, uMouth: { value: V() }, uMouthX: { value: 0 }, uMouthR: { value: 0 }, uIrisP: { value: V() }, uIrisN: { value: V() }, uIrisS: { value: 1 }, uFlipS: { value: 1 }, uRim: { value: new THREE.Color(0, 0, 0) },
    };
    this.gbuf = new THREE.WebGLRenderTarget(4, 4, { count: 2, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, generateMipmaps: false, depthBuffer: true });
    this.gbuf.textures[1].type = THREE.HalfFloatType;
    this.shadow = new THREE.WebGLRenderTarget(1536, 1536, { minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthTexture: new THREE.DepthTexture(1536, 1536), generateMipmaps: false });
    this.U.uShadow = { value: this.shadow.depthTexture };
    this.lightCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
    this.lightCam.layers.set(1);
    this.depthMat = new THREE.ShaderMaterial({ vertexShader: DEPTH_V, fragmentShader: 'void main(){}', side: THREE.DoubleSide, colorWrite: false });
    this.ink = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: 'void main(){ gl_Position = vec4(position.xy, 0., 1.); }', fragmentShader: INK,
      uniforms: { color: { value: this.gbuf.textures[0] }, gbuf: { value: this.gbuf.textures[1] }, res: { value: new THREE.Vector2() }, lineW: { value: 1 }, uK: { value: 0.2 } },
      depthTest: false, depthWrite: false, blending: THREE.NoBlending,
    });
    this.inkScene = new THREE.Scene();
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.ink); quad.frustumCulled = false; this.inkScene.add(quad);
    this.inkCam = new THREE.Camera();
    this.loader = new GLTFLoader(); this.loader.register(p => new VRMLoaderPlugin(p));
    this.scale = 1; this.slow = 0;
    this.gest = [[0, 0], [0, 0]]; this.wasTalking = false; this.nextAct = 4 + Math.random() * 6; this.act = null;
    this.wrist = [{ p: null, v: V() }, { p: null, v: V() }];
    this.hand = [{ f: [0, -1, 0], open: 0, fist: 0 }, { f: [0, -1, 0], open: 0, fist: 0 }];
    this.zoom = 1; this.zoomV = 0; this.shake = 0; this.seenEmotion = 'neutral'; this.full = 0; this.turn = 0; this.turnTo = 0; this.fullLock = false;
    this.loaded = this.load(url);
  }

  // Resolves with the model's own name, author and licence, as data for the page to show.
  async load(url) {
    const gltf = await this.loader.loadAsync(url, e => { if (e.total) this.onProgress?.(e.loaded / e.total); });
    const next = this.adopt(gltf);                     // throws before touching the scene if it isn't a humanoid, so the old model stays up
    if (this.m) { this.scene.remove(this.m.root); VRMUtils.deepDispose(this.m.root); }
    this.m = next; this.wrist = [{ p: null, v: V() }, { p: null, v: V() }]; this.hand = [{ f: [0, -1, 0], open: 0, fist: 0 }, { f: [0, -1, 0], open: 0, fist: 0 }];
    return this.meta = readMeta(gltf.userData.vrm?.meta);
  }

  adopt(gltf) {
    const vrm = gltf.userData.vrm ?? null, root = gltf.scene;
    VRMUtils.combineSkeletons(root);
    root.updateMatrixWorld(true);
    let hum = vrm?.humanoid;
    if (!hum) {
      const bones = {};
      root.traverse(n => { const b = n.name && humanBone(n.name); if (b && !bones[b]) bones[b] = { node: n }; });
      for (const need of ['hips', 'head', 'leftUpperArm', 'rightUpperArm']) if (!bones[need]) throw new Error(`No humanoid skeleton: can't find ${need}`);
      // ponytail: the rig's arm rest pose assumes a T-pose bind, as VRM requires. An A-pose glTF would have its arms off by that angle; measure the bind pose if that comes up.
      hum = new VRMHumanoid(bones);
      root.add(hum.normalizedHumanBonesRoot);
    }
    // VRM 0 and many plain glTFs face -Z. Turn the root, and conjugate every bone rotation below so the solver can stay in one frame.
    const flip = hum.getRawBoneNode('leftUpperArm').getWorldPosition(V()).x < 0;
    root.rotation.y = flip ? Math.PI : 0;
    root.traverse(n => { n.frustumCulled = false; });
    this.scene.add(root);
    root.updateMatrixWorld(true);
    hum.update?.();
    vrm?.springBoneManager?.setInitState();   // hair was set up before the turn above, and would whip around on the first frames
    const node = n => hum.getNormalizedBoneNode(n);
    const pos = n => { const b = node(n); return b ? b.getWorldPosition(V()) : null; };
    const rest = {}; for (const n of ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head', 'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand', 'leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg', 'leftFoot', 'rightFoot']) rest[n] = pos(n);
    // Which way this model's own fingers and thumb point at rest, measured from its bones, so a hand aims true whatever the artist bound.
    const handRest = {};
    for (const side of ['left', 'right']) {
      const forearm = rest[side + 'Hand'].clone().sub(rest[side + 'LowerArm']).normalize(), mid = pos(side + 'MiddleProximal'), thumb = pos(side + 'ThumbMetacarpal') ?? pos(side + 'ThumbProximal');
      const f0 = mid ? mid.sub(rest[side + 'Hand']).normalize() : forearm, th = thumb ? thumb.sub(rest[side + 'Hand']) : V(0, 0, 1);
      handRest[side] = frame(f0, orth(f0, Math.abs(orth(f0, th).z) > 0.3 ? th : V(0, 0, 1))).invert();
    }
    const legs = !!(rest.leftFoot && rest.rightFoot && rest.leftLowerLeg && rest.rightLowerLeg);


    const inHead = new Set(); hum.getRawBoneNode('head').traverse(n => inHead.add(n));
    const meshes = []; root.traverse(n => { if (n.isMesh) meshes.push(n); });
    // GLTFLoader only reads morph names from the mesh's extras, and VRoid keeps them on the primitives.
    for (const mesh of meshes) {
      const at = gltf.parser.associations.get(mesh), names = at && gltf.parser.json.meshes[at.meshes]?.primitives[at.primitives ?? 0]?.extras?.targetNames;
      if (!mesh.morphTargetDictionary?.[names?.[0]] && names) mesh.morphTargetDictionary = Object.fromEntries(names.map((n, i) => [n, i]));
    }
    const box = new THREE.Box3(), faceBox = new THREE.Box3(), tmp = V();
    meshes.forEach((mesh, i) => {
      const g = mesh.geometry, P = g.attributes.position, N = P.count, w = new Float32Array(N);
      let sum = 0;
      for (let v = 0; v < N; v++) {
        if (mesh.isSkinnedMesh) for (let k = 0; k < 4; k++) { if (inHead.has(mesh.skeleton.bones[g.attributes.skinIndex.getComponent(v, k)])) w[v] += g.attributes.skinWeight.getComponent(v, k); }
        sum += w[v];
      }
      g.setAttribute('aHead', new THREE.BufferAttribute(w, 1));
      const headish = sum / N > 0.5, morphs = !!g.morphAttributes.position?.length, isFace = headish && morphs, isHair = headish && !morphs;
      for (let v = 0; v < N; v += 7) { tmp.fromBufferAttribute(P, v).applyMatrix4(mesh.matrixWorld); box.expandByPoint(tmp); if (isFace && w[v] > 0.9) faceBox.expandByPoint(tmp); }
      if (isHair || isFace) mesh.layers.enable(1);   // the shadow's depth bias is wider than a nose, so only hair and the chin leave a mark
      mesh.material = this.toon(Array.isArray(mesh.material) ? mesh.material[0] : mesh.material, { id: isFace ? 1 : isHair ? 1000 + i : 2 + i, isFace, isHair });
      if (Array.isArray(g.groups) && g.groups.length) g.clearGroups();   // the second group was the MToon outline; the ink pass draws lines now
    });
    if (faceBox.isEmpty()) faceBox.copy(box);
    const center = faceBox.getCenter(V()), size = faceBox.getSize(V());
    this.U.uR.value = Math.max(size.x, size.y) / 2;

    // Where the mouth and each iris are, measured from the model itself: the mouth from what the "ah" morph moves, the irises from their own mesh.
    this.U.uFlipS.value = flip ? -1 : 1;
    this.U.uMouthR.value = 0;
    const irisBox = { p: new THREE.Box3(), n: new THREE.Box3() };
    for (const mesh of meshes) {
      const P = mesh.geometry.attributes.position;
      if (/iris/i.test(mesh.material.name)) for (let v = 0; v < P.count; v++) { tmp.fromBufferAttribute(P, v); irisBox[tmp.x > 0 ? 'p' : 'n'].expandByPoint(tmp); }
    }
    if (!irisBox.p.isEmpty()) irisBox.p.getCenter(this.U.uIrisP.value);
    if (!irisBox.n.isEmpty()) irisBox.n.getCenter(this.U.uIrisN.value);
    const eyeAt = b => b.isEmpty() ? null : root.localToWorld(b.getCenter(V())).sub(center);
    const eyes = [eyeAt(irisBox.p) ?? V(-size.x * 0.2, 0, size.x * 0.4), eyeAt(irisBox.n) ?? V(size.x * 0.2, 0, size.x * 0.4)];
    // Bind face shapes to morph targets by name, with the VRM's standard expressions as a fallback.
    const binds = {};
    for (const shape of Object.keys(MORPHS)) {
      const morphs = [];
      for (const mesh of meshes) if (mesh.morphTargetDictionary) for (const [name, i] of Object.entries(mesh.morphTargetDictionary)) if (MORPHS[shape].test(name)) morphs.push([mesh, i]);
      const expr = !morphs.length && EXPRESSIONS[shape] && vrm?.expressionManager?.getExpression(EXPRESSIONS[shape]) ? EXPRESSIONS[shape] : null;
      if (morphs.length || expr) binds[shape] = { morphs, expr };
    }

    const mouthBox = new THREE.Box3();
    for (const [mesh, i] of binds.aa?.morphs ?? []) {
      const D = mesh.geometry.morphAttributes.position?.[i], P = mesh.geometry.attributes.position;
      if (!D) continue;
      for (let v = 0; v < D.count; v++) if (Math.hypot(D.getX(v), D.getY(v), D.getZ(v)) > 0.002) mouthBox.expandByPoint(tmp.fromBufferAttribute(P, v));
    }
    if (!mouthBox.isEmpty()) { mouthBox.getCenter(this.U.uMouth.value); this.U.uMouthR.value = mouthBox.getSize(tmp).x * 0.95; }

    const L = rest.leftUpperArm.distanceTo(rest.leftLowerArm) + rest.leftLowerArm.distanceTo(rest.leftHand);
    const top = box.max.y, low = rest.hips.y + (rest.neck.y - rest.hips.y) * 0.18;
    this.ink.uniforms.uK.value = L / 2.25;
    const ls = (top - rest.hips.y) * 0.75, lc = V(0, lerp(rest.hips.y, top, 0.6), 0);
    Object.assign(this.lightCam, { left: -ls, right: ls, top: ls, bottom: -ls });
    this.lightCam.position.copy(lc).addScaledVector(LIGHT, 3); this.lightCam.lookAt(lc); this.lightCam.updateProjectionMatrix(); this.lightCam.updateMatrixWorld();
    this.U.uLightVP.value.multiplyMatrices(this.lightCam.projectionMatrix, this.lightCam.matrixWorldInverse);
    const body = measureBody(hum, meshes, node, L / 2.25);
    const tipBone = pos('leftMiddleDistal') ?? pos('leftMiddleIntermediate');
    return {
      vrm, root, hum, flip, node, rest, handRest, legs, baseYaw: root.rotation.y, binds, top, low, L, a: L / 2.25, hipsRest: node('hips').position.clone(), meshes,
      body, handLen: tipBone ? tipBone.distanceTo(rest.leftHand) * 1.1 : L * 0.16,
      eyes, spine: ['spine', 'chest', 'upperChest'].filter(node), offset: center.clone().sub(rest.head), hasBlush: !!binds.blush,
      width: rest.leftUpperArm.distanceTo(rest.rightUpperArm),
    };
  }

  toon(mat, { id, isFace, isHair }) {
    const unlit = /eye|brow|lash|mouth/i.test(mat.name) && !mat.shadeColorFactor;
    const blend = mat.transparent && (isFace || mat.opacity < 0.9);     // only decals and glass stay blended, everything else gets a hard cut so it can have an ink line
    const em = mat.emissive ? mat.emissive.clone().multiplyScalar(mat.emissiveIntensity ?? 1) : new THREE.Color(0, 0, 0);
    const shadeC = mat.shadeColorFactor ? mat.shadeColorFactor.clone() : unlit ? new THREE.Color(1, 1, 1) : mat.color.clone().multiply(new THREE.Color(0.72, 0.64, 0.74));
    const shadeTex = mat.shadeMultiplyTexture ?? mat.map ?? white;
    return new THREE.ShaderMaterial({
      name: mat.name, glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG, side: mat.side, transparent: blend, depthWrite: blend ? mat.depthWrite : true,
      blending: blend ? THREE.NormalBlending : THREE.NoBlending, toneMapped: false,
      uniforms: {
        ...this.U, map: { value: mat.map ?? white }, shadeMap: { value: shadeTex }, emMap: { value: mat.emissiveMap ?? white },
        uColor: { value: mat.color.clone() }, uShadeC: { value: shadeC }, uEm: { value: em }, uAlpha: { value: blend ? mat.opacity : 1 },
        uCut: { value: blend ? (mat.alphaTest || 0.01) : (mat.alphaTest || (mat.transparent ? 0.5 : 0)) },
        uKind: { value: /brow/i.test(mat.name) ? 1 : /iris|highlight/i.test(mat.name) ? 2 : 0 },
        uShift: { value: isFace ? 0.28 : (mat.shadingShiftFactor ?? 0) + 0.08 }, uId: { value: id }, uRecv: { value: isHair ? 0 : 1 }, uBlend: { value: blend ? 1 : 0 }, uFace: { value: isFace ? 1 : 0 }, uCheek: { value: isFace && !/eye|iris|highlight|brow|lash|mouth/i.test(mat.name) ? 1 : 0 },
      },
    });
  }

  // Moves p (world) out to the body's surface plus `skin`. Returns how far it moved, or null if it was already outside.
  keepOut(p, skin) {
    let moved = null;
    for (const B of this.m.body) {
      const b = this.m.node(B.name), at = b.getWorldPosition(V());
      const since = b.getWorldQuaternion(new THREE.Quaternion()).multiply(B.q0.clone().invert());   // this bone's turn since the rest pose
      const r = p.clone().sub(at).applyQuaternion(since.clone().invert()).add(B.pos0);              // p, in the rest pose where the slices were measured
      const s = B.slices[Math.floor((r.y - B.y0) / B.h)];
      if (!s) continue;
      const dx = r.x - s.cx, dz = r.z - s.cz, rx = (dx > 0 ? s.xp : s.xn) + skin, rz = (dz > 0 ? s.zp : s.zn) + skin;
      if ((dx / rx) ** 2 + (dz / rz) ** 2 >= 1) continue;
      // Out the shortest way, sideways or front-to-back: past a wide, thin coat tail a hand slips in front of it rather than being thrown wide.
      const fz = Math.sign(dz) || this.m.body.front, toX = rx * Math.sqrt(Math.max(0, 1 - (dz / rz) ** 2)) * (Math.sign(dx) || 1);
      const toZ = ((fz > 0 ? s.zp : s.zn) + skin) * Math.sqrt(Math.max(0, 1 - (dx / rx) ** 2)) * fz;
      if (Math.abs(toX - dx) <= Math.abs(toZ - dz)) r.x = s.cx + toX; else r.z = s.cz + toZ;
      const to = r.sub(B.pos0).applyQuaternion(since).add(at);
      moved = (moved ?? V()).add(to.clone().sub(p)); p.copy(to);
    }
    return moved;
  }

  // --- the same skeleton as AnimeChar, in the model's own proportions. Solved every frame, whatever is shown. ---------------
  pose(rig, dt) {
    const m = this.m, o = rig.out, t = rig.t, h = Math.min(dt, 1 / 30), { node, a, L, flip } = m;
    // Spring bones never recover from a bad number, so one must never reach them: a single frame would lose the hair for good.
    const put = (n, q) => { const b = node(n); if (!b || !Number.isFinite(q.x + q.y + q.z + q.w)) return; b.quaternion.copy(q); if (flip) { b.quaternion.x *= -1; b.quaternion.z *= -1; } };
    // A full-body move, in this model's size. Everything below is solved with the root square on; the spin and hop go on at the very end.
    const mv = moveNow(rig.act), W_ = mv ? mv.weight : 0, M = mv ? mv.pose : STANCE, k = m.top / VITA_HEIGHT, fx = flip ? -1 : 1;
    m.root.position.set(0, 0, 0); m.root.rotation.y = m.baseYaw;
    const hips = node('hips');
    hips.position.copy(m.hipsRest); hips.position.y += (-o.crouch * 0.22 + o.lift * 0.12) * a * (1 - W_ * 0.8); hips.position.x += o.hipX * 0.05 * a * fx;
    hips.position.x += W_ * M.shiftX * k * fx; hips.position.z += W_ * M.shiftZ * k * fx; hips.position.y -= W_ * Math.max(0, M.crouch) * 0.13 * k;
    const Rp = euler(W_ * M.bodyX * 0.5, W_ * M.hipYaw, W_ * M.hipZ);
    put('hips', Rp);

    // Legs: the feet stay where they were put and the pelvis moves over them. During a move, the pelvis drops rather than let a foot leave the floor.
    if (m.legs) {
      const footAt = {};
      for (const [side, K] of [['left', 'L'], ['right', 'R']]) footAt[side] = m.rest[side + 'Foot'].clone().add(V(W_ * M['foot' + K + 'X'], W_ * (Math.max(0, M['step' + K]) + Math.abs(Math.sin(M['footPitch' + K])) * 0.09), W_ * M['foot' + K + 'Z']).multiplyScalar(k));
      let drop = 0;
      for (const side of ['left', 'right']) {
        const H = node(side + 'UpperLeg').getWorldPosition(V()), F = footAt[side], len = m.rest[side + 'UpperLeg'].distanceTo(m.rest[side + 'LowerLeg']) + m.rest[side + 'LowerLeg'].distanceTo(m.rest[side + 'Foot']);
        drop = Math.max(drop, H.y - F.y - Math.sqrt(Math.max(0, (len * 0.985) ** 2 - (H.x - F.x) ** 2 - (H.z - F.z) ** 2)));
      }
      hips.position.y -= W_ * clamp(drop, 0, 0.14 * k);
      [-1, 1].forEach(s => {
        const side = s > 0 ? 'left' : 'right', K = s > 0 ? 'L' : 'R', H0 = m.rest[side + 'UpperLeg'], K0 = m.rest[side + 'LowerLeg'], F0 = m.rest[side + 'Foot'];
        const H = node(side + 'UpperLeg').getWorldPosition(V()), up = H0.distanceTo(K0), lo = K0.distanceTo(F0);
        const d = footAt[side].clone().sub(H); let dl = d.length(); const reach = (up + lo) * 0.999;
        if (dl > reach) { d.multiplyScalar(reach / dl); dl = reach; }
        const u = d.clone().normalize(), al = (up * up - lo * lo + dl * dl) / (2 * dl), hh = Math.sqrt(Math.max(0, up * up - al * al));
        const pole = V(s * 0.12 + W_ * M.shiftX * 0.3, 0.5, 0.6 + W_ * M.shiftZ); pole.addScaledVector(u, -pole.dot(u)).normalize();
        const Kn = H.clone().addScaledVector(u, al).addScaledVector(pole, hh), hinge = V().crossVectors(u, pole).normalize();
        const dU = Kn.clone().sub(H).normalize(), dL = H.clone().add(d).sub(Kn).normalize(), d0U = K0.clone().sub(H0).normalize(), d0L = F0.clone().sub(K0).normalize(), z = V(0, 0, 1);
        const QU = frame(dU, orth(dU, hinge)).multiply(frame(d0U, orth(d0U, V().crossVectors(d0U, z))).invert());
        const QL = frame(dL, orth(dL, hinge)).multiply(frame(d0L, orth(d0L, V().crossVectors(d0L, z))).invert());
        put(side + 'UpperLeg', Rp.clone().invert().multiply(QU));
        put(side + 'LowerLeg', QU.clone().invert().multiply(QL));
        put(side + 'Foot', QL.clone().invert().multiply(euler(W_ * M['footPitch' + K], 0, 0)));
      });
    }

    const Rc = euler(-o.chestPitch * 0.5 - o.breath * 0.012 + W_ * M.bodyX, o.chestYaw * 0.9 - 0.2 + W_ * (M.bodyYaw + M.hipYaw), o.chestRoll * 0.75 + W_ * (M.bodyZ + M.hipZ));
    const spineQ = Rp.clone().invert().multiply(Rc);
    for (const n of m.spine) put(n, part(spineQ, 1 / m.spine.length));
    const Rh = euler(-o.pitch * 0.5 + W_ * (M.bodyX * 0.75 + M.headX), o.yaw * 0.62 + 0.08 + W_ * (M.bodyYaw * 0.78 + M.headY), o.roll * 0.42 + 0.03 + W_ * (M.bodyZ * 0.65 + M.hipZ * 0.7 + M.headZ));
    const rel = Rc.clone().invert().multiply(Rh);
    if (node('neck')) { put('neck', part(rel, 0.4)); put('head', part(rel, 0.6)); } else put('head', rel);

    // Each burst of speech picks a fresh gesture; a hand goes somewhere on its own now and then.
    const talking = o.hand > 0.16;
    if (talking && !this.wasTalking) { const pick = () => [(Math.random() - 0.5) * 0.9, (Math.random() - 0.3) * 0.7]; this.gest = [pick(), pick()]; }
    this.wasTalking = talking;
    this.nextAct -= dt;
    if (this.nextAct <= 0 && !this.act && rig.mode === 'idle') { this.act = { t: 0, dur: 2.2 + Math.random(), s: Math.random() < 0.5 ? 0 : 1 }; this.nextAct = 8 + Math.random() * 9; }
    let actE = 0;
    if (this.act) { const A = this.act; A.t += dt; const u = A.t / A.dur; actE = u >= 1 ? 0 : Math.min(1, u * 4) * Math.min(1, (1 - u) * 3.5); if (u >= 1 || rig.mode !== 'idle') this.act = null; }

    const HT = node('head').getWorldPosition(V()).add(m.offset.clone().applyQuaternion(Rh)), R = this.U.uR.value;
    const chestAt = node('upperChest') ?? node('chest') ?? node('spine');
    const anchors = { face: [HT, R], chest: [chestAt.getWorldPosition(V()), a], hip: [hips.getWorldPosition(V()), a] };
    const acting = ACTING[rig.emotion];
    [-1, 1].forEach((s, i) => {
      const side = s > 0 ? 'left' : 'right';           // s is the viewer's side: +1 on the viewer's right is the character's left
      const raise = (s < 0 ? o.shL : o.shR);
      const K = s > 0 ? 'L' : 'R', shQ = euler(0, 0, s * (raise * 0.25 + W_ * M.shoulders * 0.15));
      put(side + 'Shoulder', shQ);
      const parent = Rc.clone(); if (node(side + 'Shoulder')) parent.multiply(shQ);
      node(side + 'UpperArm').updateWorldMatrix(true, false);
      const S = node(side + 'UpperArm').getWorldPosition(V()), S0 = m.rest[side + 'UpperArm'];

      // Targets from the anime rig, as offsets from the resting shoulder in units of the arm (2.25 long there), so they fit any model.
      const wave = s > 0 ? clamp(o.wave, 0, 1) : 0, shrug = clamp(o.shrug, 0, 1), talk = clamp(o.hand * (s > 0 ? 0.95 : 0.55), 0, 1), g = this.gest[i];
      let T = [s * 0.4 + talk * (s * -0.5 + g[0]), -3.15 + talk * (2.5 + g[1]), 0.1 + talk * 0.9];
      let fingers = [s * 0.2, talk > 0.2 ? 0.8 : -1, talk > 0.2 ? 0.5 : 0], open = talk, poleV = [s * 0.35, -0.75, -0.55];
      const A = acting?.[s > 0 ? 'a' : 'b'];
      if (A) {        // the feeling's own pose. The wrist spring carries the hand there, with overshoot. Talking only stirs it.
        const [at, unit] = A.at === 'shoulder' ? [S0, a] : anchors[A.at];
        const w_ = at.clone().add(V(A.p[0] * s, A.p[1], A.p[2]).multiplyScalar(unit)).sub(S0).divideScalar(a);
        T = [w_.x + talk * g[0] * 0.22, w_.y + talk * (g[1] * 0.2 + 0.06 * Math.sin(t * 7 + i)), w_.z];
        fingers = [A.f[0] * s, A.f[1], A.f[2]]; open = Math.max(A.open, talk * 0.5);
        if (A.pole) poleV = [A.pole[0] * s, A.pole[1], A.pole[2]];
      }
      if (this.act && this.act.s === i && !A) {              // a hand comes up to rest on the chest; near the head it would clip through whatever hair the artist made
        T = [lerp(T[0], -s * 0.35, actE), lerp(T[1], -1.5, actE), lerp(T[2], 0.95, actE)];
        fingers = [lerp(fingers[0], -s * 0.8, actE), lerp(fingers[1], 0.35, actE), lerp(fingers[2], 0.1, actE)]; open = Math.max(open, actE * 0.6);
      }
      T = [lerp(T[0], s * 0.95, shrug), lerp(T[1], -0.85, shrug), lerp(T[2], 0.95, shrug)];
      fingers = [lerp(fingers[0], s * 0.75, shrug), lerp(fingers[1], 0.5, shrug), lerp(fingers[2], 0.4, shrug)]; open = Math.max(open, shrug);
      T = [lerp(T[0], 1.05 + Math.sin(t * 9.5) * 0.2, wave) + Math.sin(Math.PI * wave) * 0.5, lerp(T[1], 0.95 + Math.cos(t * 9.5) * 0.05, wave), lerp(T[2], 0.6, wave)];
      fingers = [lerp(fingers[0], Math.sin(t * 9.5) * 0.3, wave), lerp(fingers[1], 1, wave), lerp(fingers[2], 0.1, wave)]; open = Math.max(open, wave);
      if (W_ > 0) {                                    // the move's hand: arm lengths from where the shoulder is right now
        const q = V(s * M['hand' + K + 'X'], M['hand' + K + 'Y'], M['hand' + K + 'Z']), to = S.clone().addScaledVector(q, L).sub(S0).divideScalar(a), dir = q.normalize(), palm = M['palm' + K];
        T = [lerp(T[0], to.x, W_), lerp(T[1], to.y, W_), lerp(T[2], to.z, W_)];
        fingers = [lerp(fingers[0], lerp(dir.x, 0, palm), W_), lerp(fingers[1], lerp(dir.y, 1, palm), W_), lerp(fingers[2], lerp(dir.z, 0.1, palm), W_)];
        open = lerp(open, 1 - M['curl' + K], W_);
      }
      const target = S0.clone().add(V(T[0], T[1], T[2]).multiplyScalar(a));
      const hs = this.hand[i], ease = 1 - Math.exp(-dt * 16);     // fingers close and open over a few frames instead of snapping
      for (let k = 0; k < 3; k++) hs.f[k] += (fingers[k] - hs.f[k]) * ease;
      hs.open += (open - hs.open) * ease; hs.fist += ((A?.fist && !wave ? 1 - W_ : 0) - hs.fist) * ease; fingers = hs.f; open = hs.open;
      hs.turn = (hs.turn ?? 0) + (W_ * Math.abs(M['palmTurn' + K]) / 1.35 - (hs.turn ?? 0)) * ease; hs.point = (hs.point ?? 0) + (W_ * M['point' + K] - (hs.point ?? 0)) * ease;

      const w = this.wrist[i];                         // wrists lag, so hands have weight
      if (!w.p) w.p = target.clone();
      const K_ = 150, C_ = 2 * 0.72 * Math.sqrt(K_);
      w.v.addScaledVector(target.clone().sub(w.p).multiplyScalar(K_).addScaledVector(w.v, -C_), h); w.p.addScaledVector(w.v, h);
      // two-bone IK with the model's real bone lengths; the elbow sits in the plane of the arm and a pole that points down, back and out
      const E0 = m.rest[side + 'LowerArm'], H0 = m.rest[side + 'Hand'], up = S0.distanceTo(E0), fo = E0.distanceTo(H0), reach = (up + fo) * 0.995;
      // The body is solid. The hand goes where the arm can really reach, then stops at the body's surface, wrist and fingertips both,
      // losing the speed that was carrying it in, so it settles there. Pushing out and staying in reach are repeated until both hold.
      const goal = w.p.clone(), inReach = () => { const v = goal.clone().sub(S), l = v.length(); if (l > reach) goal.copy(S).addScaledVector(v, reach / l); };
      const tipDir = V(hs.f[0], hs.f[1], hs.f[2]).normalize(), settle = moved => { if (!moved) return; const n = moved.clone().normalize(), vn = w.v.dot(n); if (vn < 0) w.v.addScaledVector(n, -vn); };
      const clear = () => {
        for (let k = 0; k < 3; k++) {
          inReach();
          settle(this.keepOut(goal, a * 0.12));
          const tip = goal.clone().addScaledVector(tipDir, m.handLen), tipMoved = this.keepOut(tip, a * 0.05);
          if (tipMoved) { goal.add(tipMoved); settle(tipMoved); }
          else if (k) break;
        }
      };
      inReach(); if (hs.lean) goal.add(hs.lean);      // lean from where the hand can be, or a far-off target swallows it
      clear();
      const pole = V(poleV[0], poleV[1], poleV[2]);
      let d, u, E, W;
      const solve = () => {
        d = goal.clone().sub(S); let dl = d.length();
        if (dl > reach) { d.multiplyScalar(reach / dl); dl = reach; }
        u = d.clone().normalize(); const al = (up * up - fo * fo + dl * dl) / (2 * dl), hh = Math.sqrt(Math.max(0, up * up - al * al));
        pole.addScaledVector(u, -pole.dot(u)).normalize();
        E = S.clone().addScaledVector(u, al).addScaledVector(pole, hh); W = S.clone().add(d);
        return S.clone().addScaledVector(u, al);
      };
      let mid = solve();
      // An elbow inside the waist swings out, and a forearm through the body takes the hand with it; then solve again.
      const elbow = E.clone(), fore = E.clone().lerp(W, 0.5);
      const elbowMoved = this.keepOut(elbow, a * 0.1), foreMoved = this.keepOut(fore, a * 0.1);
      if (foreMoved) { goal.add(foreMoved); settle(foreMoved); clear(); }
      if (elbowMoved) pole.copy(elbow.sub(mid));
      if (elbowMoved || foreMoved) mid = solve();
      const dU = E.clone().sub(S).normalize(), dF = W.clone().sub(E).normalize(), hinge = V().crossVectors(pole, u).normalize();
      const d0U = E0.clone().sub(S0).normalize(), d0F = H0.clone().sub(E0).normalize(), z = V(0, 0, 1);
      const n0U = V().crossVectors(d0U, z).normalize(), n0F = V().crossVectors(d0F, z).normalize();
      const QU = frame(dU, orth(dU, hinge)).multiply(frame(d0U, orth(d0U, n0U)).invert());
      let QF = frame(dF, orth(dF, hinge)).multiply(frame(d0F, orth(d0F, n0F)).invert());
      // Hand: fingers along `fingers`, thumb forward when the hand hangs and toward the body when it rises.
      const along = V(fingers[0], fingers[1], fingers[2]).normalize();
      const rise = THREE.MathUtils.smoothstep(along.y, -0.6, 0.2);
      const thumb = orth(along, V(-s * rise * (1 - hs.turn), 0, (1 - rise) * (1 - hs.turn) - hs.turn + 0.001));   // turn: palms facing each other, for a clap
      const QH = frame(along, thumb).multiply(m.handRest[side]);
      // Half the wrist's twist goes into the forearm, which stops the wrist wringing like a candy wrapper.
      let handL = QF.clone().invert().multiply(QH);
      const ax = d0F, dp = handL.x * ax.x + handL.y * ax.y + handL.z * ax.z;
      const twist = part(new THREE.Quaternion(ax.x * dp, ax.y * dp, ax.z * dp, handL.w).normalize(), 0.6);
      QF.multiply(twist); handL = twist.clone().invert().multiply(handL);
      put(side + 'UpperArm', parent.clone().invert().multiply(QU));
      put(side + 'LowerArm', QU.clone().invert().multiply(QF));
      put(side + 'Hand', handL);

      // Fingers curl toward the palm and fan out as the hand opens.
      const curl = lerp(lerp(0.55, 0.03, open) * 1.25, 1.45, hs.fist), fan = lerp(0.03, 0.2, open);
      FINGERS.forEach((f, k_) => {
        const fingerCurl = k_ === 0 ? lerp(curl, 0.05, hs.point) : lerp(curl, 1.3, hs.point);
        const spread = euler(0, -s * fan * (1.1 - k_ * 0.7), 0), bend = euler(0, 0, -s * fingerCurl);
        put(side + f + 'Proximal', spread.multiply(bend)); put(side + f + 'Intermediate', bend); put(side + f + 'Distal', bend);
      });
      const tb = euler(0, s * curl * 0.5, 0);
      put(side + 'ThumbProximal', tb); put(side + 'ThumbDistal', tb);
      // Curled fingers reach past the straight-line guess above. Measure the real fingertip, and lean the hand out by what it lacked
      // on the next frame; the lean fades slowly once the fingers are clear, so the hand rests against the body instead of tapping it.
      let missed = null;
      for (const f of [...FINGERS, 'Thumb']) {
        const tip = node(side + f + 'Distal'), by = tip && this.keepOut(tip.getWorldPosition(V()), a * 0.02);
        if (by && (!missed || by.lengthSq() > missed.lengthSq())) missed = by;
      }
      hs.lean = (hs.lean ?? V()).multiplyScalar(missed ? 1 : 0.98);
      if (missed) hs.lean.addScaledVector(missed, 0.5).clampLength(0, a * 1.2);
    });

    // Eyes: the VRM's own look-at when there is one, otherwise the eye bones.
    const yaw = clamp(o.gazeX, -1, 1), pitch = clamp(o.gazeY, -1, 1);
    if (m.vrm?.lookAt) { m.vrm.lookAt.yaw = yaw * 11; m.vrm.lookAt.pitch = pitch * 9; }
    else { const q = euler(-pitch * 0.14, yaw * 0.18, 0); put('leftEye', q); put('rightEye', q); }

    const shapes = faceShapes(o, TIMING.onTwos);
    for (const [k, b] of Object.entries(m.binds)) if (b.expr) m.vrm.expressionManager.setValue(b.expr, shapes[k]);
    // The spin turns about the standing foot and the hop leaves the floor. The hair is simulated after this, so it swings with them.
    const spin = W_ > 0 ? M.spin ?? 0 : 0, Qs = new THREE.Quaternion().setFromAxisAngle(Y_AXIS, spin), anchor = m.legs ? m.rest.leftFoot.clone().setY(0) : V();
    anchor.z += 0.08 * k; anchor.multiplyScalar(W_ > 0 ? M.pivot ?? 0 : 0);
    const shift = anchor.clone().sub(anchor.clone().applyQuaternion(Qs)); shift.y = (W_ > 0 ? M.lift ?? 0 : 0) * k;
    this.turn += (this.turnTo - this.turn) * (1 - Math.exp(-dt * 8));   // the view buttons turn her, and a spin adds to that
    const Qt = new THREE.Quaternion().setFromAxisAngle(Y_AXIS, spin + this.turn);
    m.root.rotation.y = m.baseYaw + spin + this.turn; m.root.position.copy(shift);
    if (m.vrm) m.vrm.update(h); else m.hum.update();
    for (const b of Object.values(m.binds)) for (const [mesh, i] of b.morphs) mesh.morphTargetInfluences[i] = 0;
    for (const [k, b] of Object.entries(m.binds)) for (const [mesh, i] of b.morphs) mesh.morphTargetInfluences[i] += shapes[k];
    this.U.uBlush.value = m.hasBlush ? 0 : shapes.blush;
    const brow = (o.browL + o.browR) / 2, ask = (o.browL - o.browR) / 2;
    this.U.uBrow.value.set((brow * 0.05 + ask * 0.2) * R, (brow * 0.05 - ask * 0.2) * R);
    this.U.uMouthX.value = clamp(o.mouthX, -1, 1);
    this.U.uIrisS.value = lerp(1, clamp(o.pupil, 0.5, 1.3), 0.85);
    this.Rh = Qt.clone().multiply(Rh); this.headAt = HT.clone().applyQuaternion(Qt).add(shift);

    // The camera acts too: stiff springs for a shock, slow drifts for quiet feelings, and it pulls back when the arms need room.
    if (rig.emotion !== this.seenEmotion) { this.seenEmotion = rig.emotion; if (!STAGE.calm && ['surprised', 'angry', 'scared'].includes(rig.emotion)) this.shake = 1; }
    const [zoomTo, zk] = (!STAGE.calm && CAMERA[rig.emotion]) || [1, 25], wide = Math.max(clamp(o.wave, 0, 1), clamp(o.shrug, 0, 1));
    const want = lerp(zoomTo + (rig.mode === 'speaking' ? 0.03 : 0), 0.93, wide);
    this.zoomV += (zk * (want - this.zoom) - 2 * 0.8 * Math.sqrt(zk) * this.zoomV) * h; this.zoom += this.zoomV * h;
    this.shake *= Math.exp(-dt * 5);
    this.full += ((this.fullLock || (rig.act && MOVES[rig.act.name]?.wide)) && m.legs ? 1 - this.full : -this.full) * (1 - Math.exp(-dt * 7));   // the shot widens to the whole body for a move that needs the floor
  }

  draw(rig, W, H, dt, force = false) {
    const o = rig.out, Z = Math.min(W, H) / 1000;
    if (this.rw !== W || this.rh !== H) { this.rw = W; this.rh = H; AnimeChar.prototype.paintRoom.call(this, W, H, Z); }
    this.room.style.transform = `translate(${-4 - o.yaw * 0.5}%,${-4 + o.pitch * 0.3}%)`;
    if (!this.m || rig.t === 0) return;                // the rig's skeleton channels don't exist until its first tick
    this.pose(rig, dt);
    // Film anime holds each drawing for two or three frames. The skeleton keeps running underneath; we only show it on twos.
    if (TIMING.onTwos && !force && rig.t - (this.shownAt ?? -1) < 1 / 12 - 0.004) return;
    this.shownAt = rig.t;

    if (dt > 1 / 45) this.slow++; else this.slow = Math.max(0, this.slow - 0.25);
    if (this.slow > 20 && this.scale > 0.45) { this.scale *= 0.85; this.slow = 0; }
    // Ink lines need more pixels than a 1x screen has. A 2x screen already has them.
    const ss = devicePixelRatio >= 1.5 ? 1 : 2;
    const w = Math.round(W * this.scale * ss), h = Math.round(H * this.scale * ss), r = this.r, m = this.m, U = this.U;
    if (this.c.width !== w || this.c.height !== h) { r.setSize(w, h, false); }
    if (this.gbuf.width !== w || this.gbuf.height !== h) this.gbuf.setSize(w, h);

    // Waist-up framing on a long lens, which is most of what makes a mesh read as drawn.
    const vis = (m.top - m.low) * 1.1, need = Math.max(vis, m.width * 3.4 / (w / h));
    const wideOut = this.full * this.full * (3 - 2 * this.full), fit = lerp(need / this.zoom, Math.max(need, m.top * 1.3), wideOut), jolt = this.shake * m.width * 0.05, cam = this.cam;
    cam.aspect = w / h;
    cam.position.set(this.headAt.x * (this.zoom - 1) * 0.8 * (1 - wideOut) + Math.sin(rig.t * 61) * jolt, lerp(m.top - fit * 0.47, m.top * 0.56, wideOut) + Math.cos(rig.t * 47) * jolt, fit / 2 / Math.tan(FOV * Math.PI / 360));
    cam.updateProjectionMatrix(); cam.updateMatrixWorld();
    U.uCenter.value.copy(this.headAt); U.uHeadR.value.setFromMatrix4(new THREE.Matrix4().makeRotationFromQuaternion(this.Rh));
    U.uHeadV.value.copy(this.headAt).applyMatrix4(cam.matrixWorldInverse);

    this.scene.overrideMaterial = this.depthMat;
    r.setRenderTarget(this.shadow); r.render(this.scene, this.lightCam);
    this.scene.overrideMaterial = null;
    r.setRenderTarget(this.gbuf); r.render(this.scene, cam);
    r.setRenderTarget(null);
    this.ink.uniforms.res.value.set(w, h); this.ink.uniforms.lineW.value = Math.max(1, Math.min(w, h) / 620);
    r.render(this.inkScene, this.inkCam);

    const oc = this.oc;
    if (this.ov.width !== W || this.ov.height !== H) { this.ov.width = W; this.ov.height = H; }
    oc.clearRect(0, 0, W, H);
    const plain = document.body.dataset.bg && document.body.dataset.bg !== 'room';   // green screen or transparent: nothing but the character and her marks
    const px = p => { const q = p.clone().project(cam); return [(q.x + 1) / 2 * W, (1 - q.y) / 2 * H]; };
    const head = px(this.headAt), rPx = H / (2 * Math.tan(FOV * Math.PI / 360) * (cam.position.z - this.headAt.z)) * U.uR.value;
    const tone = [o.tintR, o.tintG, o.tintB].map(x => Math.round(clamp(x, 0, 1) * 255)).join();
    U.uRim.value.setRGB(clamp(o.tintR, 0, 1) * 0.35, clamp(o.tintG, 0, 1) * 0.35, clamp(o.tintB, 0, 1) * 0.35);
    if (!plain) {
      this.mood.draw(STAGE.backdrop ? rig.emotion : 'none', rig.t, W, H, head[0], head[1]);
      if (wideOut > 0.02) {                            // she needs something to stand on once her feet are in the shot
        const g = this.mood.g, L_ = m.node('leftFoot').getWorldPosition(V()), R_ = m.node('rightFoot').getWorldPosition(V()), at = px(L_.clone().add(R_).multiplyScalar(0.5).setY(0)), rx = (Math.abs(px(L_)[0] - px(R_)[0]) + rPx * 1.1) / 2;
        g.fillStyle = `rgba(4,6,14,${0.42 * wideOut * Math.max(0.4, 1 - m.root.position.y * 3)})`;
        g.beginPath(); g.ellipse(at[0] / 2, at[1] / 2, rx, rx * 0.2, 0, 0, Math.PI * 2); g.fill();
      }
      const wash = oc.createLinearGradient(0, 0, W * 0.7, H);
      wash.addColorStop(0, `rgba(${tone},.14)`); wash.addColorStop(0.5, `rgba(${tone},0)`); wash.addColorStop(1, 'rgba(0,0,10,.18)');
      oc.fillStyle = wash; oc.fillRect(0, 0, W, H);
    }
    const facing = V(0, 0, 1).applyQuaternion(this.Rh).z;
    drawMarks(oc, o, rig.t, { head, eyes: m.eyes.map(e => px(this.headAt.clone().add(e.clone().applyQuaternion(this.Rh)))), r: rPx, side: Math.sign(V(0, 0, 1).applyQuaternion(this.Rh).x) || 1, facing });
    drawFx(oc, rig, head[0], head[1] + rPx * 0.2, rPx * 2.6, '#ffe9a8');
  }
}

// The body as something solid: for each torso and thigh bone, oval slices up its length, measured from the vertices that bone carries
// (a coat's tails included). Bones that move (arms, head and hair) are left out. Limbs are kept outside it, so a hand rests on a hip instead of sinking in.
const BODY = ['hips', 'spine', 'chest', 'upperChest', 'leftUpperLeg', 'rightUpperLeg'];
const HUMAN = [...BODY, 'neck', 'head', 'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand',
  'leftLowerLeg', 'rightLowerLeg', 'leftFoot', 'rightFoot', 'leftToes', 'rightToes', 'leftEye', 'rightEye', 'jaw'];
function measureBody(hum, meshes, node, a) {
  const named = new Map();
  for (const n of HUMAN) { const raw = hum.getRawBoneNode(n); if (raw) named.set(raw, n); }
  const partOf = new Map(), owner = b => {       // the nearest named bone above: a coat's own bones belong to the hips
    if (partOf.has(b)) return partOf.get(b);
    let x = b; while (x && !named.has(x)) x = x.parent;
    const p = x ? named.get(x) : null; partOf.set(b, p); return p;
  };
  const pts = Object.fromEntries(BODY.map(n => [n, []])), tmp = V();
  for (const mesh of meshes) {
    if (!mesh.isSkinnedMesh) continue;
    const g = mesh.geometry, P = g.attributes.position, I = g.attributes.skinIndex, Wt = g.attributes.skinWeight;
    for (let v = 0; v < P.count; v += 2) {
      let best = 0, w = 0;
      for (let k = 0; k < 4; k++) { const x = Wt.getComponent(v, k); if (x > w) { w = x; best = I.getComponent(v, k); } }
      const part = owner(mesh.skeleton.bones[best]);
      if (part in pts) { tmp.fromBufferAttribute(P, v).applyMatrix4(mesh.matrixWorld); pts[part].push(tmp.x, tmp.y, tmp.z); }
    }
  }
  const h = a * 0.18, q97 = arr => { arr.sort((x, y) => x - y); return arr[Math.min(arr.length - 1, Math.floor(arr.length * 0.97))] ?? 0; };
  const out = [];
  for (const name of BODY) {
    const P = pts[name], b = node(name);
    if (!b || P.length < 60) continue;
    let y0 = Infinity, y1 = -Infinity;
    for (let i = 1; i < P.length; i += 3) { y0 = Math.min(y0, P[i]); y1 = Math.max(y1, P[i]); }
    const bins = Array.from({ length: Math.max(1, Math.ceil((y1 - y0) / h)) }, () => ({ x: [], z: [] }));
    for (let i = 0; i < P.length; i += 3) { const s = bins[Math.min(bins.length - 1, Math.floor((P[i + 1] - y0) / h))]; s.x.push(P[i]); s.z.push(P[i + 2]); }
    // Each side measured on its own: a coat tail hanging behind a thigh mustn't make the front of the thigh stick out too.
    const raw = bins.map(({ x, z }) => {
      if (x.length < 6) return null;
      const mid = arr => { const c = [...arr].sort((p, q) => p - q), n = c.length - 1; return (c[Math.round(n * 0.03)] + c[Math.round(n * 0.97)]) / 2; }, cx = mid(x), cz = mid(z);   // halfway across, so two coat tails share one centre
      const side = (arr, c, sign) => q97(arr.map(v => (v - c) * sign).filter(v => v > 0));
      return { cx, cz, xp: side(x, cx, 1), xn: side(x, cx, -1), zp: side(z, cz, 1), zn: side(z, cz, -1) };
    });
    // Each slice is as wide as its neighbours too, so there is no gap for a fingertip between two slices.
    const slices = raw.map((s, i) => {
      if (!s) return null;
      const near = [raw[i - 1], s, raw[i + 1]].filter(n => n && Math.abs(n.cx - s.cx) + Math.abs(n.cz - s.cz) < a * 0.3);
      const widest = k => Math.max(...near.map(n => n[k]));
      return { cx: s.cx, cz: s.cz, xp: widest('xp'), xn: widest('xn'), zp: widest('zp'), zn: widest('zn') };
    });
    out.push({ name, y0, h, slices, pos0: b.getWorldPosition(V()), q0: b.getWorldQuaternion(new THREE.Quaternion()) });
  }
  const toe = node('leftToes'), foot = node('leftFoot');   // which way she faces, so a hand level with a flat coat tail goes in front of it
  out.front = toe && foot ? Math.sign(toe.getWorldPosition(V()).z - foot.getWorldPosition(V()).z) || 1 : 1;
  return out;
}

function readMeta(meta) {
  if (!meta) return { title: 'plain glTF', author: '', licence: 'not stated in the file' };
  if (meta.metaVersion === '0') return { title: meta.title ?? '', author: meta.author ?? '', licence: meta.licenseName === 'Other' ? (meta.otherLicenseUrl ?? 'Other') : (meta.licenseName ?? '') };
  return { title: meta.name ?? '', author: (meta.authors ?? []).join(', '), licence: meta.licenseUrl ?? '' };
}
