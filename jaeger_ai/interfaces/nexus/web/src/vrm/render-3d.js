// Tier 3. True 3D with no mesh or asset: raymarched signed-distance characters in a fragment shader.
// Every rig channel is a uniform, so "blendshapes" are continuous and cost nothing extra per expression.
// Four bodies share one chassis: a human bust (Maya), a humanoid robot (Rook), an astronaut bot (Pip), a box bot (Bo).
// ponytail: SDFs need a real GPU. For robot-grade hardware, map the same rig channels to glTF morph targets.
import { drawFx } from './rig.js';
import { TRUTH, TruthBody } from './render-truth.js';

export const NAMES = ['lidL', 'lidR', 'low', 'arc', 'squeeze', 'heart', 'pupil', 'browL', 'browR', 'tilt', 'gazeX', 'gazeY', 'jaw', 'wide', 'round', 'teeth', 'smile', 'mouthX', 'yaw', 'pitch', 'roll', 'lean', 'crouch', 'lift', 'blush', 'glow', 'sparkle', 'tear', 'droop', 'tintR', 'tintG', 'tintB', 'antX', 'antY', 'energy'];
const DEFINES = NAMES.map((n, i) => `#define ${n} u[${i}]`).join('\n');

export const PRELUDE = `#version 300 es
precision highp float;
uniform float uClear,uTurn,uZoom; uniform vec2 res; uniform float time; uniform float u[${NAMES.length}]; uniform vec3 arm[6];
out vec4 frag;
${DEFINES}
#define tint vec3(tintR,tintG,tintB)
#define SAT(x) clamp(x,0.,1.)
#define sL arm[0]
#define eL arm[1]
#define wL arm[2]
#define sR arm[3]
#define eR arm[4]
#define wR arm[5]
float smin(float a,float b,float k){float h=SAT(.5+.5*(b-a)/k);return mix(b,a,h)-k*h*(1.-h);}
float smax(float a,float b,float k){return -smin(-a,-b,k);}
float ell(vec3 p,vec3 r){float k0=length(p/r),k1=length(p/(r*r));return k0*(k0-1.)/max(k1,1e-4);}
float cap(vec3 p,vec3 a,vec3 b,float r){vec3 pa=p-a,ba=b-a;float h=SAT(dot(pa,ba)/dot(ba,ba));return length(pa-ba*h)-r;}
float cone(vec3 p,vec3 a,vec3 b,float ra,float rb){vec3 pa=p-a,ba=b-a;float h=SAT(dot(pa,ba)/dot(ba,ba));return length(pa-ba*h)-mix(ra,rb,h);}
float box(vec3 p,vec3 b,float r){vec3 q=abs(p)-b+r;return length(max(q,0.))+min(max(q.x,max(q.y,q.z)),0.)-r;}
float box2(vec2 p,vec2 b,float r){vec2 q=abs(p)-b+r;return length(max(q,0.))+min(max(q.x,q.y),0.)-r;}
struct Mat{vec3 alb;float metal;float rough;vec3 emis;float sss;};
vec3 envMap(vec3 r);
mat2 rot(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}
vec2 opU(vec2 a,vec2 b){return a.x<b.x?a:b;}
float hash(vec3 p){p=fract(p*.3183+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float noise(vec3 x){vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);
  return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
             mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float heartSdf(vec2 p){
  p.y+=.2; p.x=abs(p.x);
  if(p.y+p.x>1.) return length(p-vec2(.25,.75))-.3536;
  vec2 a=p-vec2(0,1),b=p-.5*max(p.x+p.y,0.);
  return sqrt(min(dot(a,a),dot(b,b)))*sign(p.x-p.y);
}
// One LED eye on a screen, in 2D: lids, sad/angry slant and ^ ^ all cut the same shape. sq: 0 oval, 1 rounded square.
float ledEye(vec2 q,float side,float lid,vec2 r,float sq){
  if(heart>.5) return heartSdf(q/(max(r.x,r.y)*1.05))*max(r.x,r.y)*1.05;
  if(squeeze>.5){ vec2 c=vec2(abs(q.y)*.9-(q.x*side)*-.0,q.y); float dir=-side; float y=abs(q.y); return abs(q.x*dir-(y-r.y*.35)*.9)-r.x*.12+max(y-r.y*.62,0.); }
  float wide_=max(lid-1.,0.),l=SAT(lid);
  vec2 R=r*vec2(1.-wide_*.12,1.+wide_*.75);
  float shape=sq>.5?box2(q,R,min(R.x,R.y)*.42):(length(q/R)-1.)*min(R.x,R.y);
  float x=q.x/R.x;
  float top=mix(-R.y*.08,R.y*1.1,l)-tilt*.5*R.y*(x*side)*(1.-arc)+min(tilt,0.)*.3*R.y;
  float bot=mix(-R.y*.14,-R.y*1.1,SAT(l*1.5))+R.y*(low*.65+arc*1.7)*(1.-x*x);
  if(arc>.3) top=max(top,R.y*1.1);
  return max(shape,max(q.y-top,bot-q.y));
}
// LED mouth: a stroke along the smile curve that swells into an open mouth as the jaw drops.
float ledMouth(vec2 q,float w){
  float W=w*(1.+wide*.35-round*.55+max(smile,0.)*.25);
  q.x-=mouthX*w*.4;
  float x=q.x/W,c=-smile*w*.42*(1.-x*x);
  float th=w*.09+jaw*w*.62*sqrt(SAT(1.-x*x))+round*w*.1;
  return max(abs(q.x)-W,abs(q.y-c+jaw*w*.3)-th);
}
`;

