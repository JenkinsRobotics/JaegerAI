// Copied from JaegerAvatar app/web/kin/eyes.js (commit e041f0c), now Omni's own file.
// Momo's original eye performance. The shell never moves; every motion lives on its display.
export const FACE_MOODS=['neutral','joy','excited','love','sad','angry','surprised','scared','thinking','confused','shy','smug','sleepy','laughing','singing','listening'];
export const REACTIONS={blink:{label:'Double blink',icon:'◡',duration:.9},wink:{label:'Wink',icon:'◕',duration:1.8},sideeye:{label:'Side-eye',icon:'⌁',duration:2.8},sparkle:{label:'Sparkle',icon:'✧',duration:2.5},heart:{label:'Heartbeat',icon:'♡',duration:3},roll:{label:'Eye roll',icon:'↻',duration:2.4},peek:{label:'Peekaboo',icon:'◒',duration:3.2},doze:{label:'Doze off',icon:'☾',duration:4},groove:{label:'Eye dance',icon:'♫',duration:3},wake:{label:'Wake up',icon:'!',duration:1.8}};
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v)),ease=v=>{v=clamp(v);return v*v*(3-2*v);};
const pulse=(t,start,attack,hold,release)=>ease((t-start)/attack)*ease((start+attack+hold+release-t)/release);
const base={width:81,height:105,curve:0,tilt:0,asym:0,spread:178,x:0,y:0,heart:0,star:0,ring:0,chevron:0,blush:0,tear:0,brows:0,browSlope:0,browLift:0,blinkL:0,blinkR:0,red:190,green:255,blue:225,sparkles:0,question:0,dots:0,notes:0,sleep:0};
const moods={
 neutral:{},joy:{height:10,width:86,curve:38,y:8,sparkles:.12},
 excited:{height:103,width:94,star:.95,red:255,green:223,blue:156,sparkles:1},
 love:{heart:1,width:98,height:111,red:255,green:163,blue:193,blush:.7,sparkles:.35},
 sad:{height:43,width:77,tilt:.16,curve:-12,y:25,red:157,green:209,blue:255,tear:.85,brows:.65,browSlope:.3},
 angry:{height:45,width:92,tilt:-.25,red:255,green:154,blue:120,brows:1,browSlope:-.35,browLift:-8},
 surprised:{width:78,height:111,ring:.6,spread:183,y:-8,brows:.35,browLift:20},
 scared:{width:83,height:115,ring:.76,spread:185,red:198,green:221,blue:255,brows:.8,browSlope:.25,browLift:13},
 thinking:{height:69,width:70,asym:.37,x:32,y:-24,brows:.3,browLift:14},
 confused:{height:62,width:78,asym:-.6,tilt:.07,question:1,brows:.65,browSlope:.15,browLift:17},
 shy:{height:30,width:74,curve:13,y:25,x:-12,blush:1,red:225,green:232,blue:245},
 smug:{height:30,width:84,asym:.55,curve:11,tilt:-.06,x:-20,brows:.5,browLift:5},
 sleepy:{height:9,width:88,curve:-3,y:28,sleep:1,red:180,green:203,blue:228},
 laughing:{height:7,width:87,chevron:1,y:5,red:244,green:237,blue:184},
 singing:{height:22,width:83,curve:28,notes:1,red:183,green:240,blue:255},
 listening:{height:109,width:67,spread:165,brows:.22,browLift:11}
};
export function faceTarget(v,t){
 const index=Math.round(clamp(v.faceMood||0)*(FACE_MOODS.length-1)),name=FACE_MOODS[index];
 const p={...base,...moods[name]},energy=clamp(v.faceEnergy??1,.5,1.6);
 const age=v.faceMoodAge??3;
 const pop=Math.sin(age*14)*Math.exp(-age*7)*.07;
 p.width*=1+pop;p.height*=1-pop*.5;
 p.x+=(v.gazeX||0)*54;p.y-=(v.gazeY||0)*28;
 p.blinkL=clamp(Math.max(v.winkL||0,v.faceBlink||0));p.blinkR=clamp(Math.max(v.winkR||0,v.faceBlink||0));
 // Small, deliberate eye movements, with long holds instead of perpetual wobble.
 const looks=[[0,0],[.3,-.08],[0,0],[-.25,.06],[.1,.13],[0,0]],beat=(Number.isFinite(t)?Math.max(t,0):0)/4.7,j=Math.floor(beat)%looks.length,u=ease((beat%1)/.065),a=looks[(j+looks.length-1)%looks.length],b=looks[j];
 if(['neutral','listening','thinking'].includes(name)){p.x+=(a[0]+(b[0]-a[0])*u)*28;p.y+=(a[1]+(b[1]-a[1])*u)*20;}
 if(name==='love'){const beat=t%2.4,thump=pulse(beat,.1,.1,.02,.22)+.6*pulse(beat,.43,.09,.01,.18);p.width*=1+.055*thump;p.height*=1+.055*thump;}
 if(name==='scared')p.x+=Math.sin(t*29)*1.6;
 if(name==='laughing'){p.y+=Math.sin(t*9)*3;p.curve=5;}
 if(name==='singing'){p.y+=Math.sin(t*3)*3;p.asym=Math.sin(t*3)*.2;}
 if(name==='listening')p.height+=Math.sin(t*1.8)*2;
 const speech=clamp(v.jaw||0);p.width*=1+speech*.045;p.height*=1+speech*.08;
 const reactions=Object.keys(REACTIONS),code=Math.round((v.faceReaction||0)*reactions.length)-1,key=reactions[code];
 if(key){const duration=REACTIONS[key].duration,a=clamp(v.faceProgress||0)*duration,envelope=pulse(a,0,.18,Math.max(0,duration-.55),.37);
  if(key==='blink'){const blink=Math.max(pulse(a,.06,.07,.035,.14),pulse(a,.4,.07,.025,.16));p.blinkL=Math.max(p.blinkL,blink);p.blinkR=Math.max(p.blinkR,blink);}
  if(key==='wink'){p.height+=(95-p.height)*envelope*.9;p.blinkR=Math.max(p.blinkR,pulse(a,.24,.12,.7,.28));p.curve+=envelope*12;p.x-=envelope*9;}
  if(key==='sideeye'){p.x+=envelope*82;p.height*=1-.65*envelope;p.asym+=envelope*.25;}
  if(key==='sparkle'){p.star+=(1-p.star)*envelope;p.width+=envelope*12;p.height+=(105-p.height)*envelope;p.sparkles=Math.max(p.sparkles,envelope);p.red+=envelope*(255-p.red);p.blue+=envelope*(150-p.blue);}
  if(key==='heart'){p.heart+=(1-p.heart)*envelope;p.width+=envelope*12;p.height+=(110-p.height)*envelope;p.blush=Math.max(p.blush,envelope);p.red+=envelope*(255-p.red);p.green+=envelope*(163-p.green);p.blue+=envelope*(193-p.blue);}
  if(key==='roll'){const u=ease((a-.25)/1.6),theta=u*Math.PI*2;p.x+=Math.sin(theta)*70*envelope;p.y+=(Math.cos(theta)-1)*30*envelope;p.height*=1-.35*envelope;}
  if(key==='peek'){p.blinkL=Math.max(p.blinkL,pulse(a,.05,.14,.55,.75));p.blinkR=Math.max(p.blinkR,pulse(a,.05,.14,1.35,.65));p.x+=envelope*24;}
  if(key==='doze'){p.height*=1-.93*envelope;p.y+=envelope*16;p.sleep=Math.max(p.sleep,envelope);p.curve-=envelope*5;}
  if(key==='groove'){const wave=Math.sin(a*5)*envelope;p.y+=wave*11;p.asym+=wave*.45;p.curve+=envelope*12;p.notes=Math.max(p.notes,envelope);}
  if(key==='wake'){const blink=pulse(a,.04,.08,.13,.13),open=pulse(a,.37,.1,.5,.6);p.blinkL=Math.max(p.blinkL,blink);p.blinkR=Math.max(p.blinkR,blink);p.height+=(123-p.height)*open;p.width+=(91-p.width)*open;p.ring+=.3*open;}
 }
 p.x*=energy;p.y*=energy;p.curve*=.75+energy*.25;p.tilt*=.8+energy*.2;
 return p;
}
export class FaceAnimator{
 constructor(){this.values={...base};this.velocity=Object.fromEntries(Object.keys(base).map(k=>[k,0]));this.lastTime=-1;}
 update(v,dt,t){const target=faceTarget(v,t);if(dt===0||t<this.lastTime){this.values={...target};for(const k in this.velocity)this.velocity[k]=0;}else for(const key of Object.keys(base)){const speed=key.startsWith('blink')?47:['x','y'].includes(key)?24:19,damping=key.startsWith('blink')?1:.83;let left=Math.min(Math.max(dt,0),.1);while(left>0){const h=Math.min(left,1/120);this.velocity[key]+=(speed*speed*(target[key]-this.values[key])-2*damping*speed*this.velocity[key])*h;this.values[key]+=this.velocity[key]*h;left-=h;}}
 this.lastTime=t;return this.values;
 }
}
// Common topology means hearts, stars, pills, and curved lids morph rather than switch sprites.
export function eyeContour(p,side,steps=64){
 const points=[],blink=clamp(side<0?p.blinkL:p.blinkR),width=p.width*(1+blink*.08),height=Math.max(3,p.height*(1+side*p.asym)*(1-blink)),heart=clamp(p.heart)*(1-blink),star=clamp(p.star)*(1-blink),angle=side*p.tilt,c=Math.cos(angle),s=Math.sin(angle);
 for(let i=0;i<steps;i++){const a=i/steps*Math.PI*2,cx=Math.cos(a),sy=Math.sin(a),ex=Math.sign(cx)*Math.abs(cx)**.58,ey=Math.sign(sy)*Math.abs(sy)**.58;
  const ht=a+Math.PI/2,hx=Math.sin(ht)**3,hy=-(13*Math.cos(ht)-5*Math.cos(2*ht)-2*Math.cos(3*ht)-Math.cos(4*ht))/17;
  const section=Math.floor(i/(steps/8)),fraction=(i%(steps/8))/(steps/8),a0=section*Math.PI/4,a1=(section+1)*Math.PI/4,r0=section%2?.29:1,r1=section%2?1:.29,sx=Math.cos(a0)*r0*(1-fraction)+Math.cos(a1)*r1*fraction,sy2=Math.sin(a0)*r0*(1-fraction)+Math.sin(a1)*r1*fraction;
  let x=ex*(1-heart)+hx*heart,y=ey*(1-heart)+hy*heart;x=x*(1-star)+sx*star;y=y*(1-star)+sy2*star;
  x*=width;y*=height;const lidCurve=p.curve+(blink*12);y+=(x*x/(width*width)-1)*lidCurve*(1-heart)*(1-star);y+=clamp(p.chevron)*(1-Math.abs(x/width))*-48*(1-blink);
  points.push([x*c-y*s,x*s+y*c]);
 }return points;
}
export function path(ctx,points){ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();}
// layout fits the 1024x640 face onto other screens: scale enlarges it about the centre (dy moves it up or down) and
// spread pulls the eyes and cheek marks together (JP01's square screen wants a bigger, more compact face).
export function drawFace(ctx,p,t,{scale=1,spread=1,dy=0,eye=null}={}){// eye(ctx,p,side,color,contour) swaps how an eye is drawn; its animation, brows and marks stay
 const W=ctx.canvas.width,H=ctx.canvas.height;ctx.clearRect(0,0,W,H);ctx.save();ctx.translate(W/2,H/2+dy);ctx.scale(scale,scale);ctx.translate(-512,-320);
 const color=`rgb(${Math.round(clamp(p.red,0,255))},${Math.round(clamp(p.green,0,255))},${Math.round(clamp(p.blue,0,255))})`;
 for(const side of [-1,1]){
  ctx.save();ctx.translate(512+side*p.spread*spread+p.x,288+p.y);const contour=eyeContour(p,side);if(eye)eye(ctx,p,side,color,contour);else{ctx.fillStyle=color;ctx.shadowColor=color;ctx.shadowBlur=17;path(ctx,contour);ctx.fill();ctx.shadowBlur=0;}
  if(!eye&&p.ring>.01){ctx.globalCompositeOperation='destination-out';ctx.save();ctx.scale(clamp(p.ring,0,.84),clamp(p.ring,0,.84));path(ctx,contour);ctx.fill();ctx.restore();ctx.globalCompositeOperation='source-over';}
  if(p.brows>.01){ctx.globalAlpha=clamp(p.brows);ctx.strokeStyle=color;ctx.lineWidth=8;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(-58,-143-p.browLift-side*p.browSlope*55);ctx.quadraticCurveTo(0,-152-p.browLift,58,-143-p.browLift+side*p.browSlope*55);ctx.stroke();}
  ctx.restore();
 }
 // Secondary marks stay within the display, so the character's silhouette remains fixed.
 ctx.save();ctx.strokeStyle='#ffa8ba';ctx.lineWidth=7;ctx.lineCap='round';ctx.globalAlpha=clamp(p.blush)*.65;
 for(const side of [-1,1])for(let i=0;i<3;i++){const x=512+side*302*spread+i*19;ctx.beginPath();ctx.moveTo(x,397);ctx.lineTo(x-9,423);ctx.stroke();}ctx.restore();
 if(p.tear>.02){ctx.save();ctx.fillStyle='#9dcfff';for(const side of [-1,1]){const phase=(t*.48+(side>0?.4:0))%1;ctx.globalAlpha=clamp(p.tear)*Math.sin(phase*Math.PI);ctx.beginPath();ctx.ellipse(512+side*245*spread+p.x,340+phase*147,8,13,0,0,Math.PI*2);ctx.fill();}ctx.restore();}
 if(p.sparkles>.02){ctx.save();ctx.fillStyle=color;for(let i=0;i<5;i++){const phase=(t*.4+i*.19)%1,alpha=Math.sin(phase*Math.PI)*clamp(p.sparkles);ctx.globalAlpha=alpha*.85;const x=[190,800,500,237,772][i],y=[154,165,110,442,426][i]-phase*15,r=6+alpha*7;ctx.beginPath();ctx.moveTo(x,y-r);ctx.quadraticCurveTo(x+2,y-2,x+r,y);ctx.quadraticCurveTo(x+2,y+2,x,y+r);ctx.quadraticCurveTo(x-2,y+2,x-r,y);ctx.quadraticCurveTo(x-2,y-2,x,y-r);ctx.fill();}ctx.restore();}
 if(p.dots>.02){ctx.save();ctx.fillStyle=color;for(let i=0;i<3;i++){ctx.globalAlpha=clamp(p.dots)*(.25+.75*(.5+.5*Math.sin(t*3-i*.8)));ctx.beginPath();ctx.arc(476+i*36,465,7,0,Math.PI*2);ctx.fill();}ctx.restore();}
 for(const [field,glyph,x,y] of [['question','?',765,138],['sleep','z',768,167],['notes','♪',205,150]])if(p[field]>.02){ctx.save();ctx.fillStyle=color;ctx.globalAlpha=clamp(p[field])*.7;ctx.font='46px Georgia';ctx.fillText(glyph,x,y-Math.sin(t*1.7)*5);if(field==='sleep'){ctx.font='28px Georgia';ctx.globalAlpha*=.7;ctx.fillText('z',803,119-Math.sin(t*1.7)*5);}ctx.restore();}
 ctx.restore();
}
