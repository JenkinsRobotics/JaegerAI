// Maps the rig onto any humanoid model. No GPU or three.js here, so `node test.mjs` can check it.
import { SNAP } from './rig.js';

const c01 = x => Math.max(0, Math.min(1, x));

// Abstract face shapes from the rig's channels. lidL is the viewer's left, which is the character's right eye.
export function faceShapes(o, onTwos) {
  let { jaw, wide, round } = o, teeth = o.teeth;
  if (onTwos) { jaw = SNAP(jaw, [0, 0.2, 0.42, 0.7]); round = SNAP(round, [0, 1]); wide = SNAP(wide, [0, 1]); teeth = SNAP(teeth, [0, 1]); }
  const j = c01(jaw / 0.7), smile = c01(o.smile), frown = c01(-o.smile), brow = (o.browL + o.browR) / 2;
  const eyeJoy = c01(o.arc + o.low * 0.5 + o.squeeze);
  const kin=o.kinMouth?Object.fromEntries(['aa','ee','ih','oh','ou'].map(k=>[k,c01(o['lip'+k.toUpperCase()])])):null;
  if(kin)kin.ih=Math.max(kin.ih,teeth*.6);
  return {
    aa: j * (1 - round) * (1 - wide) * (1 - smile * 0.6), oh: j * round, ou: (1 - j) * round, ee: j * wide * (1 - round),
    ih: Math.max((1 - j) * wide, teeth * 0.6) * (1 - round),
    ...(kin||{}),
    smile: smile * (1 - j), smileOpen: smile * j * (1 - round),
    frown: frown * c01(0.5 + o.tilt), snarl: frown * c01(0.5 - o.tilt),
    blinkR: c01(1 - o.lidL) * (1 - eyeJoy), blinkL: c01(1 - o.lidR) * (1 - eyeJoy),
    eyeJoy, eyeWide: c01(((o.lidL + o.lidR) / 2 - 1) / 0.35),
    eyeAngry: c01(-o.tilt) * 0.8, eyeSad: c01(o.tilt) * 0.7,
    browUp: c01(brow), browAngry: c01(c01(-o.tilt) + c01(-brow) * 0.5), browSad: c01(o.tilt),
    blush: c01(o.blush),
  };
}

// Morph target names by shape: VRoid (Fcl_*), Seed-san style, VRChat visemes, ARKit, MMD.
export const MORPHS = {
  aa: /Fcl_MTH_A$|v_aa$|lip_a$|^aa$|^あ$|jawOpen$/i, ih: /Fcl_MTH_I$|v_ih$|lip_i$|^ih$|^い$/i, ou: /Fcl_MTH_U$|v_ou$|lip_u$|^ou$|^う$|mouthPucker$/i,
  ee: /Fcl_MTH_E$|v_ee?$|lip_e$|^ee$|^え$/i, oh: /Fcl_MTH_O$|v_oh$|lip_o$|^oh$|^お$|mouthFunnel$/i,
  smile: /Fcl_MTH_Fun$|mouthSmile(Left|Right)$|lip_up$|^にやり$/i, smileOpen: /Fcl_MTH_Joy$/i,
  frown: /Fcl_MTH_Sorrow$|mouthFrown(Left|Right)$|lip_down$/i, snarl: /Fcl_MTH_Angry$/i,
  blinkL: /Fcl_EYE_Close_L$|blink_?l(eft)?$|^ウィンク$/i, blinkR: /Fcl_EYE_Close_R$|blink_?r(ight)?$|^ウィンク右$/i,
  eyeJoy: /Fcl_EYE_Joy$|eye_smile$|^笑い$/i, eyeWide: /Fcl_EYE_Surprised$|eye_open$|eyeWide(Left|Right)$|^びっくり$/i,
  eyeAngry: /Fcl_EYE_Angry$|eye_angry$|eyeSquint(Left|Right)$/i, eyeSad: /Fcl_EYE_Sorrow$/i,
  browUp: /Fcl_BRW_Surprised$|eye_brow_up$|browOuterUp(Left|Right)$|^上$/i, browAngry: /Fcl_BRW_Angry$|eye_brow_down$|browDown(Left|Right)$|^怒り$/i, browSad: /Fcl_BRW_Sorrow$|browInnerUp$|^困る$/i,
  blush: /cheek$|^照れ$/i,
};
// When a VRM's morphs have other names, its standard expressions stand in.
export const EXPRESSIONS = { aa: 'aa', ih: 'ih', ou: 'ou', ee: 'ee', oh: 'oh', blinkL: 'blinkLeft', blinkR: 'blinkRight', smile: 'happy', browAngry: 'angry', frown: 'sad', eyeWide: 'surprised' };