// Shared lighting and scene. Each body supplies map(), material(), and the constants below.
const LIGHTING = `
#ifndef SCENE_SCALE
#define SCENE_SCALE 1.   // a body built smaller (Truth, in metres) scales the shading probes with it
#endif
#ifndef SHADOW_STEPS
#define SHADOW_STEPS 22
#endif
#ifndef SHADOW_STRIDE
#define SHADOW_STRIDE (.35*SCENE_SCALE)   // longest shadow step: shorter keeps a far occluder's penumbra from banding
#endif
#ifndef SHADOW_FAR
#define SHADOW_FAR 5.   // a shadow ray this far out has cleared the body
#endif
#ifndef SHADOW_K
#define SHADOW_K 7.   // shadow hardness: lower is a softer penumbra
#endif
vec3 normal(vec3 p){
  const vec2 e=vec2(1.,-1.)*.0016*SCENE_SCALE;
  return normalize(e.xyy*map(p+e.xyy).x+e.yyx*map(p+e.yyx).x+e.yxy*map(p+e.yxy).x+e.xxx*map(p+e.xxx).x);
}
float softShadow(vec3 ro,vec3 rd){
  float res_=1.,t=.03*SCENE_SCALE;
  for(int i=0;i<SHADOW_STEPS;i++){
    float h=map(ro+rd*t).x;
    res_=min(res_,SHADOW_K*h/t);
    t+=clamp(h,.025*SCENE_SCALE,SHADOW_STRIDE);
    if(res_<.01||t>SHADOW_FAR)break;
  }
  return SAT(res_);
}
float occl(vec3 p,vec3 n){
  float a=0.,s=1.;
  for(int i=1;i<=4;i++){float h=(.05*float(i)*float(i)*.5+.02)*SCENE_SCALE;a+=(h-map(p+n*h).x)/SCENE_SCALE*s;s*=.6;}
  return SAT(1.-a*2.2);
}
vec3 envMap(vec3 r){
  float h=r.y*.5+.5;
  vec3 c=mix(ENV_LOW,ENV_HIGH,smoothstep(.0,1.,h));
  c+=smoothstep(.975,.998,dot(r,normalize(vec3(-.45,.7,.6))))*vec3(5.);      // softbox
  c+=smoothstep(.9,.99,dot(r,normalize(vec3(.8,.1,-.3))))*RIM*1.5;           // kicker
  return c;
}
vec3 surface(Mat m,vec3 p,vec3 n,vec3 rd,float ao,float sh){
  vec3 L=normalize(vec3(-.45,.75,.65)),V=-rd,H=normalize(L+V);
  float nl=dot(n,L);
  float wrap=SAT((nl+m.sss*.5)/(1.+m.sss*.5));
  vec3 dif=wrap*sh*vec3(1.,.97,.93)*1.15;
  // light bleeding through skin: warm where the shadow begins
  dif+=m.sss*vec3(.42,.14,.1)*smoothstep(-.55,.1,nl)*(1.-smoothstep(.1,.6,nl))*mix(.6,1.,sh);
  vec3 amb=mix(ENV_LOW*1.1+.06,ENV_HIGH*.55,n.y*.5+.5)*ao;
  amb+=RIM*.1*SAT(dot(n,normalize(vec3(.8,.1,-.3))))*ao;
  float nh=max(dot(n,H),0.),nv=max(dot(n,V),.001);
  float a=m.rough*m.rough,a2=a*a;
  float d=a2/(3.14*pow(nh*nh*(a2-1.)+1.,2.));
  vec3 F0=mix(vec3(.04),m.alb,m.metal);
  float fres=pow(1.-nv,5.);
  vec3 spec=F0*d*.25*sh*max(nl,0.)*3.;
  vec3 refl=envMap(reflect(rd,n))*(F0+(1.-F0)*fres)*(1.-m.rough*.72)*mix(.45,1.,ao);
  vec3 col=m.alb*(1.-m.metal)*(dif+amb)+spec+refl+m.emis;
  col+=pow(1.-nv,3.)*RIM*.22*ao;
  return col;
}
void main(){
  vec2 px=(gl_FragCoord.xy-.5*res)/min(res.x,res.y)*2.;
  vec3 ro=CAM,rd=normalize(vec3(px*uZoom+CAMSHIFT,-FOCAL));
  ro.xz*=rot(uTurn); rd.xz*=rot(uTurn);                                    // the view buttons orbit the camera round the character
  vec3 col=background(px);
  float tFloor=rd.y<0.?(FLOOR-ro.y)/rd.y:1e9;
  float t=max(length(ro.xz)-BOUND,.01),id=0.;
  bool hit=false;
  float tEnd=length(ro.xz)+BOUND;
#ifndef MARCH_STEPS
#define MARCH_STEPS 110
#endif
  for(int i=0;i<MARCH_STEPS;i++){   // a body with long grazing surfaces (limbs on the floor) asks for more
    vec2 h=map(ro+rd*t);
    if(h.x<.001*SCENE_SCALE*t){hit=true;id=h.y;break;}
    t+=h.x*.86;
    if(t>tEnd)break;
  }
  if(hit&&t<tFloor){
    vec3 p=ro+rd*t,n=normal(p);
    Mat m=Mat(vec3(.8),0.,.5,vec3(0),0.);
    material(id,p,n,rd,m);
    float ao=occl(p,n);
    float sh=softShadow(p+n*.02*SCENE_SCALE,normalize(vec3(-.45,.75,.65)));
    col=surface(m,p,n,rd,ao,sh);
  }else if(tFloor<40.){
    vec3 p=ro+rd*tFloor;
    float sh=softShadow(p+vec3(0,.02*SCENE_SCALE,0),normalize(vec3(-.45,.75,.65)));
    float cont=SAT(map(p+vec3(0,.12*SCENE_SCALE,0)).x/(.5*SCENE_SCALE));
    col*=mix(.62,1.,sh)*mix(.55,1.,sqrt(cont));
  }
  col*=1.-.2*dot(px*.6,px*.6);
  col=col*(2.51*col+.03)/(col*(2.43*col+.59)+.14);   // ACES
  frag=vec4(pow(SAT(col),vec3(.4545)),1.);
  if(uClear>.5&&!(hit&&t<tFloor))frag=vec4(0.);   // green screen or transparent: only the character
}`;

