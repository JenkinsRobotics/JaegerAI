// Truth's body: the standard humanoid (humanoid.js) posed by keyframes and settled by springs, drawn by render-truth.js.
// The kneel follows the reference sculpt: the right knee up with the right forearm lying across it and the hand
// hanging, the left leg folded under, the left hand flat on the floor. Stand and sit are visits; Truth always
// settles back to the kneel. Metres, floor at y 0, Truth faces +z, its left is +x (screen right).
import { HUMANOID, PALMS, REST, HumanoidBody, tools, env } from './humanoid.js';
export const JOINTS = [...HUMANOID, ...PALMS, 'cam', 'turn'];   // cam: camera offset; turn: head roll, pitch (down), yaw
const { add, set, at, shiftUpper } = tools(JOINTS);

const TORSO = (z = 0) => ({
  hips: [0, .13, -.02 + z], spine: [0, .25, -.03 + z], chest: [0, .45, z], neck: [0, .61, .04 + z], head: [0, .69, .06 + z],
  leftUpperArm: [.18, .61, .03 + z], rightUpperArm: [-.18, .61, .03 + z], leftUpperLeg: [.09, .11, 0], rightUpperLeg: [-.09, .11, 0],
});
const KNEEL = {
  ...TORSO(),
  rightLowerLeg: [-.15, .46, .24], rightFoot: [-.17, .08, .38], rightToes: [-.18, .015, .52],                // the raised knee
  leftLowerLeg: [.42, .07, .2], leftFoot: [.04, .06, .36], leftToes: [-.08, .03, .43],                        // folded under
  rightLowerArm: [-.12, .5, .3], rightHand: [.1, .48, .38], rightHandTip: [.12, .3, .4], rightPalm: [0, 0, -1],   // across the knee, hand hanging
  leftLowerArm: [.3, .35, 0], leftHand: [.4, .11, .04], leftHandTip: [.55, .02, .12], leftPalm: [0, -1, 0],      // propped, hand flat on the floor
  cam: [0, 0, 0], turn: [.03, .15, 0],
};
const SIT = {
  ...TORSO(-.03),
  ...Object.fromEntries([1, -1].flatMap(s => { const side = s > 0 ? 'left' : 'right'; return [
    [side + 'LowerLeg', [s * .12, .47, .24]], [side + 'Foot', [s * .12, .07, .4]], [side + 'Toes', [s * .12, .015, .54]],       // both knees up
    [side + 'LowerArm', [s * .25, .44, .17]], [side + 'Hand', [s * .13, .5, .33]], [side + 'HandTip', [s * .12, .42, .48]],   // hands on the knees
    [side + 'Palm', [0, -1, 0]]]; })),
  cam: [0, 0, 0], turn: [0, .2, 0],
};
const STAND = { ...REST, cam: [0, .58, 1.5], turn: [0, .03, 0] };
export const BASES = { kneel: KNEEL, sit: SIT, stand: STAND };

// Moves on top of the base pose: fn(pose, u 0..1, t seconds since start).
export const MOVES = {
  clap: { label: 'Clap', icon: '✦', dur: 3.2, fn(p, u, t) {
    const e = env(u, .12, .18), c = at(p, 'chest'), open = .5 + .5 * Math.cos(t * Math.PI * 2 * 2.4);
    for (const s of [1, -1]) {
      const side = s > 0 ? 'left' : 'right', x = c[0] + s * (.012 + .07 * open);
      set(p, side + 'LowerArm', [c[0] + s * .24, c[1] - .1, c[2] + .14], e);
      set(p, side + 'Hand', [x, c[1] - .02, c[2] + .3], e); set(p, side + 'HandTip', [x, c[1] + .15, c[2] + .36], e);
      set(p, side + 'Palm', [-s, 0, 0], e);                                                 // palms face each other
    }
    add(p, 'turn', [0, -.07 * Math.sin(t * 15) * e, 0]);
  } },
  lean: { label: 'Lean back', icon: '↶', dur: 4, fn(p, u) {
    const e = env(u, .25, .3);
    shiftUpper(p, [0, -.02 * e, -.08 * e]);
    set(p, 'leftLowerArm', [.27, .32, -.1], e); set(p, 'leftHand', [.33, .12, -.18], e); set(p, 'leftHandTip', [.37, .06, -.35], e);   // the floor hand props behind
    add(p, 'turn', [0, -.3 * e, 0]);
  } },
  sway: { label: 'Sway', icon: '↔', dur: 4.4, fn(p, u, t) {
    const e = env(u, .15, .2), s = Math.sin(t * Math.PI) * e;
    shiftUpper(p, [.035 * s, -.004 * Math.abs(s), 0]); add(p, 'rightHand', [.015 * s, 0, 0]); add(p, 'rightHandTip', [.015 * s, 0, 0]);
    add(p, 'turn', [-.18 * s, 0, .08 * s]);
  } },
  stand: { label: 'Stand', icon: '↑', dur: 8, base: 'stand' },
  sit: { label: 'Sit', icon: '↓', dur: 8, base: 'sit' },
  kneel: { label: 'Kneel', icon: '◟', dur: .1, base: 'kneel' },
};

export class TruthBody extends HumanoidBody {
  constructor() { super(JOINTS, BASES, MOVES, 'kneel'); }
  // The rig's continuous channels: breath, roll, lean, crouch; the hanging hand lifts as Truth talks; a wave.
  channels(p, o, t) {
    shiftUpper(p, [(o.roll || 0) * .03 + Math.sin(t * .37) * .004, Math.sin(t * 1.4) * .003 + (o.lift || 0) * .01 - (o.crouch || 0) * .012, (o.lean || 0) * .02], .5);
    if (this.base === 'kneel') { const h = o.hand || 0; add(p, 'rightHand', [0, h * .012, h * .01]); add(p, 'rightHandTip', [.007 * h, h * .034, h * .024]); }
    if (o.wave > .01) {
      const e = Math.min(1, o.wave), sh = at(p, 'leftUpperArm'), x = sh[0] + .1 + .03 * Math.sin(t * 10);
      set(p, 'leftLowerArm', [sh[0] + .08, sh[1] + .03, sh[2] + .02], e); set(p, 'leftHand', [x, sh[1] + .26, sh[2] + .04], e);
      set(p, 'leftHandTip', [x + .005, sh[1] + .44, sh[2] + .04], e); set(p, 'leftPalm', [0, 0, 1], e);
    }
  }
}
