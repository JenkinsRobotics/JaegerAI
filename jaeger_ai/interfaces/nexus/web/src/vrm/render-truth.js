// Truth: the standard blank humanoid (humanoid.js) in smooth white clay with a huge toothy grin, raymarched for
// Char3D and posed by truth-pose.js (kneels by default; leans, sways, claps, stands, sits). Fan study for a
// personal pack (Fullmetal Alchemist; rights not cleared).
// No eyes or nose: the grin is the whole face, so it carries the rig. The upper teeth row stays with the skull
// and the lower row rides the jaw, so speech parts them; corners curl up the cheeks to grin or droop to frown;
// mouthX lifts one corner for a smirk; "oo" narrows and opens the grin, "ee" stretches it.
import { humanoidGLSL } from './humanoid.js';
import { JOINTS } from './truth-pose.js';
export { TruthBody } from './truth-pose.js';
export const TRUTH = humanoidGLSL(JOINTS, 'TJ') + `
#define CAM (vec3(.02,.2,3.6)+J_cam)
#define CAMSHIFT vec2(0,-.45)                                                      // looking down a little, like the reference
#define FOCAL 5.
#define FLOOR -.55
#define BOUND 1.
#define SCENE_SCALE .4                                                                 // metres: about .4 of the other bodies' units
#define SHADOW_STRIDE .03                                                              // short strides: the raised leg's penumbra on the thigh stays smooth
#define SHADOW_FAR 1.6                                                                 // past the figure: stop, so short strides stay cheap
#define SHADOW_STEPS 96                                                                // thin limbs: finer shadow steps, or the penumbra bands
#define SHADOW_K 2.5                                                                   // soft clay shadows: fingers blur into one shadow, as in the sculpt
#define MARCH_STEPS 200                                                                // rays graze the legs lying along the floor
#define ENV_LOW vec3(.1,.1,.11)                                                         // dim fill, so the form shades like the reference
#define ENV_HIGH vec3(.62,.62,.64)
#define RIM (vec3(.85,.88,.95)*.55+tint*.2)
const float HK=.235;                                                                      // the head is drawn in head heights; HK makes them metres
const vec3 SKULL=vec3(.39,.5,.45);
vec3 background(vec2 px){
  float v=smoothstep(1.6,.1,length(px*vec2(.8,.7)-vec2(0,-.05)));                      // black, as in the reference, with a faint glow behind
  float smoke=noise(vec3(px*2.2,time*.07))*.6+noise(vec3(px*5.,time*.11))*.3;
  return vec3(.004)*v*v*(.7+.3*smoke)+tint*.002;
}
vec3 toBody(vec3 p){ p.y-=FLOOR; p.xz*=rot(yaw*.1); return p; }
// Head space, in head heights: pivot at the top of the neck, turned by the pose (J_turn: roll, pitch, yaw) and the rig.
vec3 toHead(vec3 p){
  p=toBody(p)-J_head;
  vec3 a=J_turn;
  p.xz*=rot(yaw*.5+gazeX*.25+a.z); p.yz*=rot(pitch*.4-gazeY*.15+a.y); p.xy*=rot(roll*.4+tilt*.1+a.x);
  return p/HK-vec3(0,.43,.06);
}
// The grin, in 2D on the face. top/bot: the mouth's outline at this x; tu/tl: heights of the two teeth rows.
float W_(){ return .305*(1.+max(smile,0.)*.1+wide*.12-round*.38+jaw*.04); }
float grin(vec2 q,out float top,out float bot,out float tu,out float tl){
  float W=W_(),x=clamp(q.x/W,-1.,1.),arch=sqrt(max(1.-x*x,0.));
  float x8=x*x*x*x; x8*=x8;
  float c=-.3+(.12+.2*smile-.05*round)*x*x+(.06+.07*smile)*x8+mouthX*.06*x+jaw*.02;   // corners curl up the cheeks or droop; mouthX smirks
  float gap=(jaw*.14+round*.06)*(.3+.7*arch);                                // the jaw drops the lower row
  tu=.1*(.3+.7*arch)*(1.-.25*round); tl=tu*.8;
  top=c+tu+gap*.2; bot=c-tl-gap*.8;
  return max(abs(q.x)-W,max(q.y-top,bot-q.y)*.7);
}
// id: 1 skin 3 mouth 5 teeth
vec2 map(vec3 p0){
  vec3 h=toHead(p0);
  float hd=ell(h,SKULL);
  hd=smin(hd,ell(h-vec3(0,-.2-jaw*.1,.07),vec3(.29,.26,.33)),.14);                         // the jaw: the chin drops as the mouth opens
  float top,bot,tu,tl,g=grin(h.xy,top,bot,tu,tl),front=.05-h.z;
  float cav=max(max(g,front),-(hd+.1));                                                   // the mouth: a recess .1 deep
  float carved=smax(hd,-cav,.012);
  vec2 res_=vec2(smin(humanoid(toBody(p0)),carved*HK,.02),-cav>hd+.004?3.:1.);
  float rows=max(h.y-(top-tu),(bot+tl)-h.y);                                              // upper row hangs, lower row rides the jaw
  float x=h.x/W_(),tooth=x*2.7*(1.+.45*abs(x)),row=h.y>(top-tu+bot+tl)*.5?(h.y-(top-tu))/tu:((bot+tl)-h.y)/tl;
  float bulge=.014*sqrt(SAT(sin(3.1416*fract(tooth))))*sqrt(SAT(sin(3.1416*SAT(1.-row))));   // each tooth rounded
  res_=opU(res_,vec2(max(max(hd+.03-bulge,-rows),max(g+.028,front))*HK,5.));
  return res_;
}
void material(float id,vec3 p,vec3 n,vec3 rd,inout Mat m){
  m.alb=vec3(.42); m.rough=.6; m.sss=.2;                                                  // matte grey-white clay, as in the reference
  if(id==3.){ m.alb=vec3(.02,.015,.015); m.sss=0.; m.rough=.9; }
  if(id==5.){
    vec3 h=toHead(p); float top,bot,tu,tl; grin(h.xy,top,bot,tu,tl);
    float x=h.x/W_(),tooth=x*2.7*(1.+.45*abs(x));                                          // big front teeth, narrower toward the corners
    float seam=.5-abs(fract(tooth)-.5);                                                    // 0 at the gap between teeth
    float gum=min(abs(h.y-(top-tu)),abs(h.y-(bot+tl)));                                   // where each row meets the dark gap
    m.alb=vec3(.62,.61,.6)*mix(.5,1.,smoothstep(.0,.13,seam))*mix(.55,1.,smoothstep(.0,.016,gum));
    m.rough=.3; m.sss=.12;
  }
}`;