// --- Maya: a stylised human bust ---------------------------------------------------------
const HUMAN = `
#define CAM vec3(0,-.42,5.9)
#define CAMSHIFT vec2(0,0)
#define FOCAL 2.95
#define FLOOR -99.
#define BOUND 4.6
#define ENV_LOW vec3(.1,.08,.1)
#define ENV_HIGH vec3(.62,.58,.58)
#define RIM (vec3(.55,.68,1.)*.8+tint*.3)
const vec3 EYE=vec3(.285,.04,.555); const float ER=.178;
float skull(float x,float y){return -.14+.93*sqrt(max(.02,1.-x*x/.64-(y-.28)*(y-.28)/.81));}
vec3 background(vec2 px){
  vec3 c=mix(vec3(.2,.2,.26),vec3(.46,.42,.44),smoothstep(-1.1,1.2,px.y+px.x*.25));
  return c+tint*.05*smoothstep(1.5,.1,length(px-vec2(0,.25)));
}
vec3 toBody(vec3 p){ p.y-=lift*.05; p.z-=lean*.1; p.xz*=rot(yaw*.14); return p; }
vec3 toHead(vec3 p){
  p=toBody(p);
  p.y+=1.05; p.z+=.12;                         // pivot at the top of the neck
  p.xz*=rot(yaw*.6); p.yz*=rot(pitch*.42); p.xy*=rot(roll*.42);
  p.y-=1.05; p.z-=.12;
  return p;
}
float eyeOpen(vec3 q,float side,float lid){
  float x=q.x*side,l=SAT(lid);
  float ux=x/ER;
  float up=mix(-.025,ER*(.6-.34*ux*ux+.12*ux),l)+max(lid-1.,0.)*.11-tilt*(.05*ux)*(1.-arc)*step(.15,l)+min(tilt,0.)*.035;
  float dn=mix(-.03,ER*(-.5+.3*ux*ux+.05*ux)+low*.09*(1.-ux*ux),SAT(l*3.));
  float open=min(q.y-dn,up-q.y);
  return mix(open,-.03,max(arc,squeeze));
}
vec3 mouthSpace(vec3 p,out float mw,out float mh){
  float mx=p.x-mouthX*.09;
  vec3 m=p-vec3(mouthX*.09,-.5+smile*.015-jaw*.075,.77);
  m.y-=smile*.75*(mx*mx);
  mw=.175*(1.+wide*.26-round*.42+max(smile,0.)*.34+jaw*.07); mh=.003+jaw*.17+round*.03;
  return m;
}
// id: 1 skin 2 eye 3 cavity 4 tongue 5 teeth 6 brow 7 hair 8 shirt 9 lips
vec2 map(vec3 p0){
  vec3 p=toHead(p0);
  float hb=length(p-vec3(0,.05,0))-1.55;
  vec2 res_=vec2(hb,1.);
  if(hb<.6){
    float d=ell(p-vec3(0,.28,-.14),vec3(.8,.9,.92));                                    // cranium
    d=smin(d,ell(p-vec3(0,-.3,.16),vec3(.63,.72,.6)),.24);                              // face mass
    d=smin(d,ell(p-vec3(0,-.82-jaw*.09,.4),vec3(.27,.2,.24)),.26);                      // chin, drops with the jaw
    vec3 ax=vec3(abs(p.x),p.yz);
    d=smin(d,ell(ax-vec3(.4,-.26,.36),vec3(.2,.16,.2)),.26);                            // cheekbones
    d=smax(d,-ell(ax-vec3(.3,.05,.8),vec3(.19,.09,.08)),.12);                           // eye sockets
    d=smin(d,ell(ax-vec3(.26,.2,.6),vec3(.2,.05,.1)),.2);                                // soft brow bone
    d=smin(d,cone(p,vec3(0,.12,.78),vec3(0,-.14,.9),.05,.058),.1);                      // nose bridge
    d=smin(d,length(p-vec3(0,-.19,.91))-.07,.05);                                       // nose tip
    d=smin(d,ell(ax-vec3(.07,-.225,.83),vec3(.05,.04,.05)),.045);                       // nostril wing
    d=smin(d,ell(ax-vec3(.79,-.02,-.1),vec3(.05,.17,.11)),.03);                         // ear
    vec3 qL=p-vec3(-EYE.x,EYE.y,EYE.z),qR=p-EYE;
    // skin is cut away only inside the lid opening, so the eyeball sits behind the face, not on it
    d=smax(d,-max(eyeOpen(qL,-1.,lidL)*-1.,length(qL)-(ER+.04)),.012);
    d=smax(d,-max(eyeOpen(qR,1.,lidR)*-1.,length(qR)-(ER+.04)),.012);
    float lL=max(length(qL)-(ER+.012),-eyeOpen(qL,-1.,lidL)*-1.),lR=max(length(qR)-(ER+.012),-eyeOpen(qR,1.,lidR)*-1.);
    d=smin(d,min(lL,lR),.03);

    float mw,mh; vec3 m=mouthSpace(p,mw,mh);
    float lip=ell(m-vec3(0,mh+.018,.012),vec3(mw*1.02,.03,.07));
    lip=min(lip,ell(m-vec3(0,-mh-.026,.008),vec3(mw*.82,.04,.075)));
    d=smin(d,lip,.03);
    float cav=ell(m,vec3(mw*.92,mh+.006,.2));
    float pre=d;
    d=smax(d,-cav,.016);
    res_=vec2(d,lip<.012?9.:1.);
    if(cav<.1){
      res_=opU(res_,vec2(max(pre+.012,cav),3.));
      res_=opU(res_,vec2(max(ell(m-vec3(0,-mh*.68,-.04),vec3(mw*.66,mh*.42+.006,.12)),pre+.004),4.));
      res_=opU(res_,vec2(max(ell(m-vec3(0,mh*.72+.012,-.04),vec3(mw*.8,mh*.26+.018,.07)),pre+.006),5.));
    }
    res_=opU(res_,vec2(min(length(qL),length(qR))-ER,2.));
    for(int i=0;i<2;i++){
      float s=i==0?-1.:1.,by=i==0?browL:browR;
      vec3 a=vec3(s*.1,.235+by*.075+tilt*.065+min(tilt,0.)*.03,0.),c=vec3(s*.3,.3+by*.085,0.),b=vec3(s*.51,.2+by*.06-tilt*.04,0.);
      a.z=skull(a.x,a.y)+.075; c.z=skull(c.x,c.y)+.07; b.z=skull(b.x,b.y)+.03;
      res_=opU(res_,vec2(min(cone(p,a,c,.026,.022),cone(p,c,b,.022,.008)),6.));
    }
    // hair: a cap with the face cut out, a long bob behind the neck that sways, a side-swept fringe
    vec3 hp=p; float below=SAT(-(p.y-.1)*.7);
    hp.x-=antX*.16*below; hp.y-=antY*.04*below;
    float hair=ell(hp-vec3(0,.3,-.14),vec3(.855,.97,.97));
    hair=smin(hair,ell(hp-vec3(0,-.55,-.42),vec3(.88,1.2,.5)),.3);
    float faceCut=ell(p-vec3(0,-.14,.72),vec3(.6,.82,.62));
    hair=smax(hair,-faceCut,.03);
    for(int i=0;i<2;i++){                                                                   // curtain fringe from a centre part
      float s=i==0?-1.:1.;
      vec3 a=vec3(s*.03,.84,.5),c=vec3(s*.48,.5,.62),e=vec3(s*.7,-.1,.4);
      hair=smin(hair,min(cone(hp,a,c,.075,.085),cone(hp,c,e,.085,.04)),.1);
    }
    hair+=.004*sin(p.x*30.+p.y*6.);
    res_=opU(res_,vec2(hair,7.));
  }
  // neck and shoulders: follow the head at the top, stay with the body below
  vec3 b=toBody(p0);
  vec3 headBase=vec3(0,-.88,-.12); headBase.xz*=rot(-yaw*.5); headBase.x+=roll*-.2;
  float neck=cone(b,headBase,vec3(0,-1.6,-.22),.31,.37);
  float breathe=sin(time*1.7)*.012;
  vec3 s=b-vec3(0,-2.56+breathe,-.3);
  float torso=ell(s,vec3(1.7,.95,.82));
  torso=smin(torso,cap(b,vec3(-1.2,-1.88+breathe,-.3),vec3(1.2,-1.88+breathe,-.3),.3),.34);
  torso=smin(torso,cap(b,vec3(0,-1.5,-.3),vec3(0,-1.94,-.3),.42),.28);     // trapezius
  res_=opU(res_,vec2(smin(neck,torso,.14),1.));
  float shirt=torso-.012;
  shirt=smax(shirt,-(ell(b-vec3(0,-1.62,.0),vec3(.54,.3,.62))),.02);    // scoop neck, skin shows above it
  res_=opU(res_,vec2(shirt,8.));
  return res_;
}
vec3 eyeColor(vec3 p,vec3 n,vec3 rd){
  vec3 h=toHead(p);
  float side=h.x<0.?-1.:1.;
  vec3 q=normalize(h-vec3(side*EYE.x,EYE.y,EYE.z));
  vec3 a=normalize(vec3(gazeX*.42-side*.05,gazeY*.32-.03,1.));
  vec3 up=normalize(cross(vec3(1,0,0),a)),rt=cross(a,up);
  vec2 uv=vec2(dot(q,rt),dot(q,up));
  float front=dot(q,a),r=length(uv);
  vec3 col=vec3(.74,.71,.69)-vec3(.0,.08,.08)*smoothstep(.5,.95,r);     // sclera, slightly warm at the corners
  if(front>0.){
    float iR=.66;
    float ang=atan(uv.y,uv.x);
    float fib=.82+.18*sin(ang*31.+sin(ang*7.)*2.)*smoothstep(.16,.45,r);
    vec3 ir=mix(vec3(.34,.17,.05),vec3(.17,.09,.04),smoothstep(.2,.6,r))*fib*1.2;
    ir=mix(ir,ir*.15,smoothstep(.5,.67,r));
    ir*=.72+.5*SAT(.5-uv.y);
    float pup=.25*pupil;
    if(heart>.5){ float hd=heartSdf(uv*(3./(heart*.9))); ir=mix(vec3(1.,.12,.42),ir,smoothstep(-.02,.02,hd)); }
    else ir=mix(vec3(.004),ir,smoothstep(pup-.01,pup+.025,r));
    col=mix(ir,col,smoothstep(iR-.015,iR+.02,r));
  }
  vec3 refl=envMap(reflect(rd,n));
  float fr=.02+.3*pow(1.-max(dot(-rd,n),0.),5.);
  col=col*(.4+.75*SAT(-q.y*.9+.5))+refl*fr;                            // upper-lid shadow plus wet cornea
  col+=smoothstep(.09,.04,length(uv-vec2(-.2,.24)))*1.5;
  if(sparkle>.2){ vec2 g=abs(uv-vec2(.14,.14)); col+=sparkle*(.6+.4*sin(time*9.))*smoothstep(.025,.0,g.x*g.y*5.+length(g)*.1)*2.; }
  return col;
}
void material(float id,vec3 p,vec3 n,vec3 rd,inout Mat m){
  vec3 h=toHead(p);
  vec3 skin=vec3(.66,.38,.26);
  m.alb=skin; m.rough=.48; m.sss=.75;
  if(id==1.||id==9.){
    float cheek=0.;
    for(int s=-1;s<=1;s+=2) cheek=max(cheek,smoothstep(.34,.0,length((h-vec3(float(s)*.5,-.2,.68))*vec3(1.,1.3,1.))));
    m.alb=mix(m.alb,vec3(.76,.26,.24),cheek*(blush*.7+.12));
    m.alb=mix(m.alb,vec3(.78,.34,.26),smoothstep(.12,.02,length(h-vec3(0,-.19,.92)))*.3);   // warm nose tip
    vec3 qa=h-vec3(-EYE.x,EYE.y,EYE.z),qb=h-EYE;
    float rim=min(length(qa)-ER,length(qb)-ER);
    float op=max(SAT(eyeOpen(qa,-1.,lidL)*40.+1.)*step(length(qa),ER+.05),SAT(eyeOpen(qb,1.,lidR)*40.+1.)*step(length(qb),ER+.05));
    float upper=SAT(max(qa.y*step(length(qa),.3),qb.y*step(length(qb),.3))*7.);
    m.alb=mix(m.alb,vec3(.07,.045,.05),smoothstep(.012+.026*upper,.003,rim)*op*(1.-max(arc,squeeze)));  // lash line
    vec3 qq=h.x<0.?qa:qb;
    float x=qq.x/ER,yc=mix(-.035-.03*x*x,.06-.11*x*x,arc);
    float closed=max(arc,1.-smoothstep(.03,.2,h.x<0.?lidL:lidR));
    m.alb=mix(m.alb,vec3(.07,.045,.05),closed*smoothstep(.016,.004,abs(qq.y-yc))*step(abs(x),1.1)*step(length(qq),.3));
    m.alb=mix(m.alb,vec3(.8,.55,.5),smoothstep(.2,.3,length(qq))*smoothstep(.34,.3,length(qq))*.12*step(0.,qq.y));
  }
  if(id==9.){ m.alb=vec3(.46,.1,.11); m.rough=.42; m.sss=.5; }
  if(id==3.){ m.alb=vec3(.14,.02,.04); m.sss=0.; m.rough=.9; }
  if(id==4.){ m.alb=vec3(.85,.32,.33); m.sss=.3; m.rough=.4; }
  if(id==5.){ m.alb=vec3(1.,.98,.92); m.sss=.2; m.rough=.25; }
  if(id==6.){ m.alb=vec3(.07,.04,.03); m.sss=0.; m.rough=.8; }
  if(id==7.){
    float strand=.86+.14*sin(h.x*70.+sin(h.y*6.+h.x*3.)*2.)*sin(h.y*9.+h.x*22.);
    m.alb=vec3(.055,.024,.016)*strand; m.sss=.1; m.rough=.34;
    m.emis=vec3(.26,.12,.07)*.3*smoothstep(.2,.0,abs(h.y-.52+h.x*h.x*.28))*SAT(n.y+.5);   // the shine band
  }
  if(id==8.){ m.alb=vec3(.1,.17,.24); m.sss=.1; m.rough=.85; }
  if(id==2.){ m.alb=vec3(0); m.emis=eyeColor(p,n,rd); m.rough=1.; m.sss=0.; }
  if(tear>.25&&id==1.){
    for(int s=-1;s<=1;s+=2){ vec3 q=h-vec3(float(s)*.38,-.08-fract(time*.6+float(s)*.3)*.4,.8); float tr=smoothstep(.05,.02,length(q*vec3(1.,.6,1.)))*SAT(tear*2.); m.rough=mix(m.rough,.05,tr); m.alb=mix(m.alb,vec3(.7,.85,1.),tr*.6); }
  }
}`;

