// Tier 2. One true 3D character per anime face, drawn to look 2D. Nothing is layered, so turning the head can't break proportions:
//   - a single raymarched body and a real skeleton (chest -> neck -> head -> jaw, shoulders -> two-bone IK arms -> jointed hands)
//   - view flattening: the head is compressed along the camera axis, the trick behind Guilty Gear Xrd and Genshin. It keeps the
//     big-eyed, flat-nosed anime read at every angle while the silhouette stays consistent in 3D
//   - face normals replaced by a sphere's, so cel shadows stay clean instead of following the nose
//   - two passes: cel shading into a G-buffer, then ink lines found from depth, normal and part-id edges
// ponytail: raymarching needs a real GPU. For robot hardware, bake the same shapes to a mesh, keep the bones and the flatten.
import { drawFx, SNAP } from './rig.js';
import { NAMES, PRELUDE, VS } from './render-3d.js';

const lerp = (a, b, u) => a + (b - a) * u;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const v3 = a => `vec3(${a.map(n => n.toFixed(3)).join(',')})`;

// A lock is root, bend, tip and radius in head space, plus `sw`, how far its tip lags. Roots tuck into the cap so their ends never show.
const growLocks = guides => guides.map(([a, b, c, r, sw]) => [a.map((n, j) => n * (j === 1 ? 0.92 : 0.8)), b, c, r, sw]);
const lockGLSL = guides => {
  const L = growLocks(guides), n = L.length, list = (t, f) => `const ${t} ${f[0]}[NL]=${t}[NL](${L.map(f[1]).join(',')});`;
  const centre = l => [0, 1, 2].map(j => (l[0][j] + l[1][j] + l[2][j]) / 3);
  const reach = l => { const o = centre(l); return Math.max(...[l[0], l[1], l[2]].map(p => Math.hypot(p[0] - o[0], p[1] - o[1], p[2] - o[2]))) + l[3] + 0.12; };
  return `#define NL ${n}
${list('vec3', ['LA', l => v3(l[0])])}
${list('vec3', ['LB', l => v3(l[1])])}
${list('vec3', ['LC', l => v3(l[2])])}
${list('vec3', ['LO', l => v3(centre(l))])}
${list('float', ['LR', l => l[3].toFixed(3)])}
${list('float', ['LS', l => l[4].toFixed(3)])}
${list('float', ['LQ', l => reach(l).toFixed(3)])}`;
};

const mirror = l => [l, [[-l[0][0], l[0][1], l[0][2]], [-l[1][0], l[1][1], l[1][2]], [-l[2][0], l[2][1], l[2][2]], l[3], l[4]]];

const CHARS = {
  ace: {
    flat: 0.6, gear: 'headset', shades: true, shift: 0, chestYaw: 0.14, chestRoll: -0.03, headYaw: 0.08, headRoll: 0.05, headPitch: 0.02, smirk: 0.42, smirkX: 0.5,
    eye: [0.19, 0.115], eyeX: 0.35, slant: 0.2, iris: ['vec3(.16,.09,.05)', 'vec3(.42,.28,.16)'],
    grade: 'vec3(1.)', skin: ['vec3(1.,.86,.72)', 'vec3(.82,.56,.48)'], hair: ['vec3(.17,.185,.22)', 'vec3(.05,.055,.075)'], ring: 'vec3(.55,.78,.9)', brow: 'vec3(.06,.06,.08)', lash: 'vec3(.07,.05,.07)',
    cloth: 'vec3(.2,.21,.25)', clothSh: 'vec3(.07,.075,.1)', rim: 'vec3(.4,.82,1.)', wash: '120,200,255',
    capCut: 'ell(h-vec3(0,-.34,.62),vec3(.74,.78,.72))', capBack: 'ell(h-vec3(0,-.1,-.36),vec3(.9,.72,.56))', hairAt: 0.02,
    locks: [
      [[-0.2, 0.7, -0.6], [-0.3, 1.1, -0.75], [0.05, 1.42, -0.8], 0.3, 1.4], [[0.35, 0.7, -0.55], [0.55, 1.05, -0.7], [0.95, 1.2, -0.75], 0.28, 1.3],
      [[-0.8, 0.3, 0.1], [-1.02, 0.72, 0.0], [-0.84, 1.2, -0.1], 0.22, 1], [[-0.5, 0.72, 0.2], [-0.62, 1.15, 0.15], [-0.25, 1.58, 0.05], 0.27, 1.4], [[-0.08, 0.84, 0.3], [0.05, 1.24, 0.28], [0.5, 1.6, 0.12], 0.28, 1.6],
      [[0.36, 0.76, 0.25], [0.66, 1.1, 0.2], [1.16, 1.32, 0.05], 0.26, 1.5], [[0.72, 0.4, 0.15], [1.04, 0.68, 0.08], [1.44, 0.72, -0.05], 0.2, 1.2],
      [[-0.6, 0.62, 0.6], [-0.62, 0.3, 0.8], [-0.42, 0.06, 0.84], 0.17, 0.5], [[-0.24, 0.76, 0.66], [-0.2, 0.42, 0.86], [-0.02, 0.1, 0.94], 0.19, 0.6], [[0.12, 0.76, 0.68], [0.24, 0.44, 0.84], [0.42, 0.12, 0.88], 0.18, 0.6], [[0.48, 0.64, 0.56], [0.66, 0.36, 0.68], [0.76, 0.1, 0.66], 0.15, 0.5],
      ...mirror([[0.86, 0.1, 0.25], [0.9, -0.1, 0.32], [0.82, -0.32, 0.34], 0.08, 0.3]).flat(0),
    ],
  },
  sol: {
    flat: 0.62, gear: 'headset', shift: 0.72, chestYaw: -0.5, chestRoll: 0.03, headYaw: -0.52, headRoll: -0.06, headPitch: -0.06, smirk: 0.2, smirkX: 0,
    eye: [0.2, 0.15], eyeX: 0.35, slant: 0.2, iris: ['vec3(.2,.25,.42)', 'vec3(.56,.66,.86)'],
    grade: 'vec3(.97,.92,.98)', skin: ['vec3(1.,.86,.79)', 'vec3(.78,.54,.6)'], hair: ['vec3(.9,.89,.92)', 'vec3(.56,.53,.66)'], ring: 'vec3(1.)', brow: 'vec3(.45,.41,.48)', lash: 'vec3(.18,.13,.2)',
    cloth: 'vec3(.96,.75,.32)', clothSh: 'vec3(.74,.46,.2)', rim: 'vec3(.82,.45,1.)', wash: '220,130,255',
    capCut: 'ell(h-vec3(0,-.34,.62),vec3(.74,.8,.72))', capBack: 'ell(h-vec3(0,-.16,-.38),vec3(.9,.78,.56))', hairAt: 0.24,
    locks: [
      [[-0.5, 0.5, -0.6], [-0.75, 0.3, -0.85], [-0.75, -0.2, -0.85], 0.28, 1.2], [[0.5, 0.5, -0.6], [0.75, 0.3, -0.85], [0.75, -0.2, -0.85], 0.28, 1.2], [[0, 0.3, -0.8], [0, 0, -1.05], [0, -0.42, -0.95], 0.3, 1.2],
      [[-0.84, 0.4, 0.05], [-1.12, 0.52, 0.02], [-1.36, 0.42, -0.05], 0.13, 1], [[0.84, 0.4, 0.05], [1.12, 0.52, 0.02], [1.36, 0.42, -0.05], 0.13, 1],
      
      [[-0.5, 0.78, 0.2], [-0.66, 1.05, 0.15], [-0.98, 1.2, 0.05], 0.15, 1.5], [[-0.26, 0.9, 0.2], [-0.34, 1.16, 0.18], [-0.56, 1.42, 0.1], 0.15, 1.6], [[0.0, 0.94, 0.2], [0.0, 1.2, 0.2], [0.12, 1.5, 0.1], 0.16, 1.7], [[0.26, 0.9, 0.2], [0.42, 1.14, 0.18], [0.66, 1.36, 0.1], 0.15, 1.6], [[0.52, 0.76, 0.2], [0.72, 1.0, 0.15], [1.02, 1.1, 0.05], 0.14, 1.5],
      [[-0.68, 0.56, 0.5], [-0.76, 0.2, 0.6], [-0.74, -0.2, 0.56], 0.17, 0.7], [[-0.4, 0.74, 0.62], [-0.42, 0.34, 0.82], [-0.36, -0.02, 0.88], 0.19, 0.8], [[-0.1, 0.8, 0.68], [-0.06, 0.4, 0.88], [0, 0.04, 0.96], 0.2, 0.9], [[0.2, 0.78, 0.66], [0.3, 0.4, 0.84], [0.36, -0.04, 0.9], 0.2, 0.9], [[0.5, 0.64, 0.52], [0.66, 0.26, 0.64], [0.72, -0.18, 0.6], 0.17, 0.7],
      [[-0.05, 0.92, 0.1], [-0.12, 1.26, 0.1], [-0.3, 1.5, 0.05], 0.03, 2.2], [[0.1, 0.92, 0.1], [0.16, 1.28, 0.1], [0.34, 1.54, 0.05], 0.025, 2.4],
    ],
  },
  nori: {
    flat: 0.58, gear: 'ears', shift: 0, chestYaw: -0.06, chestRoll: 0.02, headYaw: 0.04, headRoll: -0.06, headPitch: 0.03, smirk: 0.14, smirkX: 0, tintIris: true, wing: true,
    eye: [0.24, 0.25], eyeX: 0.39, slant: 0.06, iris: null,
    grade: 'vec3(1.)', skin: ['vec3(1.,.91,.85)', 'vec3(.92,.66,.68)'], hair: ['vec3(.27,.46,.82)', 'vec3(.12,.2,.48)'], hairTip: 'vec3(.5,.92,.94)', ring: 'vec3(.82,.93,1.)', brow: 'vec3(.16,.22,.46)', lash: 'vec3(.1,.08,.2)',
    cloth: 'vec3(.97,.97,1.)', clothSh: 'vec3(.68,.70,.86)', rim: 'vec3(.55,.8,1.)', wash: '255,200,230',
    capCut: 'ell(h-vec3(0,-.34,.62),vec3(.76,.84,.72))', capBack: 'ell(h-vec3(0,-.25,-.42),vec3(.92,.9,.6))', hairAt: 0.08,
    locks: [
      ...mirror([[0.8, 0.3, -0.3], [1.02, -0.5, -0.45], [1.0, -1.55, -0.5], 0.3, 2]).flat(0), ...mirror([[0.4, 0.2, -0.75], [0.56, -0.8, -0.9], [0.5, -1.75, -0.8], 0.34, 2.2]).flat(0), [[0, 0.2, -0.85], [0, -0.8, -1.0], [0, -1.85, -0.85], 0.36, 2.2],
      ...mirror([[0.84, 0.2, 0.3], [0.94, -0.45, 0.32], [0.88, -1.3, 0.3], 0.14, 1.6]).flat(0),
      ...mirror([[0.66, 0.6, 0.45], [0.74, 0.2, 0.6], [0.72, -0.14, 0.58], 0.16, 0.6]).flat(0), ...mirror([[0.38, 0.74, 0.6], [0.42, 0.36, 0.8], [0.4, 0.03, 0.86], 0.18, 0.7]).flat(0), [[-0.06, 0.82, 0.68], [-0.08, 0.42, 0.88], [-0.02, 0.05, 0.96], 0.2, 0.8],
      [[-0.02, 0.92, 0.1], [0.12, 1.32, 0.1], [0.02, 1.6, 0.1], 0.07, 2.5],
    ],
  },
};

