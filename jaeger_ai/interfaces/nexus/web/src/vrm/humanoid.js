// The standard humanoid a 3D body starts from: VRM humanoid bone names, adult proportions (about 7.5 heads),
// in metres, facing +z with its left at +x and the floor at y 0. A body poses it by joint positions (keyframes
// settled by springs) and the bones always keep their rest length. humanoidGLSL() draws it, unclothed and blank:
// pelvis, waist, ribcage, neck, shoulders, arms, hands with four fingers and a thumb, legs and feet. The head is
// left to the body, so each character brings its own face.
// ponytail: HandTip (the middle fingertip) and the palm directions are not VRM bones; they orient the hand.
const SIDES = ['left', 'right'];
const LIMB = ['UpperArm', 'LowerArm', 'Hand', 'HandTip', 'UpperLeg', 'LowerLeg', 'Foot', 'Toes'];
export const HUMANOID = ['hips', 'spine', 'chest', 'neck', 'head', ...SIDES.flatMap(s => LIMB.map(b => s + b))];
export const PALMS = ['leftPalm', 'rightPalm'];   // the way each palm faces, a direction, not a position
export const HEAD_HEIGHT = 0.235;                  // chin to crown

const LEFT = {   // standing, arms relaxed at the sides; the right side mirrors it
  UpperArm: [.185, 1.435, -.01], LowerArm: [.215, 1.145, -.03], Hand: [.235, .875, 0], HandTip: [.245, .69, .02],
  UpperLeg: [.09, .92, 0], LowerLeg: [.1, .5, .01], Foot: [.1, .08, -.02], Toes: [.105, .015, .12],
};
export const REST = {
  hips: [0, .95, 0], spine: [0, 1.07, 0], chest: [0, 1.28, 0], neck: [0, 1.45, -.01], head: [0, 1.54, 0],
  ...Object.fromEntries(SIDES.flatMap(s => LIMB.map(b => [s + b, [s === 'left' ? LEFT[b][0] : -LEFT[b][0], LEFT[b][1], LEFT[b][2]]]))),
  leftPalm: [-1, 0, 0], rightPalm: [1, 0, 0],   // palms face the thighs
};

// Bones, parent first, in the order lengths are restored: the spine, then each arm from the chest and each leg from the hips.
const BONES = [['hips', 'spine'], ['spine', 'chest'], ['chest', 'neck'], ['neck', 'head'],
  ...SIDES.flatMap(s => [['chest', s + 'UpperArm'], [s + 'UpperArm', s + 'LowerArm'], [s + 'LowerArm', s + 'Hand'], [s + 'Hand', s + 'HandTip'],
    ['hips', s + 'UpperLeg'], [s + 'UpperLeg', s + 'LowerLeg'], [s + 'LowerLeg', s + 'Foot'], [s + 'Foot', s + 'Toes']])];
export const chainsOf = joints => BONES.filter(([a, b]) => joints.includes(a) && joints.includes(b));
const restLength = (a, b) => Math.hypot(...REST[b].map((v, i) => v - REST[a][i]));
// How high each joint sits above the floor when that part rests on it: the ankle above the sole, the ball of the foot, a fingertip.
const FLOOR_CLEAR = { Foot: .072, Toes: .012, HandTip: .012, Hand: .025, LowerLeg: .05, LowerArm: .04 };

// Posing tools for a joint list: add or blend towards an offset, read a joint, move the whole upper body.
export function tools(joints) {
  const J = Object.fromEntries(joints.map((n, i) => [n, i]));
  const add = (p, j, v, w = 1) => { for (let k = 0; k < 3; k++) p[J[j] * 3 + k] += v[k] * w; };
  const set = (p, j, v, w = 1) => { for (let k = 0; k < 3; k++) p[J[j] * 3 + k] += (v[k] - p[J[j] * 3 + k]) * w; };
  const at = (p, j) => [p[J[j] * 3], p[J[j] * 3 + 1], p[J[j] * 3 + 2]];
  const shiftUpper = (p, d, arms = .6) => {
    for (const j of ['chest', 'neck', 'head', 'leftUpperArm', 'rightUpperArm']) add(p, j, d);
    for (const j of ['leftLowerArm', 'rightLowerArm']) add(p, j, d, arms);
  };
  return { J, add, set, at, shiftUpper };
}
export const env = (u, a = .15, b = .2) => Math.max(0, Math.min(1, u / a, (1 - u) / b));