// --- Rook: an original humanoid robot, weathered armour and an LED visor ---------------------
const DROID = `
#define CAM vec3(0,.72,8.2)
#define CAMSHIFT vec2(0,0)
#define FOCAL 3.1
#define FLOOR -99.
#define BOUND 5.2
#define ENV_LOW vec3(.08,.07,.07)
#define ENV_HIGH vec3(.62,.58,.54)
#define RIM (vec3(1.,.52,.2)*1.2)
vec3 background(vec2 px){
  vec3 c=mix(vec3(.09,.09,.11),vec3(.5,.34,.24),smoothstep(-.7,1.3,px.y+.2*px.x));
  c+=vec3(.5,.28,.12)*.5*smoothstep(1.3,.0,length(px-vec2(.5,.9)));
  float dust=noise(vec3(px*3.,time*.05));
  return c*(.88+.24*dust)+tint*.05*smoothstep(1.4,.2,length(px-vec2(0,.6)));
}
vec3 toBody(vec3 p){ p.y-=lift*.09-crouch*.1; p.z-=lean*.14; p.xz*=rot(.1+yaw*.2); p.xy*=rot(roll*.05); return p; }
vec3 toHead(vec3 p){
  p=toBody(p); p-=vec3(0,1.28,.02);
  p.xz*=rot(yaw*.72); p.yz*=rot(pitch*.5); p.xy*=rot(roll*.52);
  p-=vec3(0,.66,.05);
  return p/1.24;
}
float limb(vec3 p,vec3 a,vec3 b,float ra,float rb,inout float joint){
  joint=min(joint,length(p-a)-ra*.82);
  return cone(p,mix(a,b,.08),mix(a,b,.92),ra,rb);
}
// id: 1 armour 2 screen 3 dark metal 4 stencil-free dark plate 5 antenna tip
vec2 hand(vec3 p,vec3 e,vec3 w){
  vec3 d=normalize(w-e),s=normalize(cross(d,vec3(0,0,1))),f=cross(s,d);
  vec3 q=vec3(dot(p-w,s),dot(p-w,d),dot(p-w,f));
  if(length(q-vec3(0,.2,0))>.62) return vec2(length(q-vec3(0,.2,0))-.5,3.);
  float palm=box(q-vec3(0,.13,0),vec3(.14,.14,.06),.05);
  float fing=1e3;
  for(int i=0;i<3;i++){
    float x=(float(i)-1.)*.1;
    fing=min(fing,cap(q,vec3(x,.26,0),vec3(x*1.5,.48,.05+abs(x)*.1),.033));
  }
  fing=min(fing,cap(q,vec3(.15,.1,.02),vec3(.27,.26,.07),.036));
  return opU(vec2(palm,1.),vec2(fing,3.));
}
vec2 map(vec3 p0){
  vec3 p=toHead(p0);
  vec2 res_=vec2(length(p-vec3(0,.3,-.1))-1.9,1.);
  if(res_.x<.6){
    // angular skull: a box with chamfers cut by planes
    float d=box(p-vec3(0,.04,-.04),vec3(.72,.46,.7),.13);
    d=smax(d,dot(p,normalize(vec3(0,.82,.57)))-.76,.03);                         // sloped forehead
    d=smax(d,dot(vec3(abs(p.x),p.yz),normalize(vec3(.72,0,.7)))-.92,.03);        // cheek chamfer
    // the visor is recessed into the face
    float slot=box(p-vec3(0,.05,.72),vec3(.66,.2,.16),.07);
    d=smax(d,-slot,.015);
    float screen=box(p-vec3(0,.05,.585),vec3(.64,.19,.02),.06);
    d=min(d,box(p-vec3(0,.33+(browL+browR)*.012,.62),vec3(.66,.045,.09),.03)-.004);   // brow plate
    res_=vec2(d,1.);
    res_=opU(res_,vec2(screen,2.));
    // mandible: a separate plate that drops when it talks
    vec3 mq=p-vec3(0,-.38,.02); mq.yz*=rot(jaw*.32); mq.y+=jaw*.05;
    res_=opU(res_,vec2(box(mq-vec3(0,-.11,.26),vec3(.5,.13,.42),.08),1.));
    res_=opU(res_,vec2(box(mq-vec3(0,-.06,.5),vec3(.36,.05,.2),.03),3.));
    res_=opU(res_,vec2(box(vec3(abs(p.x),p.yz)-vec3(.78,.02,-.1),vec3(.07,.2,.27),.04),3.));   // ear housing
    // twin antenna blades: spring in JS, flatten when sad or angry, perk when surprised
    float perk=(browL+browR)*.5-droop*.9;
    for(int i=0;i<2;i++){
      float s=i==0?-1.:1.;
      vec3 a=vec3(s*.8,.16,-.14),m_=a+vec3(s*.12,.45+perk*.12,-.1),t_=a+vec3(s*(.16+max(-perk,0.)*.5)+antX*.22,.98+perk*.42+antY*.16,-.34-max(-perk,0.)*.3);
      float b=min(cone(p,a,m_,.075,.05),cone(p,m_,t_,.05,.02));
      res_=opU(res_,vec2(b,1.));
      res_=opU(res_,vec2(length(p-t_)-.035,5.));
    }
    res_.x*=1.24;
  }
  vec3 b=toBody(p0);
  float breathe=sin(time*1.4)*.015;
  // neck: three pistons between head and shoulders
  vec3 nt=vec3(0,1.62,.05); nt.xz*=rot(-yaw*.2);
  float neck=cap(b,vec3(0,1.,0),nt,.13);
  neck=min(neck,cap(b,vec3(-.26,.95,-.05),vec3(-.2,1.56,-.02),.05));
  neck=min(neck,cap(b,vec3(.26,.95,-.05),vec3(.2,1.56,-.02),.05));
  res_=opU(res_,vec2(neck,3.));
  // torso: wide at the collar, narrow at the waist, layered plates over a dark frame
  vec3 c=b-vec3(0,.28+breathe,0);
  float k=1./(.62+SAT((c.y+.85)/1.7)*.56);
  vec3 ct=vec3(c.x*k,c.y,c.z);
  float frame=box(ct,vec3(.76,.8,.4),.16);
  res_=opU(res_,vec2(frame,3.));
  vec3 ax=vec3(abs(c.x),c.yz);
  float pec=box(ax-vec3(.42,.32,.36),vec3(.38,.3,.09),.07);
  pec=smax(pec,dot(ax,normalize(vec3(.5,-.1,.86)))-.72,.02);
  float ab=min(box(ax-vec3(.2,-.22,.33),vec3(.19,.13,.075),.04),box(ax-vec3(.18,-.54,.3),vec3(.16,.12,.075),.04));
  float collar=box(c-vec3(0,.84,.05),vec3(.46,.1,.3),.08);
  res_=opU(res_,vec2(min(min(pec,ab),collar),1.));
  res_=opU(res_,vec2(box(ax-vec3(.62,-.12,.2),vec3(.09,.38,.2),.05),1.));   // rib guards
  // waist and hips
  vec3 w=b-vec3(0,-.95,0);
  float rib=length(w.xz*vec2(1.,1.25))-.4-.012*sin(w.y*26.);
  rib=max(rib,abs(w.y)-.36);
  res_=opU(res_,vec2(rib,3.));
  res_=opU(res_,vec2(box(b-vec3(0,-1.38,0),vec3(.5,.18,.32),.09),1.));
  res_=opU(res_,vec2(min(cone(b,vec3(-.34,-1.5,0),vec3(-.4,-2.6,.04),.25,.19),cone(b,vec3(.34,-1.5,0),vec3(.4,-2.6,.04),.25,.19)),1.));
  // arms: dark upper arm, armoured forearm with an elbow guard, shoulder pauldrons
  float jointL=1e3,jointR=1e3;
  float ua=min(limb(b,sL,eL,.15,.125,jointL),limb(b,sR,eR,.15,.125,jointR));
  float fa=min(limb(b,eL,wL,.19,.12,jointL),limb(b,eR,wR,.19,.12,jointR));
  res_=opU(res_,vec2(ua,3.));
  res_=opU(res_,vec2(fa,1.));
  res_=opU(res_,vec2(min(jointL,jointR),3.));
  for(int i=0;i<2;i++){
    vec3 s=i==0?sL:sR,e=i==0?eL:eR;
    vec3 d=normalize(e-s);
    vec3 q=b-s-d*.04-vec3(0,.06,0);
    q.xy*=rot((i==0?1.:-1.)*.42);
    float pl=box(q,vec3(.33,.17,.32),.12);
    pl=min(pl,box(q-vec3(0,-.2,0),vec3(.29,.07,.27),.05));
    res_=opU(res_,vec2(pl,1.));
  }
  res_=opU(res_,hand(b,eL,wL));
  res_=opU(res_,hand(b,eR,wR));
  return res_;
}
float panelLines(vec3 q){
  float a=abs(fract(q.y*.9+.3)-.5)/.9,b=abs(fract(q.x*.8+.1)-.5)/.8;
  return smoothstep(.004,.012,min(a,b));
}
vec3 display(vec2 q){
  // a dot-matrix LED panel: the eye mask is sampled per dot, so every shape reads as pixels
  vec2 cell=vec2(.034);
  vec2 id_=floor(q/cell),c=(id_+.5)*cell,f=(q-c)/cell;
  vec2 g=vec2(gazeX*.1,gazeY*.05);
  float eyeL=ledEye(c-vec2(-.3,0)-g,-1.,lidL,vec2(.16,.13),.0);
  float eyeR=ledEye(c-vec2(.3,0)-g,1.,lidR,vec2(.16,.13),.0);
  float mask=step(min(eyeL,eyeR),.0);
  // brows on the same panel carry most of the feeling
  float bar=0.;
  for(int i=0;i<2;i++){
    float s=i==0?-1.:1.,by=i==0?browL:browR;
    float x=(c.x-s*.3)/.16;
    bar=max(bar,step(abs(x),1.)*step(abs(c.y-(.16+by*.02-tilt*.03-(x*s)*tilt*.03)),.012));
  }
  float pup=step(length(c-vec2(-.3,0)-g*1.8),.05*pupil)+step(length(c-vec2(.3,0)-g*1.8),.05*pupil);
  float dot_=smoothstep(.5,.34,length(f));
  vec3 col=tint*(mask*(1.-.85*pup)+bar*.6)*dot_*(.55+glow*.35);
  return col+tint*.012*dot_;   // unlit dots stay faintly visible
}
void material(float id,vec3 p,vec3 n,vec3 rd,inout Mat m){
  vec3 h=toHead(p),b=toBody(p);
  bool onHead=length(h-vec3(0,.05,0))<1.3;
  vec3 q=onHead?h:b;
  float scuff=noise(q*9.)*.6+noise(q*31.)*.4;
  float big=noise(q*2.5+3.);
  if(id==1.){
    m.alb=vec3(.44,.42,.37)*(.82+.28*scuff);
    m.rough=.5+.2*scuff; m.metal=.05;
    // worn edges reveal metal
    float wear=smoothstep(.6,.76,scuff*.55+big*.5);
    m.alb=mix(m.alb,vec3(.16,.155,.15),wear*.85); m.metal=mix(m.metal,.8,wear); m.rough=mix(m.rough,.35,wear);
    m.alb*=.35+.65*panelLines(q);
    // hazard block on the skull and chest, its own design language
    bool stripe=onHead?(abs(h.x)>.46&&h.y>-.34&&h.y<-.2&&h.z>.1):(abs(abs(b.x)-.52)<.14&&b.y>.5&&b.y<.86&&b.z>.1);
    if(stripe) m.alb=mix(vec3(.95,.34,.06),m.alb,wear*.7);
        if(!onHead&&b.z>.2) m.emis+=tint*(.5+energy*1.5)*smoothstep(.09,.06,length(b.xy-vec2(0,.26)));
  }
  if(id==3.){ m.alb=vec3(.13,.13,.14)*(.8+.4*scuff); m.metal=.85; m.rough=.34+.15*scuff; }
  if(id==5.){ m.alb=vec3(0); m.emis=tint*(1.+glow+energy); }
  if(id==2.){
    m.alb=vec3(.008); m.metal=0.; m.rough=.12;
    m.emis=display(h.xy-vec2(0,.05));
    m.emis+=tint*.8*smoothstep(.05,.0,abs(h.y+.09))*step(abs(h.x),.05+energy*.35)*0.;
  }
  if(tear>.3&&id==2.){ float f=fract(time*.8); for(int s=-1;s<=1;s+=2) m.emis+=vec3(.3,.6,1.)*smoothstep(.03,.015,length(h.xy-vec2(float(s)*.34,-.08-f*.12)))*SAT(tear*1.5); }
}`;