function fragment(who, K) {
  const headset = K.gear === 'headset';
  return PRELUDE.replace('out vec4 frag;', 'layout(location=0) out vec4 frag;') + `
layout(location=1) out vec4 gbuf;
uniform mat3 Rh,Rc; uniform vec3 H,C,NB,NT,sw1,sw2; uniform mat3 hf[2]; uniform float curl[2],spread[2]; uniform vec2 view;
#define FLAT ${K.flat.toFixed(2)}
${lockGLSL(K.locks)}
const vec3 LIGHT=normalize(vec3(-.5,.72,.55));
bool shadowPass=false;
// View flattening: squeeze along the camera axis first, then into the head's own space.
vec3 toHead(vec3 p){ vec3 q=p-H; q.z/=FLAT; return q*Rh; }
vec2 hand(vec3 p,int i,vec3 W){
  vec3 q=(p-W)*hf[i]; float b=length(q-vec3(0,.28,0))-.5;
  if(b>.4) return vec2(b,2.);
  float d=box(q-vec3(0,.15,0),vec3(.13,.15,.045),.05);
  float c=curl[i],sp=spread[i];
  for(int j=0;j<4;j++){
    float x=(float(j)-1.5),len=.3-abs(x)*.035-(j==0?.04:0.);
    vec3 a=vec3(x*.082,.29,0.),dir1=normalize(vec3(x*sp*.34,cos(c*1.1),-sin(c*1.1))),e1=a+dir1*len*.55;
    vec3 dir2=normalize(vec3(x*sp*.34,cos(c*2.1),-sin(c*2.1))),e2=e1+dir2*len*.45;
    d=smin(d,min(cone(q,a,e1,.041,.036),cone(q,e1,e2,.036,.03)),.012);
  }
  vec3 t0=vec3(.13,.1,.03),t1=t0+vec3(.11+sp*.05,.1,.04),t2=t1+vec3(.04+sp*.06,.1,.02);
  d=smin(d,min(cone(q,t0,t1,.05,.042),cone(q,t1,t2,.042,.034)),.02);
  return vec2(d,2.);
}
vec2 map(vec3 p){
  vec3 h=toHead(p);
  float hb=length(h-vec3(0,.2,-.1))-2.15;
  vec2 res_=vec2(hb*FLAT+.05,1.);
  if(hb<.55){
    float d=ell(h-vec3(0,.14,-.06),vec3(.92,.9,.9));
    float jd=jaw*.13;
    d=smin(d,ell(h-vec3(0,-.3-jd*.5,.12),vec3(.66,.5,.58)),.2);
    d=smin(d,ell(h-vec3(0,-.84-jd,.3),vec3(.13,.1,.14)),.3);
    if(!shadowPass) d=smin(d,cone(h,vec3(0,-.14,.8),vec3(0,-.24,.83),.012,.016),.05);
    vec3 ax=vec3(abs(h.x),h.yz);
    d=smin(d,ell(ax-vec3(.9,-.08,-.06),vec3(.05,.17,.1)),.03);
    vec2 hair=vec2(1e3,4.);
    float capS=smin(ell(h-vec3(0,.2,-.1),vec3(.97,.96,.97)),${K.capBack},.2);
    capS=smax(capS,-(${K.capCut}),.03);
    hair=vec2(capS,4.);
    for(int i=0;i<NL;i++){
      if(length(h-LO[i])-LQ[i]>hair.x) continue;                // cheap test first, so many locks don't cost many cones
      vec3 B=LB[i]+sw1*LS[i]*.35,T=LC[i]+sw1*LS[i]; float r=LR[i];
      float l=min(cone(h,LA[i],B,r*.9,r*.76),cone(h,B,T,r*.76,.004));
      if(l<hair.x) hair=vec2(l,4.+float(i+1)/128.);
    }
    vec2 hd=opU(vec2(d,1.),hair);
    ${headset ? `
    float bandT=length(vec2(length(h.xy-vec2(0,.1))-1.1,h.z+.02))-.055;
    bandT=max(bandT,.06-h.y);
    hd=opU(hd,vec2(bandT,5.));
    vec2 cd=vec2(length(ax.yz-vec2(-.04,-.04))-.46,abs(ax.x-1.02)-.09);
    float cup=min(max(cd.x,cd.y),0.)+length(max(cd,0.))-.05;
    hd=opU(hd,vec2(cup,6.));` : `
    vec2 cd=vec2(length(ax.yz-vec2(-.04,-.02))-.24,abs(ax.x-.97)-.04);
    hd=opU(hd,vec2(min(max(cd.x,cd.y),0.)+length(max(cd,0.))-.03,6.));`}
    ${K.shades ? `
    float tmp=cap(ax,vec3(.72,.0,.46),vec3(1.,.02,-.1),.018);
    hd=opU(hd,vec2(tmp,7.));
    {vec3 B=vec3(-.98,-.5,.42)+sw2*.15,T=vec3(-.44,-.78,.86)+sw2*.3;
     if(!shadowPass){hd=opU(hd,vec2(min(cap(h,vec3(-1.02,-.3,.1),B,.02),cap(h,B,T,.02)),5.));
     hd=opU(hd,vec2(ell(h-T,vec3(.08,.045,.05)),5.));}}` : ''}
    hd.x*=FLAT;
    res_=hd;
  }
  // neck and body stay in true 3D: only the head is flattened
  res_=opU(res_,vec2(cone(p,NB,NT,.31,.27),2.));
  vec3 c=(p-C)*Rc;
  float bb=length(c)-3.4;
  if(bb<.5){
    float body=ell(c-vec3(0,-.2,0),vec3(.86,1.45,.56));
    body=smin(body,cap(c,vec3(-.88,.82,-.02),vec3(.88,.82,-.02),.27),.2);
    body=smin(body,cone(c,vec3(0,.6,-.02),vec3(0,1.26,-.03),.62,.3),.2);
    res_=opU(res_,vec2(body,3.));
    ${K.gear === 'ears' ? `
    res_=opU(res_,vec2(length(vec2(length(c.xz*vec2(1.,1.1)-vec2(0,-.02))-.32,(c.y-1.1)*1.5))-.1,3.1));` : `
    float hood=length(vec2(length(c.xz*vec2(1.,1.1)-vec2(0,-.02))-.4,(c.y-1.1)*1.15))-.2;
    hood=smin(hood,ell(c-vec3(0,1.08,-.42),vec3(.58,.36,.32)),.12);
    res_=opU(res_,vec2(hood,3.2));
    for(int i=0;i<2;i++){ float s=i==0?-1.:1.; vec3 a=vec3(s*.2,.96,.5),m=vec3(s*.22,.5,.62)+sw2*.2,e=vec3(s*.2,.06,.66)+sw2*.5;
      res_=opU(res_,vec2(min(cap(c,a,m,.018),cap(c,m,e,.018)),3.3)); }`}
  } else res_=opU(res_,vec2(bb,3.));
  // arms
  float armL=min(cone(p,sL,eL,.25,.19),cone(p,eL,wL,.19,.135)),armR=min(cone(p,sR,eR,.25,.19),cone(p,eR,wR,.19,.135));
  res_=opU(res_,vec2(armL,3.4)); res_=opU(res_,vec2(armR,3.5));
  res_=opU(res_,vec2(min(cone(p,mix(eL,wL,.92),wL,.145,.145),cone(p,mix(eR,wR,.92),wR,.145,.145)),3.6));
  res_=opU(res_,hand(p,0,wL)); res_=opU(res_,hand(p,1,wR));
  ${who === 'sol' ? `
  res_=opU(res_,vec2(box(p-vec3(-1.05,-1.62,1.15),vec3(1.5,.06,.42),.04),9.));
  {vec3 m=p-vec3(-2.35,-.42,1.1); m.xy*=rot(.22);
   res_=opU(res_,vec2(cap(m,vec3(0,-.42,0),vec3(0,.42,0),.27),8.));
   vec3 f=p-vec3(-1.5,-.32,1.2);
   res_=opU(res_,vec2(length(vec2(length(f.xy*vec2(1.,.72))-.44,f.z))-.024,8.1));
   res_=opU(res_,vec2(max(length(f.xy*vec2(1.,.72))-.44,abs(f.z)-.006),8.2));
   res_=opU(res_,vec2(cap(p,vec3(-2.5,-1.0,1.1),vec3(-3.6,-2.2,.8),.05),8.1));}` : ''}
  return res_;
}
vec3 normalAt(vec3 p){
  const vec2 e=vec2(1.,-1.)*.002;
  return normalize(e.xyy*map(p+e.xyy).x+e.yyx*map(p+e.yyx).x+e.yxy*map(p+e.yxy).x+e.xxx*map(p+e.xxx).x);
}
float shadowRay(vec3 ro,vec3 rd){
  float t=.03,s=1.;
  shadowPass=true;
  for(int i=0;i<14;i++){ float d=map(ro+rd*t).x; s=min(s,14.*d/t); t+=clamp(d,.03,.3); if(s<.01||t>3.)break; }
  shadowPass=false;
  return smoothstep(.3,.36,s);
}
float cel(float x,float at){ return smoothstep(at-.015,at+.015,x); }
float band(float x,float at,float w){ return smoothstep(at-w,at+w,x); }
// --- Face, painted on the head in its own coordinates, so it can never slide off it ---
void eyeDecal(inout vec3 col,vec2 q,float side,float lidv){
  vec2 r=vec2(${K.eye[0].toFixed(3)},${K.eye[1].toFixed(3)});
  float wd=max(lidv-1.,0.),l=SAT(lidv);
  vec2 R=vec2(r.x,r.y*(1.+wd*.6));
  float ux=q.x/R.x,v=side*ux;                                    // v: -1 inner corner, +1 outer corner
  if(squeeze>.5){ float d=abs(q.x*-side-(abs(q.y)-R.y*.4)*.8)-.012; d=max(d,abs(q.y)-R.y*.7); col=mix(${K.lash},col,smoothstep(0.,.006,d)); return; }
  // the lid is a nearly straight stroke rising to a sharp outer corner; the lower lid only exists at the outside
  float openT=R.y*(.92-.42*v*v+${K.slant.toFixed(2)}*v);
  float topv=mix(-R.y*.16+.05*R.y*v,openT,l);
  topv=mix(topv,R.y*.25-R.y*1.05*(1.-ux*ux)*-1.-R.y*.6,arc)+tilt*R.y*.34*(-v)*(1.-arc)+min(tilt,0.)*R.y*.22;
  float botv=mix(-R.y*.2,-R.y*(.86-.62*v*v)+.1*R.y*v,SAT(l*3.))+low*R.y*.5*(1.-ux*ux);
  if(arc>.01) botv=mix(botv,topv-.012,arc);
  if(abs(ux)>1.05) return;
  float inside=min(q.y-botv,topv-q.y);
  if(inside>0.&&abs(ux)<1.){
    vec3 w=vec3(.98,.98,1.);
    w=mix(vec3(.72,.76,.88),w,step(R.y*.2,topv-q.y));           // a hard lid shadow, one flat tone
    vec2 g=vec2(gazeX*R.x*.3,gazeY*R.y*.18);
    vec2 d=q-g; float irisR=length(d/vec2(R.x*.58,R.y*1.02));
    ${K.tintIris ? 'vec3 i0=vec3(.05,.05,.2),i1=tint;' : `vec3 i0=${K.iris[0]},i1=${K.iris[1]};`}
    vec3 ir=mix(i1,i0,step(-.12,d.y/R.y));                        // two flat tones, split like a cel
    ir=mix(ir,mix(i1,vec3(1.),.45),step(.62,-d.y/R.y));           // a bright crescent at the bottom
    ir=mix(i0*.5,ir,step(irisR,.9));
    if(heart>.5){ float hd=heartSdf(d/(R.y*.62*(heart*.8+.2))); ir=mix(vec3(1.,.15,.45),ir,step(.0,hd)); }
    else ir=mix(vec3(.015,.015,.04),ir,step(.42*pupil,length(d/vec2(R.x*.58,R.y*.9))));
    w=mix(ir,w,step(1.,irisR));
    w=mix(vec3(1.),w,step(.26,length((d-vec2(-R.x*.2,R.y*.32))/R.y)));   // one hard highlight, fixed to the light
    w=mix(vec3(1.),w,step(.1,length((d-vec2(R.x*.2,-R.y*.42))/R.y)));
    if(sparkle>.2){ vec2 a=abs(d-vec2(R.x*.24,R.y*.24)); w=mix(vec3(1.),w,1.-sparkle*step(a.x*a.y*16.+length(a)*.1,.008)); }
    col=w;
  }
  // upper lash: a tapered wedge, heavy at the outer corner, with a flick past it
  float th=mix(.008,${K.wing ? '.04' : '.03'},SAT(.5+.5*v))*mix(.55,1.,l*(1.-arc));
  if(abs(ux)<1.05) col=mix(${K.lash},col,step(th,abs(q.y-topv-th*.5)*2.));
  if(arc<.5&&l>.3){ vec2 f=q-vec2(side*R.x*.98,topv); float fl=abs(f.y-(f.x*side)*.5)-.012*(1.-SAT(f.x*side/.07)); col=mix(${K.lash},col,step(0.,max(fl,max(-f.x*side,f.x*side-.07)))); }
  if(arc<.6&&l>.2) col=mix(${K.lash},col,1.-step(.2,v)*step(abs(q.y-botv),.0045));
  if(l>.45&&arc<.5&&v<.9&&v>-.6) col=mix(${K.skin[1]},col,step(.004,abs(q.y-topv-R.y*.42-th)));   // a single fold line above the lid
}
void browDecal(inout vec3 col,vec2 q,float side,float by,float a){
  float x=(q.x*side-${(K.eyeX + 0.01).toFixed(3)})/.2;   // -1 inner .. 1 outer
  float y=.13+by*.09-tilt*.1*(-x)+min(tilt,0.)*.02+.018*(1.-x*x)-x*.022;
  float th=mix(.016,.002,SAT(x*.5+.5));
  float d=max(abs(q.y-y)-th,abs(x)-1.);
  col=mix(col,${K.brow},a*step(d,0.));
}
void mouthDecal(inout vec3 col,vec2 q0){
  float sm=smile+${K.smirk.toFixed(2)}*(1.-jaw*.5),mxv=mouthX+${K.smirkX.toFixed(2)};
  vec2 q=q0-vec2(mxv*.05,-.53-jaw*.03);
  float W=.13*(1.+wide*.5-round*.5+max(sm,0.)*.45+jaw*.2),Hm=.27*jaw+.05*round;
  float ux=q.x/W;
  float yTop=sm*.065*(ux*ux)-sm*.016+mxv*.03*ux;
  if(Hm<.012){
    float d=max(abs(q.y-yTop)-mix(.006,.002,ux*ux),abs(ux)-1.);
    col=mix(col,vec3(.42,.2,.2),smoothstep(.004,-.002,d));
    return;
  }
  float yBot=yTop-Hm*(1.-ux*ux*.85);
  float inside=min(q.y-yBot,yTop-q.y);
  if(abs(ux)<1.&&inside>0.){
    vec3 m=mix(vec3(.46,.11,.15),vec3(.26,.05,.09),SAT((yTop-q.y)/Hm));
    float ty=(q.y-yBot)/max(Hm,.001);
    m=mix(vec3(.95,.5,.55),m,smoothstep(.0,.03,length(vec2(ux*.8,ty-.05)*vec2(1.,1.1))-.42));
    m=mix(m,vec3(.99,.99,1.),step(yTop-Hm*.2-.006,q.y));
    if(teeth>.2) m=mix(m,vec3(.99),teeth);
    col=m;
  }
  float e=abs(inside); col=mix(vec3(.34,.13,.16),col,min(1.,smoothstep(.0,.008,e)+step(1.,abs(ux))));
}
vec3 skinCol(vec3 h,vec3 p,vec3 n,float id,float light,float ao){
  vec3 base=${K.skin[0]},sh=${K.skin[1]};
  vec3 col=mix(sh,base,light);
  if(id==2.) return col;
  // soft cheek colour and blush: part of the skin, so it turns with the head
  for(int s=-1;s<=1;s+=2){
    float dc=length((h.xy-vec2(float(s)*.46,-.34))*vec2(1.,1.5));
    col=mix(col,vec3(1.,.5,.5),blush*.6*smoothstep(.26,.1,dc));
    if(blush>.55){ vec2 q=h.xy-vec2(float(s)*.46,-.34); float hat=smoothstep(.012,.004,abs(fract((q.x+q.y*.4)*22.)-.5)/22.)*step(abs(q.y),.05)*step(abs(q.x),.1); col=mix(col,vec3(.86,.25,.34),hat*(blush-.55)*2.); }
  }
  if(h.z>0.){
    // the nose is a small shadow, as anime draws it
    {vec2 nq=h.xy-vec2(.012,-.25); col=mix(col,${K.skin[1]}*.85,step(abs(nq.x-nq.y*.35)+abs(nq.y)*.5,.013));}
    eyeDecal(col,h.xy-vec2(-${K.eyeX.toFixed(3)},-.06),-1.,lidL);
    eyeDecal(col,h.xy-vec2(${K.eyeX.toFixed(3)},-.06),1.,lidR);
    browDecal(col,h.xy,-1.,browL,1.);
    browDecal(col,h.xy,1.,browR,1.);
    mouthDecal(col,h.xy);
    if(tear>.25){ for(int s=-1;s<=1;s+=2){ vec2 q=h.xy-vec2(float(s)*.37,-.2-fract(time*.6+float(s)*.3)*.3); col=mix(vec3(.72,.9,1.),col,smoothstep(.014,.03,length(q*vec2(1.,.6)))); } }
    ${K.shades ? `
    for(int s=-1;s<=1;s+=2){
      vec2 q=h.xy-vec2(float(s)*.37,-.07-(browL+browR)*.012);
      float x=q.x*float(s)/.285;
      float topE=.115+tilt*.03*(-x);
      float bowl=-(.165-.09*x*x-.05*x);
      float lens=max(max(q.y-topE,bowl-q.y),abs(x)-1.)*1.;
      if(lens<.012){
        float fr=smoothstep(.0,.012,lens+.012)*1.;
        vec3 glass=mix(vec3(.015,.014,.018),vec3(.24,.19,.17),smoothstep(0.,.3,topE-q.y));
        glass+=col*.09;
        float gl=fract((q.x+yaw*.55+gazeX*.02)*1.7+q.y*.8+.5);
        glass+=vec3(.5,.74,.9)*(.12+sparkle*.3+energy*.05)*smoothstep(.09,.0,abs(gl-.5)-.03);
        col=mix(glass,vec3(.3,.31,.34),smoothstep(-.014,-.009,lens));
      }
    }
    if(abs(h.x)<.1) col=mix(col,vec3(.16,.17,.2),smoothstep(.012,.007,abs(h.y-.045)));` : ''}
  }
  return col;
}
// Paints along each lock's own length and width: darker roots, a tone per lock, fine strand lines, and a sheen combed into streaks.
vec3 hairCol(vec3 h,vec3 n,float light,float id,float ao){
  vec3 base=${K.hair[0]},sh=${K.hair[1]};
  ${K.hairTip ? `base=mix(base,${K.hairTip},smoothstep(-.1,-1.3,h.y)); sh=mix(sh,${K.hairTip}*.62,smoothstep(-.1,-1.3,h.y));` : ''}
  int i=int(fract(id)*128.+.5)-1;
  float u=.45,v=atan(h.x,h.z)*2.2,seed=.5;
  if(i>=0){
    vec3 A=LA[i],B=LB[i]+sw1*LS[i]*.35,T=LC[i]+sw1*LS[i];
    float t1=SAT(dot(h-A,B-A)/dot(B-A,B-A)),t2=SAT(dot(h-B,T-B)/dot(T-B,T-B));
    vec3 p1=A+(B-A)*t1,p2=B+(T-B)*t2;
    bool first=length(h-p1)<length(h-p2);
    vec3 sp=first?p1:p2,dir=normalize(first?B-A:T-B),side=normalize(cross(dir,normalize(sp)));
    u=first?t1*.5:.5+t2*.5;
    v=dot(h-sp,side)/max(LR[i]*mix(1.,.2,u*u),.02);
    seed=fract(float(i)*.6180339);
  }
  vec3 col=mix(sh,base,light);
  col*=1.+(seed-.5)*.07;
  col=mix(col,sh*.7,smoothstep(.035,.012,abs(v-(seed-.5)*.5))*.45*smoothstep(.08,.3,u));   // one thin line down each lock
  float zig=abs(fract(v*.75+seed*3.)-.5)*.11;
  float hi=step(abs(h.y-.54+h.x*h.x*.26+zig-(seed-.5)*.05),.034+.03*(1.-abs(v)))*step(-.25,h.z);
  col=mix(col,${K.ring},hi*.82*step(.5,light));
  return col;
}
void main(){
  vec2 px=(gl_FragCoord.xy-.5*res)/min(res.x,res.y)*2.;
  vec3 ro=vec3(view.x,view.y,16.),rd=normalize(vec3(px*.155,-1.));   // a long lens keeps the 2D, flat read
  float t=9.5,id=0.; bool hit=false;
  for(int i=0;i<90;i++){
    vec2 m=map(ro+rd*t);
    if(m.x<.0012){hit=true;id=m.y;break;}
    t+=m.x*.9;
    if(t>23.)break;
  }
  if(!hit){ frag=vec4(0); gbuf=vec4(1e3,0,0,0); return; }
  vec3 p=ro+rd*t,n=normalAt(p),h=toHead(p);
  float main_=floor(id);
  // Anime normal transfer: the face is shaded as if it were a smooth ball, so shadows never break around the nose.
  vec3 nL=n;
  bool head=main_==1.;
  if(head){ vec3 ns=Rh*normalize(h-vec3(0,-.05,-.35)); nL=normalize(mix(n,ns,(abs(h.x)<.12&&h.y<0.&&h.y>-.42)?1.:.86)); }
  float d=dot(nL,head||main_==2.?normalize(vec3(-.38,.42,.82)):LIGHT);
  float sh=(main_==1.||main_==3.||main_==2.)?shadowRay(p+n*.03,LIGHT):1.;
  // Hard two-tone light: the shadow is a shape with a clean edge, as a cel painter would draw it.
  float light=band(d,main_==4.?${K.hairAt.toFixed(2)}:head?.2:.12,.012)*sh;
  float ao=SAT(map(p+n*.1).x/.1);
  vec3 col=vec3(.5);
  if(main_==1.||main_==2.) col=skinCol(h,p,n,main_,light,ao);
  else if(main_==4.) col=hairCol(h,n,light,id,ao);
  else if(main_==3.){
    vec3 cl=(p-C)*Rc;
    vec3 base=${K.cloth},shC=${K.clothSh};
    ${who === 'sol' ? `float tb=step(id,3.05)*smoothstep(-.09,-.08,cl.y+.2*cl.x*cl.x-.04*0.)*0.; if(id<3.05&&cl.y<-.14&&cl.y>-1.05){base=vec3(.96,.94,.89);shC=vec3(.72,.66,.72);}` : ''}
    col=mix(shC,base,light);
    float warp=noise(cl*vec3(1.6,1.6,1.));
    if(id<3.05){ float f=sin(dot(cl.xy,vec2(cl.x>0.?-2.2:2.2,3.))*3.1+warp*5.)*.5+.5; col=mix(col,shC,step(.965,f)*step(-.6,cl.y)*step(.16,abs(cl.x))); }
    if(id>3.35&&id<3.55){ vec3 elb=id<3.45?eL:eR; float e=length(p-elb); float f=sin(e*20.+warp*6.)*.5+.5; col=mix(col,shC,step(.9,f)*step(e,.3)); }
    if(id>3.55){ col*=.9+.1*step(.5,fract(atan((p.x-(wL.x+wR.x)*.5)*2.,p.z)*7.)); }
    // fold shadows, painted with the same two tones
    ${K.gear === 'ears' ? `if(id<3.05&&cl.z>.2){ col=mix(vec3(.5,.52,.7),col,smoothstep(.006,.012,abs(cl.x))); float lamp=length(cl.xy-vec2(.48,.1)); col=mix(tint*(1.2+energy),col,smoothstep(.07,.1,lamp)); }` : `
    if(id<3.05&&cl.z>.1){ float z=abs(cl.x); float wd=.05+max(0.,cl.y+.2)*${who === 'sol' ? '.17' : '.05'}; col=mix(${who === 'ace' ? 'vec3(.05,.055,.07)' : 'vec3(.13,.12,.16)'},col,smoothstep(wd-.006,wd,z)); float zp=abs(z-wd); if(zp<.016) col=mix(col,${who === 'ace' ? 'vec3(.4,.43,.5)' : 'vec3(.82,.8,.76)'},step(.5,fract(cl.y*30.))*.8); }
    if(id>3.25&&id<3.35) col=${who === 'ace' ? 'vec3(.45,.8,.95)' : 'vec3(.97,.96,.94)'};`}
      }
  else if(main_==5.) col=mix(vec3(.05,.05,.07),vec3(.24,.25,.3),light);
  else if(main_==6.){
    ${K.gear === 'ears' ? `
    vec2 q=h.yz-vec2(-.04,-.02); float r=length(q);
    col=mix(vec3(.68,.70,.85),vec3(.97),light); if(r<.14) col=tint*(1.1+energy*.5);` : `
    vec2 q=h.yz-vec2(-.04,-.04); float r=length(q);
    col=mix(vec3(.05,.05,.07),vec3(.2,.21,.26),light);
    if(abs(h.x)>1.06){
      col=mix(vec3(.03),col,smoothstep(.34,.36,r));
      ${who === 'ace' ? `float xx=min(abs(q.x-q.y),abs(q.x+q.y))/1.414; col=mix(vec3(.45,.92,1.)*(1.+energy),col,smoothstep(.016,.03,xx)+step(.2,r));` : `
      float a=atan(q.y,q.x); col=mix(vec3(.42,.92,1.)*(1.+energy*.6),col,smoothstep(.012,.024,abs(r-.27))+step(1.5,a));
      col=mix(vec3(.92,.96,.4)*(1.+energy*.6),col,smoothstep(.012,.024,abs(r-.19))+step(a,-.5));`}
    }`}
  }
  else if(main_==7.) col=vec3(.42,.44,.5);
  else if(main_==8.){
    vec3 m=p-vec3(-2.35,-.42,1.1); m.xy*=rot(.22);
    col=mix(vec3(.08,.07,.1),vec3(.36,.34,.42),light);
    if(id>8.15) col=mix(vec3(.05,.035,.08),vec3(.16,.11,.2),smoothstep(.5,-.5,p.y+.32));
    if(id<8.05&&m.y>-.02) col*=.72+.28*step(.5,fract(m.y*24.));
    if(id<8.05&&length(m.xy-vec2(0,-.2))<.028) col=vec3(.5,.95,.88);
  }
  else if(main_==9.){
    vec3 kb=p-vec3(-1.05,-1.62,1.15);
    col=vec3(.9,.89,.93);
    if(n.y>.5){
      vec2 kk=vec2(fract(kb.x*7.5),fract(kb.z*4.5));
      col=mix(vec3(.18,.16,.24),col,step(.09,min(min(kk.x,1.-kk.x),min(kk.y,1.-kk.y))));
    } else col=mix(vec3(.38,.95,.88),vec3(1.,.42,.7),SAT(kb.x/3.+.5));
  }
  // rim light from the room, cut as a clean band, on the side away from the key
  float nv=max(dot(n,-rd),0.);
  float rim=step(.36,pow(1.-nv,2.2)*(.6+.4*dot(n,normalize(vec3(.8,.2,-.2)))));
  if(main_<=4.) col=mix(col,${K.rim},rim*(1.-light)*.75);
  col*=${K.grade};
  frag=vec4(col,1.);
  gbuf=vec4(t,id,n.xy);
}`;
}