// A posed humanoid. bases: whole poses by name (missing joints come from REST); moves: { dur, base? , fn(pose, u, t) }.
// home is where it settles; a move with a base is a visit that returns home after its duration.
export class HumanoidBody {
  constructor(joints, bases, moves, home) {
    Object.assign(this, { joints, bases, moves, home, base: home, until: 0, playing: [] });
    this.tools = tools(joints);
    this.chains = chainsOf(joints).map(([a, b]) => [this.tools.J[a] * 3, this.tools.J[b] * 3, restLength(a, b), FLOOR_CLEAR[b.replace(/^(left|right)/, '')] ?? .03]);
    this.cur = this.pose(home); this.vel = new Float32Array(this.cur.length);
  }
  pose(name) { const B = this.bases[name]; return Float32Array.from(this.joints.flatMap(j => B[j] ?? REST[j] ?? [0, 0, 0])); }
  get poses() { return Object.keys(this.moves); }
  play(name, t) {
    const m = this.moves[name]; if (!m) return;
    if (m.base) { this.base = m.base; this.until = m.base === this.home ? 0 : t + m.dur; }
    else this.playing = [...this.playing.filter(x => x.name !== name), { name, start: t }];
  }
  channels() {}   // a body adds the rig's continuous channels here: breath, lean, a talking hand, a wave
  target(o, t) {
    if (this.until && t > this.until) { this.base = this.home; this.until = 0; }
    const p = this.pose(this.base);
    this.channels(p, o, t);
    this.playing = this.playing.filter(m => t - m.start < this.moves[m.name].dur);
    for (const m of this.playing) this.moves[m.name].fn(p, (t - m.start) / this.moves[m.name].dur, t - m.start);
    return this.keepLengths(p);
  }
  // Each bone back to its rest length along its current direction. A joint that would end up under the floor
  // slides along it instead, keeping the length, so feet and hands rest on the floor instead of sinking into it.
  keepLengths(p) {
    for (const [i, k, len, low] of this.chains) {
      const d = [p[k] - p[i], p[k + 1] - p[i + 1], p[k + 2] - p[i + 2]], n = Math.hypot(...d) || 1;
      for (let c = 0; c < 3; c++) p[k + c] = p[i + c] + d[c] / n * len;
      const dy = low - p[i + 1];
      if (p[k + 1] < low && dy < len) {
        const flat = Math.hypot(d[0], d[2]) || 1, reach = Math.sqrt(len * len - dy * dy);
        p[k] = p[i] + d[0] / flat * reach; p[k + 1] = low; p[k + 2] = p[i + 2] + d[2] / flat * reach;
      }
    }
    return p;
  }
  // Springs carry each joint to its target, so a change of pose arrives with weight instead of snapping.
  step(o, t, dt) {
    const p = this.target(o, t), K = 60, C = 2 * .9 * Math.sqrt(K), h = Math.min(dt, 1 / 30);
    for (let i = 0; i < p.length; i++) { this.vel[i] += (K * (p[i] - this.cur[i]) - C * this.vel[i]) * h; this.cur[i] += this.vel[i] * h; }
    return this.keepLengths(this.cur);   // the springs blend positions; the bones stay their length
  }
}