// --- Pip: a glossy little astronaut bot ----------------------------------------------------
const ASTRO = `
#define CAM vec3(0,-.72,9.4)
#define CAMSHIFT vec2(0,0)
#define FOCAL 3.
#define FLOOR -2.88
#define BOUND 5.
#define ENV_LOW vec3(.62,.66,.74)
#define ENV_HIGH vec3(1.05,1.06,1.1)
#define RIM (vec3(.6,.8,1.)*.35)
vec3 background(vec2 px){
  vec3 c=mix(vec3(.86,.89,.94),vec3(1.02,1.03,1.05),smoothstep(-1.,.4,px.y));
  return c+tint*.05*smoothstep(1.2,.1,length(px-vec2(0,.5)));
}
vec3 toBody(vec3 p){ p.y-=lift*.3-crouch*.2; p.z-=lean*.15; p.xz*=rot(.1+yaw*.25); p.xy*=rot(roll*.1); return p; }
vec3 toHead(vec3 p){
  p=toBody(p); p-=vec3(0,.1,0);
  p.xz*=rot(yaw*.62); p.yz*=rot(pitch*.42); p.xy*=rot(roll*.45);
  p-=vec3(0,.85,0);
  return p;
}
// id: 1 white 2 visor 3 blue trim 4 glow bar
vec2 map(vec3 p0){
  vec3 p=toHead(p0);
  vec2 res_=vec2(length(p)-1.75,1.);
  if(res_.x<.6){
    float head=ell(p,vec3(1.08,.96,.94));
    vec3 ax=vec3(abs(p.x),p.yz);
    float cup=cone(ax,vec3(1.,.0,0),vec3(1.2,.0,0),.42,.3);
    float ring=max(abs(cone(ax,vec3(.98,.0,0),vec3(1.2,.0,0),.44,.32))-.012,ax.x-1.08);
    float visor=max(ell(p,vec3(1.1,.98,.965)),box2(p.xy-vec2(0,.03),vec2(.82,.6),.34));
    visor=max(visor,-p.z);
    res_=vec2(smin(head,cup,.03),1.);
    res_=opU(res_,vec2(visor,2.));
    res_=opU(res_,vec2(ring,3.));
    for(int i=0;i<2;i++){
      float s=i==0?-1.:1.;
      vec3 a=vec3(s*1.02,.34,0),t=vec3(s*1.04+antX*.18,1.06-droop*.28+antY*.1,-.03);
      res_=opU(res_,vec2(cone(p,a,t,.08,.042),1.));
      res_=opU(res_,vec2(length(p-t)-.075,1.));
    }
  }
  vec3 b=toBody(p0);
  // torso: egg with a neck
  float torso=ell(b-vec3(0,-.72,0),vec3(.72,.8,.56));
  torso=smin(torso,cap(b,vec3(0,.05,0),vec3(0,.2,0),.2),.14);
  res_=opU(res_,vec2(torso,1.));
  // jointed limbs
  for(int i=0;i<2;i++){
    float s=i==0?-1.:1.;
    vec3 S=i==0?sL:sR,E=i==0?eL:eR,W=i==0?wL:wR;
    res_=opU(res_,vec2(min(cone(b,S,E,.17,.145),cone(b,E,W,.145,.13)),1.));
    float jo=min(length(b-E)-.158,length(b-S)-.18);
    res_=opU(res_,vec2(jo,3.));
    // mitt with four soft fingers
    vec3 d=normalize(W-E),sd=normalize(cross(d,vec3(0,0,1))),f=cross(sd,d);
    vec3 q=vec3(dot(b-W,sd),dot(b-W,d),dot(b-W,f));
    float palm=ell(q-vec3(0,.17,0),vec3(.2,.21,.12));
    float spread=.65+wave_amt*.6;
    for(int j=0;j<4;j++){
      float x=(float(j)-1.5);
      palm=smin(palm,cap(q,vec3(x*.075,.28,0),vec3(x*.11*spread,.5-abs(x)*.03,.02),.058),.03);
    }
    palm=smin(palm,cap(q,vec3(-s*.14,.13,.03),vec3(-s*.3,.3,.06),.06),.04);
    res_=opU(res_,vec2(palm,1.));
    // legs and boots
    vec3 H=vec3(s*.3,-1.38,0),K=vec3(s*.32,-1.92,.02),A=vec3(s*.32,-2.44,.02);
    res_=opU(res_,vec2(min(cone(b,H,K,.2,.17),cone(b,K,A,.17,.15)),1.));
    res_=opU(res_,vec2(length(b-K)-.178,3.));
    vec3 ft=b-vec3(s*.34,-2.64,.14);
    float boot=box(ft,vec3(.25,.18,.38),.16);
    res_=opU(res_,vec2(boot,ft.y<-.12?3.:1.));
  }
  return res_;
}
void material(float id,vec3 p,vec3 n,vec3 rd,inout Mat m){
  vec3 h=toHead(p),b=toBody(p);
  m.alb=vec3(.93,.94,.96); m.rough=.26; m.metal=0.;
  if(id==1.&&length(h)>1.3){
    float y=b.y;
    float seam=smoothstep(.022,.008,abs(y+.86+b.x*b.x*.12))*step(y,-.3)*step(-1.45,y)*step(length(b.xz*vec2(1.,1.25)),.85);
    if(abs(b.x)<.8) m.alb=mix(m.alb,vec3(.42,.57,.86),seam);
    // chest light
    float bar=box2(b.xy-vec2(0,-.2),vec2(.2,.024),.02);
    if(b.z>0.) m.emis+=mix(vec3(.3,.95,1.),tint,.35)*smoothstep(.015,.0,bar)*(1.4+energy*2.);
  }
  if(id==3.){ m.alb=vec3(.42,.57,.86); m.rough=.3; }
  if(id==2.){
    m.alb=vec3(.008); m.rough=.07;
    vec2 q=h.xy-vec2(0,.05);
    vec2 g=vec2(gazeX*.08,gazeY*.06);
    float e=min(ledEye(q-vec2(-.34,.12)-g,-1.,lidL,vec2(.17,.235),0.),ledEye(q-vec2(.34,.12)-g,1.,lidR,vec2(.17,.235),0.));
    float mo=ledMouth(q-vec2(0,-.27)-g*.5,.25);
    vec3 glowC=mix(vec3(.25,.95,1.),tint,.82);
    float sdf=min(e,mo);
    m.emis=glowC*(smoothstep(.006,-.006,sdf)*(.62+glow*.14)+.12*smoothstep(.1,.0,sdf));
    m.emis+=vec3(1.)*sparkle*smoothstep(.03,.0,length(q-vec2(-.4,.23)-g))+vec3(1.)*sparkle*smoothstep(.03,.0,length(q-vec2(.28,.23)-g));
    if(blush>.05){ for(int s=-1;s<=1;s+=2) m.emis+=vec3(1.,.3,.5)*blush*.55*smoothstep(.13,.0,length((q-vec2(float(s)*.56,-.12))*vec2(1.,1.6))); }
  }
}`;