const INK = `#version 300 es
precision highp float;
uniform sampler2D color,gbuf; uniform vec2 res; uniform float lineW;
out vec4 frag;
void main(){
  vec2 uv=gl_FragCoord.xy/res,e=lineW/res;
  vec4 c=texture(color,uv);
  vec4 g=texture(gbuf,uv);
  float edge=0.; float nearest=g.x; vec3 src=c.rgb; float alphaNear=c.a;
  for(int i=0;i<16;i++){
    float a=float(i)*.7854;
    vec2 off=vec2(cos(a),sin(a))*e*(i<8?1.:1.9);
    vec4 o=texture(gbuf,uv+off);
    if(i>=8&&!(g.x>500.||o.x>500.)) continue;            // the wider ring only counts for the outer silhouette
    float dep=abs(o.x-g.x);
    float idE=abs(o.y-g.y)>.0005?1.:0.;
    bool bothHair=floor(o.y)==4.&&floor(g.y)==4.;
    float dn=length(o.zw-g.zw);
    float thisE=0.;
    if(g.x>500.||o.x>500.) thisE=(o.x<g.x)?1.:(g.x<500.?1.:0.);   // silhouette
    else if(idE>.5&&bothHair&&dep>.03) thisE=.55;
    else if(idE>.5&&!bothHair) thisE=1.;
    else if(floor(g.y)==1.&&floor(o.y)==1.) thisE=dep>.35?1.:0.;
    else if(dep>.09) thisE=1.;
    else if(dn>.7&&floor(g.y)!=1.&&floor(g.y)!=4.) thisE=.7;
    if(thisE>edge){ edge=thisE; }
    if(o.x<nearest){ nearest=o.x; vec4 oc=texture(color,uv+off); src=oc.rgb; alphaNear=oc.a; }
  }
  // lines are a darker shade of whatever they border: coloured ink, not a black marker
  vec3 ink=src*src*.22+vec3(.012,.008,.02);
  float a=max(c.a,edge*alphaNear);
  vec3 col=mix(c.rgb,ink,edge);
  frag=vec4(col*a,a);
}`;