// GLSL: names every joint (J_hips, J_leftHand...) from the uniform array U and defines humanoid(b), the blank body
// in body space b (metres, floor at 0). Needs PALMS in the joint list.
export const humanoidGLSL = (joints, U) => `uniform vec3 ${U}[${joints.length}];
${joints.map((j, i) => `#define J_${j} ${U}[${i}]`).join('\n')}
mat3 frame(vec3 up,vec3 side){ up=normalize(up); side=normalize(side-dot(side,up)*up); return mat3(side,up,cross(side,up)); }   // columns: side, up, forward
// A hand: palm, four fingers curling a little toward the palm, and a thumb. s: 1 left, -1 right (which side the thumb is on).
float hand(vec3 p,vec3 w,vec3 tip,vec3 palm,float s){
  vec3 x=normalize(tip-w),n=normalize(palm-dot(palm,x)*x),y=cross(n,x);
  vec3 q=p-w,l=vec3(dot(q,y),dot(q,x),dot(q,n));                                          // across, along, out of the palm
  float bound=length(l-vec3(0,.095,0))-.125; if(bound>.02) return bound;
  float d=box(l-vec3(0,.047,-.003),vec3(.037,.047,.013),.011);
  const vec4 LEN=vec4(.079,.087,.082,.065), OFF=vec4(.026,.009,-.009,-.025);
  for(int i=0;i<4;i++){
    vec3 k=vec3(s*OFF[i],.09,-.002),m=k+vec3(0,LEN[i]*.56,LEN[i]*.1),t=m+vec3(0,LEN[i]*.4,LEN[i]*.2);
    d=smin(d,min(cone(l,k,m,.0098,.0088),cone(l,m,t,.0088,.0075)),.006);
  }
  vec3 t0=vec3(s*.03,.016,.004),t1=t0+vec3(s*.024,.032,.014),t2=t1+vec3(s*.006,.03,.018);
  return smin(d,min(cone(l,t0,t1,.0135,.0105),cone(l,t1,t2,.0105,.0085)),.012);
}
// A foot from the ankle, pointing at the ball of the foot, with its top toward the knee.
float foot(vec3 p,vec3 an,vec3 ball,vec3 knee){
  float L=length(ball-an);
  vec3 fw=normalize(ball-an),up=normalize(knee-an); up=normalize(up-dot(up,fw)*fw);
  vec3 q=p-an,l=vec3(dot(q,cross(up,fw)),dot(q,up),dot(q,fw));                           // across, up, forward
  float d=box(l-vec3(0,-.048,L*.5),vec3(.036,.02,L*.5+.045),.018);                       // sole, heel to toes
  d=smin(d,ell(l-vec3(0,-.05,-.035),vec3(.032,.028,.042)),.02);                           // heel
  d=smin(d,ell(l-vec3(0,-.022,.035),vec3(.033,.04,.07)),.03);                             // instep
  return d;
}
float humanoid(vec3 b){
  mat3 Fp=frame(J_spine-J_hips,J_leftUpperLeg-J_rightUpperLeg),Fc=frame(J_neck-J_spine,J_leftUpperArm-J_rightUpperArm);
  mat3 Fw=frame(J_chest-J_hips,Fp[0]+Fc[0]);
  float d=ell((b-J_hips)*Fp-vec3(0,.0,-.005),vec3(.158,.105,.1));                         // pelvis
  for(int s=-1;s<=1;s+=2) d=smin(d,ell((b-J_hips)*Fp-vec3(float(s)*.068,-.045,-.045),vec3(.075,.08,.07)),.04);   // glutes
  d=smin(d,ell((b-J_spine)*Fw-vec3(0,.02,0),vec3(.122,.105,.088)),.09);                   // waist
  d=smin(d,ell((b-J_chest)*Fc-vec3(0,.02,.005),vec3(.148,.165,.103)),.08);                // ribcage
  d=smin(d,ell((b-J_chest)*Fc-vec3(0,.075,.06),vec3(.12,.07,.05)),.04);                   // chest
  d=smin(d,cap(b,J_leftUpperArm-Fc[1]*.035,J_rightUpperArm-Fc[1]*.035,.052),.05);        // shoulder girdle
  d=smin(d,cap(b,J_neck-Fc[1]*.03,J_head+(J_head-J_neck)*.2,.052),.03);                  // neck
  for(int s=-1;s<=1;s+=2){ vec3 sh=s>0?J_leftUpperArm:J_rightUpperArm;                    // trapezius: the slope from the neck to each shoulder
    d=smin(d,cone(b,J_neck+Fc[1]*.035-Fc[2]*.015,sh+Fc[1]*.025-Fc[0]*float(s)*.045,.045,.03),.04); }
  vec3 sh[2]=vec3[2](J_leftUpperArm,J_rightUpperArm),el[2]=vec3[2](J_leftLowerArm,J_rightLowerArm),wr[2]=vec3[2](J_leftHand,J_rightHand),
       tp[2]=vec3[2](J_leftHandTip,J_rightHandTip),pm[2]=vec3[2](J_leftPalm,J_rightPalm),
       hp[2]=vec3[2](J_leftUpperLeg,J_rightUpperLeg),kn[2]=vec3[2](J_leftLowerLeg,J_rightLowerLeg),an[2]=vec3[2](J_leftFoot,J_rightFoot),to[2]=vec3[2](J_leftToes,J_rightToes);
  for(int i=0;i<2;i++){
    float s=i==0?1.:-1.;
    float arm=ell(b-sh[i]-Fc[0]*s*.01+Fc[1]*.012,vec3(.05,.056,.05));                     // deltoid, capping the shoulder
    arm=smin(arm,cone(b,sh[i],el[i],.046,.036),.03);
    arm=smin(arm,cone(b,el[i],mix(el[i],wr[i],.35),.04,.037),.015);                       // forearm, fuller below the elbow
    arm=smin(arm,cone(b,mix(el[i],wr[i],.35),wr[i],.037,.026),.02);
    arm=smin(arm,hand(b,wr[i],tp[i],pm[i],s),.012);
    d=smin(d,arm,.035);
    float leg=cone(b,hp[i],kn[i],.086,.054);                                              // thigh
    leg=smin(leg,ell(b-kn[i],vec3(.05)),.02);                                             // knee
    leg=smin(leg,cone(b,kn[i],an[i],.05,.033),.015);                                      // shin
    leg=smin(leg,ell(b-mix(kn[i],an[i],.3)+Fp[2]*.018,vec3(.05,.07,.05)),.03);            // calf
    leg=smin(leg,foot(b,an[i],to[i],kn[i]),.02);
    d=smin(d,leg,.045);
  }
  return d;
}`;