// --- Bo: a small box-headed bot and a cactus -----------------------------------------------
const CUBE = `
#define CAM vec3(0,-.25,8.)
#define CAMSHIFT vec2(.1,.06)
#define FOCAL 3.
#define FLOOR -1.72
#define BOUND 5.
#define ENV_LOW vec3(.42,.45,.5)
#define ENV_HIGH vec3(.95,.97,1.)
#define RIM (vec3(.6,.7,.9)*.25)
vec3 background(vec2 px){ return mix(vec3(.72,.76,.82),vec3(.5,.54,.6),smoothstep(-.5,1.,px.y)); }
vec3 toBody(vec3 p){ p.y-=lift*.34-crouch*.2; p.z-=lean*.16; p.xz*=rot(.42+yaw*.3); p.xy*=rot(roll*.12); return p; }
vec3 toHead(vec3 p){
  p=toBody(p); p-=vec3(0,-.72,0);
  p.xz*=rot(yaw*.42); p.yz*=rot(pitch*.36); p.xy*=rot(roll*.32);
  p-=vec3(0,1.06,0);
  return p;
}
// id: 1 grey shell 2 screen 3 dark 4 cactus 5 stone
vec2 map(vec3 p0){
  vec3 p=toHead(p0);
  vec2 res_=vec2(length(p)-1.75,1.);
  if(res_.x<.6){
    float shell=box(p-vec3(0,0,-.08),vec3(1.06,.86,.9),.42);
    shell=smin(shell,ell(p-vec3(0,0,-.72),vec3(.86,.72,.44)),.1);
    float recess=box(p-vec3(0,.0,.88),vec3(.8,.62,.1),.28);
    shell=smax(shell,-recess,.05);
    res_=vec2(shell,1.);
    res_=opU(res_,vec2(box(p-vec3(0,0,.8),vec3(.79,.61,.04),.27),2.));
    res_=opU(res_,vec2(box(p-vec3(1.08,.05,-.1),vec3(.06,.26,.22),.05),1.));
  }
  vec3 b=toBody(p0);
  float belly=ell(b-vec3(0,-1.04,0),vec3(.4,.36,.34));
  res_=opU(res_,vec2(smin(belly,cap(b,vec3(0,-.5,0),vec3(0,-.9,0),.2),.12),1.));
  for(int i=0;i<2;i++){
    float s=i==0?-1.:1.;
    vec3 S=i==0?sL:sR,E=i==0?eL:eR,W=i==0?wL:wR;
    res_=opU(res_,vec2(min(cone(b,S,E,.1,.09),cone(b,E,W,.09,.1)),1.));
    res_=opU(res_,vec2(smin(cap(b,vec3(s*.17,-1.2,0),vec3(s*.17,-1.5,.0),.11),box(b-vec3(s*.18,-1.6,.07),vec3(.13,.09,.2),.08),.05),1.));
  }
  // set dressing: only the cactus and stones are outside the body's bound
  vec3 c=p0-vec3(1.72,-1.72,.9);
  float cb=length(c-vec3(0,.3,0))-.65;
  if(cb<.6){
    float cact=cap(c,vec3(0,0,0),vec3(0,.54,0),.078);
    cact=smin(cact,min(cap(c,vec3(0,.2,0),vec3(.17,.26,0),.046),cap(c,vec3(.17,.26,0),vec3(.17,.42,0),.046)),.02);
    cact=smin(cact,min(cap(c,vec3(0,.28,0),vec3(-.15,.32,0),.042),cap(c,vec3(-.15,.32,0),vec3(-.15,.46,0),.042)),.02);
    res_=opU(res_,vec2(cact,4.));
    res_=opU(res_,vec2(ell(c-vec3(-.36,.03,.03),vec3(.09,.05,.07)),5.));
    res_=opU(res_,vec2(ell(c-vec3(-.22,.02,.1),vec3(.04,.03,.04)),5.));
  } else res_=opU(res_,vec2(cb,5.));
  return res_;
}
void material(float id,vec3 p,vec3 n,vec3 rd,inout Mat m){
  vec3 h=toHead(p);
  m.alb=vec3(.1,.105,.11); m.rough=.5;
  if(id==4.){ m.alb=vec3(.2,.5,.2)*(.8+.3*sin(atan(p.x-1.72,p.z-.9)*14.)); m.rough=.6; }
  if(id==5.){ m.alb=vec3(.8,.8,.78); m.rough=.8; }
  if(id==2.){
    m.alb=vec3(.012); m.rough=.14;
    vec2 q=h.xy;
    vec2 g=vec2(gazeX*.12,gazeY*.08);
    float e=min(ledEye(q-vec2(-.22,.06)-g,-1.,lidL,vec2(.17,.2),1.),ledEye(q-vec2(.22,.06)-g,1.,lidR,vec2(.17,.2),1.));
    float mo=(jaw>.03||abs(smile)>.3)?ledMouth(q-vec2(0,-.3)-g*.5,.13):1.;
    float sdf=min(e,mo);
    vec3 c=mix(vec3(1.),tint,.12);
    m.emis=c*smoothstep(.006,-.006,sdf)*(1.5+glow*.4)+c*.03*smoothstep(.1,.0,sdf);
    if(blush>.05){ for(int s=-1;s<=1;s+=2) m.emis+=vec3(1.,.4,.55)*blush*.5*smoothstep(.1,.0,length((q-vec2(float(s)*.5,-.15))*vec2(1.,1.6))); }
  }
}`;