// VRM humanoid bone name for a plain glTF node, from the common rigs: VRoid (J_Bip_*), Mixamo, Blender.
const BONES = [
  [/hips?$|pelvis$/i, 'hips', 0], [/upperchest$|spine2$/i, 'upperChest', 0], [/chest$|spine1$/i, 'chest', 0], [/spine$/i, 'spine', 0], [/neck$/i, 'neck', 0], [/head$/i, 'head', 0],
  [/faceeye$|eye$/i, 'Eye', 1], [/shoulder$|clavicle$/i, 'Shoulder', 1],
  [/thumb_?0?1$/i, 'ThumbMetacarpal', 1], [/thumb_?0?2$/i, 'ThumbProximal', 1], [/thumb_?0?3$/i, 'ThumbDistal', 1],
  ...['Index', 'Middle', 'Ring', 'Little'].flatMap(f => { const re = f === 'Little' ? 'pinky|little' : f; return [[new RegExp(`(${re})_?0?1$`, 'i'), f + 'Proximal', 1], [new RegExp(`(${re})_?0?2$`, 'i'), f + 'Intermediate', 1], [new RegExp(`(${re})_?0?3$`, 'i'), f + 'Distal', 1]]; }),
  [/upperarm$|upper_arm$|arm$(?<!forearm|lowerarm|lower_arm)/i, 'UpperArm', 1], [/lowerarm$|lower_arm$|forearm$/i, 'LowerArm', 1], [/hand$/i, 'Hand', 1],
  [/upperleg$|upper_leg$|upleg$|thigh$/i, 'UpperLeg', 1], [/lowerleg$|lower_leg$|leg$|shin$|calf$/i, 'LowerLeg', 1], [/foot$/i, 'Foot', 1], [/toes?$|toebase$/i, 'Toes', 1],
];
export function humanBone(name) {
  if (/J_Sec|J_Opt|J_Adj(?!.*FaceEye)/i.test(name)) return null;
  const n = name.replace(/\.(l|r)$/i, '').replace(/_(l|r)$/i, '');   // Blender's upper_arm.L
  const side = /left|(^|[^a-z])l([^a-z]|$)/i.test(name) ? 'left' : /right|(^|[^a-z])r([^a-z]|$)/i.test(name) ? 'right' : '';
  const hit = BONES.find(([re]) => re.test(n));
  if (!hit) return null;
  if (!hit[2]) return hit[1];
  return side ? side + hit[1] : null;
}

// Acting: where the hands go for each feeling, so a whole body plays the emotion. `a` is the arm on the viewer's right, `b` the other.
// at: face (units of head radius), chest, hip or shoulder (units of arm/2.25). p: wrist offset, +x is away from the body's midline on that arm's side.
// f: the way the fingers point, same convention. pole: where the elbow goes, if not down and back.
const onHip = { at: 'hip', p: [0.95, 0.3, 0.02], f: [-0.75, -0.35, 0.55], open: 0.75, pole: [0.95, -0.1, -0.3], fist: false };
const heart = { at: 'chest', p: [0.28, 0.02, 0.68], f: [-0.95, 0.2, 0.2], open: 0.75 };
export const ACTING = {
  thinking: { a: { at: 'face', p: [0.5, -1.95, 0.95], f: [-0.45, 0.85, 0.2], open: 0.2 }, b: { at: 'chest', p: [0.4, -0.72, 0.68], f: [-0.95, 0.25, 0.15], open: 0.25 } },
  confused: { a: { at: 'face', p: [0.95, -1.05, 0.9], f: [-0.35, 0.92, 0.1], open: 0.35 }, b: { at: 'shoulder', p: [0.55, -0.9, 0.6], f: [0.65, 0.55, 0.3], open: 1 } },
  shy: { a: { at: 'chest', p: [0.1, -0.12, 0.72], f: [-0.5, 0.82, 0.2], open: 0.3 }, b: { at: 'chest', p: [0.1, -0.12, 0.72], f: [-0.5, 0.82, 0.2], open: 0.3 } },
  love: { a: heart, b: { ...heart, p: [0.34, -0.2, 0.62] } },
  surprised: { a: { at: 'shoulder', p: [0.5, -0.55, 0.8], f: [0.3, 0.92, 0.2], open: 1 }, b: { at: 'shoulder', p: [0.5, -0.55, 0.8], f: [0.3, 0.92, 0.2], open: 1 } },
  scared: { a: { at: 'face', p: [0.55, -1.8, 1.05], f: [-0.35, 0.9, 0.25], open: 0.12 }, b: { at: 'face', p: [0.55, -1.8, 1.05], f: [-0.35, 0.9, 0.25], open: 0.12 } },
  angry: { a: onHip, b: onHip },
  smug: { a: onHip, b: { at: 'face', p: [0.62, -2.0, 0.9], f: [-0.3, 0.9, 0.2], open: 0.2 } },
  excited: { a: { at: 'shoulder', p: [0.42, -0.75, 0.85], f: [-0.2, 0.95, 0.2], open: 0, fist: true }, b: { at: 'shoulder', p: [0.42, -0.75, 0.85], f: [-0.2, 0.95, 0.2], open: 0, fist: true } },
  joy: { a: { at: 'chest', p: [0.12, -0.72, 0.68], f: [-0.9, 0.3, 0.3], open: 0.4 }, b: { at: 'chest', p: [0.12, -0.72, 0.68], f: [-0.9, 0.3, 0.3], open: 0.4 } },
  sad: { a: { at: 'hip', p: [0.16, 0.38, 0.66], f: [-0.9, -0.3, 0.2], open: 0.3 }, b: { at: 'hip', p: [0.16, 0.38, 0.66], f: [-0.9, -0.3, 0.2], open: 0.3 } },
  laughing: { a: { at: 'face', p: [0.75, -1.45, 1.1], f: [-0.85, 0.5, 0.1], open: 0.6 }, b: { at: 'chest', p: [0.14, -0.95, 0.66], f: [-0.95, 0.1, 0.2], open: 0.5 } },
  singing: { a: heart, b: { at: 'shoulder', p: [1.15, -0.2, 1.05], f: [0.6, 0.45, 0.6], open: 1 } },
  sleepy: { a: { at: 'face', p: [0.4, -1.5, 1.15], f: [-0.8, 0.55, 0.1], open: 0.4 } },
};

// Camera: [zoom, stiffness]. A shock is a smash zoom, sadness drifts out, so the shot acts along with the face.
export const CAMERA = { surprised: [1.34, 280], scared: [1.2, 160], angry: [1.2, 110], love: [1.16, 30], shy: [1.18, 30], laughing: [1.1, 70], excited: [1.06, 110], thinking: [1.1, 25], sad: [1.08, 12], singing: [1.04, 15], sleepy: [1.06, 10] };