// A pack recolours a built-in face (validated by jaeger_avatar.packs): [r,g,b] in 0..1, or a [light, shadow] pair for skin, hair, iris.
const PALETTE = ['skin', 'hair', 'iris', 'hairTip', 'ring', 'brow', 'lash', 'cloth', 'clothSh', 'rim'];
const colour = c => v3(c.map(n => clamp(Number(n), 0, 1)));
export function withPalette(base, palette = {}) {
  const K = { ...base };
  for (const k of PALETTE.filter(k => palette[k])) K[k] = Array.isArray(palette[k][0]) ? palette[k].map(colour) : colour(palette[k]);
  if (palette.iris) K.tintIris = false;
  if (palette.rim) K.wash = palette.rim.map(n => Math.round(clamp(Number(n), 0, 1) * 255)).join(',');
  return K;
}

const BONE = { upper: 1.15, fore: 1.1 };
export const TIMING = { onTwos: true };

export class AnimeChar {
  constructor(canvas, overlay, who, palette) {
    this.c = canvas; this.ov = overlay; this.oc = overlay.getContext('2d'); this.who = who; this.K = withPalette(CHARS[who], palette);
    this.room = document.createElement('canvas');
    this.room.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block';
    this.room.className = 'bgl';
    canvas.parentNode.insertBefore(this.room, canvas);
    const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: 'high-performance', preserveDrawingBuffer: true });
    this.gl = gl;
    if (!gl || !gl.getExtension('EXT_color_buffer_float')) { this.error = 'needs WebGL2 float targets'; console.error(this.error); return; }
    const program = fsSrc => {
      const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { this.error = gl.getShaderInfoLog(s); console.error(who, this.error); } return s; };
      const pr = gl.createProgram(); gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fsSrc)); gl.linkProgram(pr);
      if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { this.error = gl.getProgramInfoLog(pr); console.error(who, this.error); }
      return pr;
    };
    this.scene = program(fragment(who, this.K)); this.ink = program(INK);
    if (this.error) return;
    this.U = n => gl.getUniformLocation(this.scene, n);
    gl.bindVertexArray(gl.createVertexArray());
    this.tex = [gl.createTexture(), gl.createTexture()]; this.fbo = gl.createFramebuffer();
    this.vals = new Float32Array(NAMES.length); this.joints = new Float32Array(18);
    this.scale = 1; this.slow = 0;
    this.sp = { x: 0, y: 0, z: 0, vx: 0, vy: 0, px: 0, py: 0, init: false };
    this.sp2 = { x: 0, y: 0, z: 0, vx: 0, vy: 0, px: 0, py: 0, init: false };
    this.wrist = [{ p: null, v: [0, 0, 0] }, { p: null, v: [0, 0, 0] }];
    this.gest = [[0, 0], [0, 0]]; this.wasTalking = false; this.nextAct = 4 + Math.random() * 6; this.act = null; this.wave = new Float32Array(160);
  }

  target(w, h) {
    const gl = this.gl;
    if (this.tw === w && this.th === h) return;
    this.tw = w; this.th = h;
    gl.bindTexture(gl.TEXTURE_2D, this.tex[0]); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.bindTexture(gl.TEXTURE_2D, this.tex[1]); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, w, h, 0, gl.RGBA, gl.FLOAT, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.tex[0], 0);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT1, gl.TEXTURE_2D, this.tex[1], 0);
    gl.drawBuffers([gl.COLOR_ATTACHMENT0, gl.COLOR_ATTACHMENT1]);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }

  // --- the skeleton, in world space ---------------------------------------------------------
  solve(rig, dt) {
    const o = rig.out, K = this.K, t = rig.t, h = Math.min(dt, 1 / 30);
    const rotY = a => { const c = Math.cos(a), s = Math.sin(a); return [c, 0, -s, 0, 1, 0, s, 0, c]; };   // column-major
    const rotX = a => { const c = Math.cos(a), s = Math.sin(a); return [1, 0, 0, 0, c, s, 0, -s, c]; };
    const rotZ = a => { const c = Math.cos(a), s = Math.sin(a); return [c, s, 0, -s, c, 0, 0, 0, 1]; };
    const mul = (A, B) => { const r = new Array(9); for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) r[j * 3 + i] = A[i] * B[j * 3] + A[3 + i] * B[j * 3 + 1] + A[6 + i] * B[j * 3 + 2]; return r; };
    const ap = (M, v) => [M[0] * v[0] + M[3] * v[1] + M[6] * v[2], M[1] * v[0] + M[4] * v[1] + M[7] * v[2], M[2] * v[0] + M[5] * v[1] + M[8] * v[2]];
    const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], mulS = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
    const len = a => Math.hypot(a[0], a[1], a[2]), norm = a => mulS(a, 1 / (len(a) || 1)), cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

    // chest turns about the base of the spine, later and less than the head
    const Rc = mul(mul(rotY(o.chestYaw * 0.9 + K.chestYaw), rotX(-o.chestPitch * 0.5)), rotZ(o.chestRoll * 0.75 + K.chestRoll));
    const base = [o.hipX * 0.05, -3.55 - o.crouch * 0.22 + o.lift * 0.12, 0];
    const C = add(base, ap(Rc, [0, 2.35 + o.breath * 0.012, 0]));
    const NB = add(base, ap(Rc, [0, 3.56, -0.02]));
    const headTilt = rotZ(o.roll * 0.42 + K.headRoll);
    const Rh = mul(mul(rotY(o.yaw * 0.62 + K.headYaw), rotX(-o.pitch * 0.5 - K.headPitch)), headTilt);
    const NT = add(NB, ap(mul(Rc, rotX(-0.05 + o.pitch * 0.1)), [o.roll * 0.05, 0.47, 0]));
    const H = add(NT, ap(Rh, [0, 0.98, 0.04]));

    // Each burst of speech picks a fresh gesture, so talking hands don't repeat one motion.
    const talking = o.hand > 0.16;
    if (talking && !this.wasTalking) { const pick = () => [(Math.random() - 0.5) * 0.9, (Math.random() - 0.3) * 0.7]; this.gest = [pick(), pick()]; }
    this.wasTalking = talking;
    // Idle actions: a hand goes somewhere on its own now and then, like a person who isn't being animated.
    this.nextAct -= dt;
    if (this.nextAct <= 0 && !this.act && rig.mode === 'idle') { this.act = { t: 0, dur: 2.2 + Math.random(), s: Math.random() < 0.5 ? 0 : 1 }; this.nextAct = 8 + Math.random() * 9; if (this.who === 'sol') rig.look(-0.55, -0.05); }
    let actE = 0;
    if (this.act) { const a = this.act; a.t += dt; const u = a.t / a.dur; actE = u >= 1 ? 0 : Math.min(1, u * 4) * Math.min(1, (1 - u) * 3.5); if (u >= 1 || rig.mode !== 'idle') this.act = null; }
    this.typing = clamp(Math.max(o.type ?? 0, this.who === 'sol' && this.act ? actE : 0), 0, 1);

    const hf = new Float32Array(18), curl = new Float32Array(2), spread = new Float32Array(2);
    [-1, 1].forEach((s, i) => {
      const S = add(base, ap(Rc, [s * 1.1, 3.1 + (s < 0 ? o.shL : o.shR) * 0.3, -0.02]));
      const wave = s > 0 ? clamp(o.wave, 0, 1) : 0, shrug = clamp(o.shrug, 0, 1), talk = clamp(o.hand * (s > 0 ? 0.95 : 0.55), 0, 1), g = this.gest[i];
      let T, fingers, open;
      if (this.who === 'sol') {
        const onKeys = [-1.05 + s * 0.5 + Math.sin(t * 11 + s) * 0.012 * this.typing, -1.2, 0.92];
        T = add(onKeys, [talk * (0.3 + g[0]), talk * (0.7 + g[1]), talk * 0.1]);
        fingers = [lerp(-0.1 * s, -0.25 * s, talk), lerp(-0.72, 0.7, talk), lerp(0.7, 0.6, talk)]; open = talk;
      } else {
        T = [s * 1.5 + talk * (s * -0.5 + g[0]), -3.6 + talk * (2.5 + g[1]), 0.1 + talk * 0.9];
        fingers = [s * 0.2, talk > 0.2 ? 0.8 : -1, talk > 0.2 ? 0.5 : 0]; open = talk;
        if (this.act && this.act.s === i) {             // settling the headset, or tucking hair behind an ear
          const ear = add(H, ap(Rh, [s * 1.02, -0.45, 0.2]));
          for (let k = 0; k < 3; k++) T[k] = lerp(T[k], ear[k], actE);
          fingers = [lerp(fingers[0], -s * 0.2, actE), lerp(fingers[1], 0.9, actE), lerp(fingers[2], 0.2, actE)]; open = Math.max(open, actE * 0.5);
        }
      }
      T = [lerp(T[0], s * 2.3, shrug), lerp(T[1], -1.5, shrug), lerp(T[2], 0.7, shrug)];
      fingers = [lerp(fingers[0], s * 0.75, shrug), lerp(fingers[1], 0.5, shrug), lerp(fingers[2], 0.4, shrug)]; open = Math.max(open, shrug);
      const wx = (this.who === 'sol' ? 1.32 : 2.0) + Math.sin(t * 9.5) * 0.2, wy = 1.05 + Math.cos(t * 9.5) * 0.05;
      T = [lerp(T[0], wx, wave) + Math.sin(Math.PI * wave) * 0.5, lerp(T[1], wy, wave), lerp(T[2], 0.6, wave)];
      fingers = [lerp(fingers[0], Math.sin(t * 9.5) * 0.3, wave), lerp(fingers[1], 1, wave), lerp(fingers[2], 0.1, wave)]; open = Math.max(open, wave);

      const w = this.wrist[i];
      if (!w.p) w.p = T.slice();
      for (let k = 0; k < 3; k++) { const K_ = 150, C_ = 2 * 0.72 * Math.sqrt(K_); w.v[k] += (K_ * (T[k] - w.p[k]) - C_ * w.v[k]) * h; w.p[k] += w.v[k] * h; }
      // two-bone IK, in 3D: the elbow sits in the plane of the arm and a pole that points down and out
      let d = sub(w.p, S), dl = len(d); const reach = BONE.upper + BONE.fore - 0.01;
      if (dl > reach) { d = mulS(d, reach / dl); dl = reach; }
      const W = add(S, d), u = norm(d), a = (BONE.upper ** 2 - BONE.fore ** 2 + dl * dl) / (2 * dl), hh = Math.sqrt(Math.max(0, BONE.upper ** 2 - a * a));
      let pole = [s * 0.65, -0.75, -0.25]; pole = norm(sub(pole, mulS(u, pole[0] * u[0] + pole[1] * u[1] + pole[2] * u[2])));
      const E = add(add(S, mulS(u, a)), mulS(pole, hh));
      this.joints.set([...S, ...E, ...W], i * 9);
      // hand frame: X across the knuckles, Y along the fingers, Z out of the back of the hand
      const Y = norm(fingers), toBody = [-s, 0, 0.001], dotT = toBody[0] * Y[0] + toBody[1] * Y[1] + toBody[2] * Y[2];
      const X = norm(sub(toBody, mulS(Y, dotT)));
      let Z = cross(X, Y); if (Z[2] < 0) Z = mulS(Z, -1);
      hf.set([...X, ...Y, ...Z], i * 9);
      curl[i] = lerp(lerp(0.55, 0.9, this.who === 'sol' ? this.typing : 0), 0.03, open);
      if (this.who === 'sol' && this.typing > 0.1) curl[i] -= Math.max(0, Math.sin(t * 13 + i * 2)) * 0.2 * this.typing;
      spread[i] = lerp(0.12, 1, open);
    });

    // secondary motion: hair and cords lag the head
    const step = (sp, K_, D, gain, x, y) => {
      if (!sp.init) { sp.px = x; sp.py = y; sp.init = true; }
      const q = Math.max(h, 1 / 240);
      sp.vx += (-K_ * sp.x - D * sp.vx - (x - sp.px) / q * gain) * q; sp.x += sp.vx * q; sp.px = x;
      sp.vy += (-K_ * sp.y - D * sp.vy - (y - sp.py) / q * gain) * q; sp.y += sp.vy * q; sp.py = y;
    };
    step(this.sp, 90, 8, 1, H[0], H[1]); step(this.sp2, 40, 4.5, 1, H[0], H[1]);
    return { Rh, Rc, H, C, NB, NT, hf, curl, spread };
  }

  // --- the room is 2D, painted once, and sits behind the transparent character ------------------
  paintRoom(W, H, Z) {
    const r = this.room; r.width = Math.round(W * 1.08); r.height = Math.round(H * 1.08);
    r.style.width = '108%'; r.style.height = '108%';
    const g = r.getContext('2d'), w = r.width, h = r.height, who = this.who;
    const dot = (x, y, rr, col, a) => { const b = g.createRadialGradient(x, y, 0, x, y, rr); b.addColorStop(0, `rgba(${col},${a})`); b.addColorStop(0.8, `rgba(${col},${a * 0.8})`); b.addColorStop(1, `rgba(${col},0)`); g.fillStyle = b; g.fillRect(x - rr, y - rr, rr * 2, rr * 2); };
    const bg = g.createLinearGradient(0, 0, 0, h);
    if (who === 'ace') {
      bg.addColorStop(0, '#04101f'); bg.addColorStop(0.55, '#0e3358'); bg.addColorStop(1, '#06121f');
      g.fillStyle = bg; g.fillRect(0, 0, w, h);
      for (const [x, sp] of [[0.18, -0.2], [0.42, 0.05], [0.74, 0.22]]) { const gr = g.createLinearGradient(0, 0, 0, h * 0.85); gr.addColorStop(0, 'rgba(150,215,255,.16)'); gr.addColorStop(1, 'rgba(150,215,255,0)'); g.fillStyle = gr; g.beginPath(); g.moveTo(w * x - 30 * Z, 0); g.lineTo(w * x + 30 * Z, 0); g.lineTo(w * (x + sp) + 170 * Z, h * 0.85); g.lineTo(w * (x + sp) - 170 * Z, h * 0.85); g.fill(); }
      for (let i = 0; i < 44; i++) dot(((i * 137.5) % 1000) / 1000 * w, (0.12 + ((i * 61.8) % 100) / 100 * 0.5) * h, (10 + (i * 7) % 34) * Z, i % 7 ? '140,205,255' : '255,210,150', 0.1 + ((i * 13) % 10) / 45);
    } else if (who === 'sol') {
      bg.addColorStop(0, '#1b1030'); bg.addColorStop(0.6, '#34204f'); bg.addColorStop(1, '#201436');
      g.fillStyle = bg; g.fillRect(0, 0, w, h);
      g.strokeStyle = 'rgba(224,140,255,.9)'; g.lineWidth = 5 * Z; g.lineJoin = 'round'; g.shadowColor = '#c77dff'; g.shadowBlur = 34 * Z;
      g.beginPath(); g.moveTo(-10, h * 0.2); g.lineTo(w * 0.1, h * 0.11); g.lineTo(w * 0.17, h * 0.05); g.lineTo(w * 0.58, h * 0.13); g.stroke();
      g.shadowBlur = 0;
      const pane = (x, y, pw, ph) => { const sh = g.createLinearGradient(0, y, 0, y + ph); sh.addColorStop(0, '#1a1330'); sh.addColorStop(1, '#100b20'); g.fillStyle = sh; g.strokeStyle = '#463a66'; g.lineWidth = 4 * Z; g.beginPath(); g.roundRect(x, y, pw, ph, 10 * Z); g.fill(); g.stroke(); };
      const m = this.monitor = { x: w * 0.04, y: h * 0.16, w: w * 0.56, h: h * 0.28 }, y2 = m.y + m.h + 10 * Z, hh = h * 0.3;
      pane(m.x, m.y, m.w, m.h); pane(m.x, y2, m.w, hh);
      for (let i = 0; i < 12; i++) { g.fillStyle = i % 4 === 0 ? 'rgba(126,240,224,.55)' : 'rgba(200,170,255,.42)'; g.fillRect(m.x + m.w * (0.06 + (i % 3) * 0.03), y2 + hh * (0.09 + i * 0.07), m.w * (0.16 + ((i * 37) % 50) / 100), 4.5 * Z); }
    } else {
      bg.addColorStop(0, '#141a38'); bg.addColorStop(0.55, '#2a2a5c'); bg.addColorStop(1, '#433263');
      g.fillStyle = bg; g.fillRect(0, 0, w, h);
      dot(w * 0.2, h * 0.3, 280 * Z, '150,130,255', 0.18); dot(w * 0.82, h * 0.62, 340 * Z, '255,150,190', 0.13);
      for (let i = 0; i < 54; i++) dot(((i * 211.3) % 1000) / 1000 * w, ((i * 97.7) % 1000) / 1000 * h, (2 + (i * 11) % 13) * Z, i % 5 ? '215,230,255' : '255,210,235', 0.16 + ((i * 7) % 10) / 22);
    }
    const v = g.createRadialGradient(w / 2, h * 0.45, Math.min(w, h) * 0.5, w / 2, h * 0.45, Math.max(w, h) * 0.85);
    v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,.45)'); g.fillStyle = v; g.fillRect(0, 0, w, h);
  }

  draw(rig, W, H, dt, force = false) {
    const gl = this.gl;
    if (!gl || !this.ink || this.error) return;
    const o = rig.out, Z = Math.min(W, H) / 1000;
    if (this.rw !== W || this.rh !== H) { this.rw = W; this.rh = H; this.paintRoom(W, H, Z); }
    this.room.style.transform = `translate(${-4 - o.yaw * 0.5}%,${-4 + o.pitch * 0.3}%)`;

    const B = this.solve(rig, dt);
    // Film anime holds each drawing for two or three frames. The skeleton keeps running underneath; we only show it on twos.
    if (TIMING.onTwos && !force && rig.t - (this.shownAt ?? -1) < 1 / 12 - 0.004 && this.c.width) return;
    this.shownAt = rig.t;
    NAMES.forEach((n, i) => { this.vals[i] = o[n] ?? 0; });
    if (TIMING.onTwos) {
      const v = n => this.vals[NAMES.indexOf(n)], set = (n, x) => { this.vals[NAMES.indexOf(n)] = x; };
      set('jaw', SNAP(v('jaw'), [0, 0.2, 0.42, 0.7])); set('round', SNAP(v('round'), [0, 1])); set('wide', SNAP(v('wide'), [0, 1])); set('teeth', SNAP(v('teeth'), [0, 1]));
    }

    if (dt > 1 / 45) this.slow++; else this.slow = Math.max(0, this.slow - 0.25);
    if (this.slow > 20 && this.scale > 0.45) { this.scale *= 0.85; this.slow = 0; }
    const w = Math.round(W * this.scale), h = Math.round(H * this.scale);
    if (this.c.width !== w || this.c.height !== h) { this.c.width = w; this.c.height = h; }
    this.target(w, h);

    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo); gl.viewport(0, 0, w, h);
    gl.clearBufferfv(gl.COLOR, 0, [0, 0, 0, 0]); gl.clearBufferfv(gl.COLOR, 1, [1000, 0, 0, 0]);
    gl.useProgram(this.scene);
    const U = this.U;
    gl.uniform2f(U('res'), w, h); gl.uniform1f(U('time'), rig.t); gl.uniform1fv(U('u'), this.vals);
    gl.uniform3fv(U('arm'), this.joints);
    gl.uniformMatrix3fv(U('Rh'), false, B.Rh); gl.uniformMatrix3fv(U('Rc'), false, B.Rc);
    gl.uniform3fv(U('H'), B.H); gl.uniform3fv(U('C'), B.C); gl.uniform3fv(U('NB'), B.NB); gl.uniform3fv(U('NT'), B.NT);
    gl.uniform3f(U('sw1'), this.sp.x * 0.5, this.sp.y * 0.3, 0); gl.uniform3f(U('sw2'), this.sp2.x * 0.5, this.sp2.y * 0.3, 0);
    gl.uniformMatrix3fv(U('hf'), false, B.hf); gl.uniform1fv(U('curl'), B.curl); gl.uniform1fv(U('spread'), B.spread);
    gl.uniform2f(U('view'), -this.K.shift, 0.62);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.ink);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.tex[0]);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, this.tex[1]);
    gl.uniform1i(gl.getUniformLocation(this.ink, 'color'), 0); gl.uniform1i(gl.getUniformLocation(this.ink, 'gbuf'), 1);
    gl.uniform2f(gl.getUniformLocation(this.ink, 'res'), w, h);
    gl.uniform1f(gl.getUniformLocation(this.ink, 'lineW'), Math.max(1, Math.min(w, h) / 620));
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    const oc = this.oc;
    if (this.ov.width !== W || this.ov.height !== H) { this.ov.width = W; this.ov.height = H; }
    oc.clearRect(0, 0, W, H);
    if (this.who === 'sol' && this.monitor) {           // the top screen shows the voice that is actually playing, behind the character
      this.wave.copyWithin(0, 1); this.wave[this.wave.length - 1] = ((o.energy || 0) + 0.012) * Math.sin(rig.t * 70);
      const g = this.room.getContext('2d'), m = this.monitor;
      g.save(); g.beginPath(); g.roundRect(m.x, m.y, m.w, m.h, 10 * Z); g.clip(); g.fillStyle = '#150f28'; g.fillRect(m.x, m.y, m.w, m.h);
      g.strokeStyle = '#8df5e6'; g.lineWidth = 2.5 * Z; g.shadowColor = '#7ef0e0'; g.shadowBlur = 12 * Z; g.beginPath();
      for (let i = 0; i < this.wave.length; i++) { const x = m.x + m.w * i / (this.wave.length - 1), y = m.y + m.h * 0.5 - this.wave[i] * m.h * 0.44; i ? g.lineTo(x, y) : g.moveTo(x, y); }
      g.stroke(); g.restore();
    }
    const wash = oc.createLinearGradient(0, 0, W * 0.7, H);
    wash.addColorStop(0, `rgba(${this.K.wash},.22)`); wash.addColorStop(0.5, `rgba(${this.K.wash},0)`); wash.addColorStop(1, 'rgba(0,0,10,.2)');
    if (!document.body.dataset.bg || document.body.dataset.bg === 'room') { oc.fillStyle = wash; oc.fillRect(0, 0, W, H); }
    drawFx(oc, rig, W / 2 + this.K.shift * Z * 160, H / 2 - 70 * Z, 400 * Z, '#ffe9a8');
  }
}