// Shoulder, arm lengths and how far each body's arms move; forearm reach is computed here, not in the shader.
const BODIES = {
  human: { src: HUMAN },
  truth: { src: TRUTH, skeleton: () => new TruthBody() },   // posed from a joint skeleton (TJ), not just arms
  droid: { src: DROID, shoulder: [1.12, 1.02, 0], l1: 0.9, l2: 0.88, rest: 0.14, baseF: 0.26 },
  astro: { src: ASTRO, shoulder: [0.78, -0.3, 0], l1: 0.5, l2: 0.5, rest: 0.2, baseF: 0.22 },
  cube: { src: CUBE, shoulder: [0.32, -0.86, 0], l1: 0.2, l2: 0.22, rest: 0.6, baseF: 0.2 },
};

export const VS = `#version 300 es
void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0,1);}`;

export class Char3D {
  constructor(canvas, overlay, kind) {
    this.c = canvas; this.ov = overlay; this.oc = overlay.getContext('2d'); this.kind = kind; this.body = BODIES[kind];
    const gl = canvas.getContext('webgl2', { antialias: false, powerPreference: 'high-performance', preserveDrawingBuffer: true });
    this.gl = gl;
    if (!gl) { this.error = 'WebGL2 unavailable'; return; }
    const sh = (type, src) => {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { this.error = gl.getShaderInfoLog(s); console.error(kind, this.error); }
      return s;
    };
    const pr = gl.createProgram();
    const src = PRELUDE + '#define wave_amt 1.\n' + this.body.src + LIGHTING;
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, src));
    gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { this.error = gl.getProgramInfoLog(pr); console.error(kind, this.error); return; }
    gl.useProgram(pr); this.pr = pr;
    this.loc = { res: gl.getUniformLocation(pr, 'res'), time: gl.getUniformLocation(pr, 'time'), u: gl.getUniformLocation(pr, 'u'), arm: gl.getUniformLocation(pr, 'arm') };
    this.vals = new Float32Array(NAMES.length); this.joints = new Float32Array(18);
    this.turnTo = 0; this.turn = 0; this.fullLock = false; this.zoom = 1;   // the view buttons: F ¾ S B and Full
    this.skel = this.body.skeleton?.(); this.poses = this.skel?.poses; this.loc.TJ = gl.getUniformLocation(pr, 'TJ'); this.t = 0;
    gl.bindVertexArray(gl.createVertexArray());
    this.ant = { x: 0, y: 0, vx: 0, vy: 0, py: 0, pl: 0 };
    this.scale = 1; this.slow = 0;
    this.arms = [[0, 0, 0, 0], [0, 0, 0, 0]];   // upper-arm angle and velocity, forearm angle and velocity, with follow-through
  }

  pose(name) { this.skel?.play(name, this.t); }   // a body move: kneel, sit, stand, lean, sway, clap

  // Forward kinematics for both arms: a pose from the rig, settled by a spring so hands lag the body.
  solveArms(o, t, dt) {
    const B = this.body;
    if (!B.shoulder) return;
    [-1, 1].forEach((side, i) => {
      const a = this.arms[i], flip = i === 0 ? 1 : -1;
      const wave = side > 0 ? o.wave : 0;
      const gestic = o.hand * (side > 0 ? 0.9 : 0.55) + 0.05 * Math.sin(t * 1.3 + i);
      const upT = (B.rest + o.shrug * 0.5 + gestic * 0.3) * (1 - wave) + wave * 1.72;
      const foreT = (B.baseF + o.shrug * 1.5 + gestic * 1) * (1 - wave) + wave * (1.15 + 0.42 * Math.sin(t * 10));
      const K = 90, C = 2 * 0.62 * Math.sqrt(K);
      a[1] += (K * (upT - a[0]) - C * a[1]) * dt; a[0] += a[1] * dt;
      a[3] += (K * 1.6 * (foreT - a[2]) - C * 1.3 * a[3]) * dt; a[2] += a[3] * dt;
      const S = [side * B.shoulder[0], B.shoulder[1] + o.shrug * B.l1 * 0.2, B.shoulder[2]];
      const th = a[0], ph = a[0] + a[2], fz = (o.hand * 0.4 + 0.12) * (1 - wave);
      const E = [S[0] + side * Math.sin(th) * B.l1, S[1] - Math.cos(th) * B.l1, S[2] + 0.06 * B.l1];
      const W = [E[0] + side * Math.sin(ph) * B.l2, E[1] - Math.cos(ph) * B.l2, E[2] + fz * B.l2];
      this.joints.set([...S, ...E, ...W], i * 9);
      void flip;
    });
  }

  draw(rig, W, H, dt) {
    const gl = this.gl;
    if (!gl || !this.loc) return;
    const o = rig.out, a = this.ant, step = Math.max(dt, 1 / 240);
    const y = o.yaw + o.roll, l = o.lift - o.crouch;
    a.vx += (-110 * a.x - 7 * a.vx - (y - a.py) / step * 12) * dt; a.x += a.vx * dt; a.py = y;
    a.vy += (-140 * a.y - 8 * a.vy - (l - a.pl) / step * 12) * dt; a.y += a.vy * dt; a.pl = l;
    const ext = { antX: a.x, antY: a.y };
    NAMES.forEach((n, i) => { this.vals[i] = ext[n] ?? o[n] ?? 0; });
    this.solveArms(o, rig.t, Math.min(dt, 1 / 30)); this.t = rig.t;

    // Hold 60fps by trading resolution, the one knob an SDF has.
    if (dt > 1 / 45) this.slow++; else this.slow = Math.max(0, this.slow - 0.25);
    if (this.slow > 20 && this.scale > 0.4) { this.scale *= 0.85; this.slow = 0; }
    const w = Math.round(W * this.scale), h = Math.round(H * this.scale);
    if (this.c.width !== w || this.c.height !== h) { this.c.width = w; this.c.height = h; gl.viewport(0, 0, w, h); }
    gl.uniform2f(this.loc.res, w, h);
    gl.uniform1f(this.loc.time, rig.t);
    this.turn += (this.turnTo - this.turn) * (1 - Math.exp(-dt * 6)); this.zoom += ((this.fullLock ? 1.35 : 1) - this.zoom) * (1 - Math.exp(-dt * 6));
    gl.uniform1f(gl.getUniformLocation(this.pr, 'uTurn'), this.turn); gl.uniform1f(gl.getUniformLocation(this.pr, 'uZoom'), this.zoom);
    gl.uniform1f(gl.getUniformLocation(this.pr, 'uClear'), document.body.dataset.bg && document.body.dataset.bg !== 'room' ? 1 : 0);
    gl.uniform1fv(this.loc.u, this.vals);
    gl.uniform3fv(this.loc.arm, this.joints);
    if (this.skel) gl.uniform3fv(this.loc.TJ, this.skel.step(o, rig.t, dt));
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    const oc = this.oc;
    if (this.ov.width !== W || this.ov.height !== H) { this.ov.width = W; this.ov.height = H; }
    oc.clearRect(0, 0, W, H);
    const S = Math.min(W, H);
    if (o.sweat > 0.2 || o.vein > 0.3) {
      oc.save(); oc.translate(W / 2 + S * 0.24, H / 2 - S * 0.28); oc.font = `${S * 0.08}px system-ui`; oc.textAlign = 'center';
      oc.globalAlpha = Math.min(1, Math.max(o.sweat, o.vein));
      oc.fillStyle = o.vein > 0.3 ? '#ff5560' : '#9fdcff'; oc.fillText(o.vein > 0.3 ? '#' : '💧', 0, 0); oc.restore();
    }
    drawFx(oc, rig, W / 2, H / 2 - S * 0.04, S * 0.42, this.kind === 'astro' ? '#3a6fb0' : '#fff5d0');
  }
}
