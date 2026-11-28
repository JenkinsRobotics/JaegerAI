// Full-body moves, keyed by hand. Adapted from local-avatar-demo/public/js/motion.js; see the README's source record.
// Authored poses in seconds. Feet are stage-space offsets; hands are shoulder-relative arm lengths.
export const MOVES={spin:{label:'Spin',icon:'⟳',duration:3.6,wide:true},dance:{label:'Dance',icon:'♫',duration:6.8,wide:true},hop:{label:'Hop',icon:'↟',duration:2.4,wide:true},celebrate:{label:'Celebrate',icon:'✷',duration:4.2,wide:true},clap:{label:'Clap',icon:'✦',duration:3.8},bow:{label:'Bow',icon:'⌄',duration:3.2,wide:true},heart:{label:'Heart',icon:'♡',duration:3.6},point:{label:'Point',icon:'↗',duration:2.8}};
export const sat=x=>Math.max(0,Math.min(1,x));
export const smooth=x=>{x=sat(x);return x*x*(3-2*x);};
export const STANCE={bodyX:0,bodyZ:0,bodyYaw:0,hipYaw:0,hipZ:0,spine:0,headX:0,headY:0,headZ:0,shoulders:0,
 lift:0,shiftX:0,shiftZ:0,crouch:.12,stepL:0,stepR:0,footLX:0,footLZ:0,footRX:0,footRZ:0,footPitchL:0,footPitchR:0,pivot:0,
 handLX:.12,handLY:-.91,handLZ:.08,handRX:.12,handRY:-.91,handRZ:.08,
 wristL:0,wristR:0,palmL:0,palmR:0,palmTurnL:0,palmTurnR:0,curlL:.2,curlR:.2,pointL:0,pointR:0};
// Monotone cubic Hermite curves keep velocity continuous without overshooting contact positions.
export function curve(keys,time){
 if(time<=keys[0][0])return keys[0][1];if(time>=keys.at(-1)[0])return keys.at(-1)[1];
 let i=0;while(keys[i+1][0]<time)i++;
 const slope=j=>(keys[j+1][1]-keys[j][1])/(keys[j+1][0]-keys[j][0]);
 const tangent=j=>{if(j===0||j===keys.length-1)return 0;const a=slope(j-1),b=slope(j);if(a*b<=0)return 0;const h0=keys[j][0]-keys[j-1][0],h1=keys[j+1][0]-keys[j][0],w1=2*h1+h0,w2=h1+2*h0;return (w1+w2)/(w1/a+w2/b);};
 const [t0,a]=keys[i],[t1,b]=keys[i+1],h=t1-t0,u=(time-t0)/h;
 return (2*u**3-3*u*u+1)*a+(u**3-2*u*u+u)*h*tangent(i)+(-2*u**3+3*u*u)*b+(u**3-u*u)*h*tangent(i+1);
}
export function flightHeight(time,takeoff=.58,duration=.46){const t=time-takeoff;if(t<=0||t>=duration)return 0;return 4.905*t*(duration-t);}
const both=(x,y,z)=>({handLX:x,handLY:y,handLZ:z,handRX:x,handRY:y,handRZ:z});
const pose=(time,values)=>({time,values});
const clips={
 spin:[
  pose(0,{}),pose(.32,{crouch:.52,shiftX:.045,bodyYaw:-.28,hipYaw:-.13,headY:.12,...both(.3,-.54,-.15)}),
  pose(.65,{crouch:.19,shiftX:.075,bodyYaw:-.16,hipYaw:.03,headY:-.35,handLX:.75,handLY:.03,handLZ:.22,handRX:.55,handRY:-.18,handRZ:.3}),
  pose(1.05,{crouch:.08,shiftX:.075,stepR:.09,footRX:.055,footRZ:.05,bodyYaw:.16,headY:-.68,...both(-.12,-.23,.46),curlL:.55,curlR:.55}),
  pose(1.65,{crouch:.08,shiftX:.075,stepR:.1,footRX:.055,footRZ:.05,bodyYaw:.12,headY:.68,...both(-.12,-.23,.46),curlL:.55,curlR:.55}),
  pose(2.25,{crouch:.2,shiftX:.06,stepR:.06,footRX:.035,bodyYaw:-.18,headY:.15,handLX:.82,handLY:.22,handLZ:.17,handRX:.64,handRY:-.16,handRZ:.29,palmL:.65,palmR:.4}),
  pose(2.65,{crouch:.36,shiftX:.025,bodyYaw:-.09,bodyZ:.04,headZ:-.06,...both(.58,-.28,.16)}),pose(3.15,{crouch:.12,...both(.22,-.84,.12)}),pose(3.6,{})
 ],
 hop:[pose(0,{}),pose(.3,{crouch:.95,shiftZ:-.055,bodyX:.24,headX:-.13,...both(.27,-.72,-.24)}),pose(.48,{crouch:.8,shiftZ:-.04,bodyX:.17,...both(.32,-.52,-.1)}),pose(.62,{crouch:.03,bodyX:-.06,headX:-.08,...both(.45,.63,.2),palmL:.65,palmR:.65}),pose(.82,{crouch:.13,stepL:.035,stepR:.035,footPitchL:.17,footPitchR:.17,...both(.5,.7,.2)}),pose(1.04,{crouch:.08,...both(.45,.12,.35)}),pose(1.18,{crouch:.95,shiftZ:-.05,bodyX:.2,headX:.1,...both(.35,-.32,.48)}),pose(1.48,{crouch:.37,bodyX:.04,...both(.25,-.58,.2)}),pose(1.85,{}),pose(2.4,{})],
 celebrate:[pose(0,{}),pose(.34,{crouch:.48,shiftZ:-.025,bodyX:.1,...both(-.08,-.35,.46),curlL:.8,curlR:.8}),pose(.72,{crouch:.06,shiftX:.03,bodyZ:-.035,headX:-.08,handLX:.55,handLY:.7,handLZ:.13,handRX:.42,handRY:.58,handRZ:.17,palmL:.8,palmR:.8}),pose(1.15,{crouch:.15,shiftX:.035,headZ:-.1,handLX:.55,handLY:.67,handLZ:.13,handRX:.42,handRY:.55,handRZ:.17,palmL:.8,palmR:.8}),pose(1.65,{crouch:.25,shiftX:-.035,bodyZ:.06,handLX:.46,handLY:.32,handLZ:.29,handRX:.48,handRY:.54,handRZ:.18,palmL:.6,palmR:.8}),pose(2.02,{crouch:.08,shiftX:-.045,bodyZ:.035,headZ:.1,handLX:.46,handLY:.58,handLZ:.2,handRX:.55,handRY:.75,handRZ:.12,palmL:.8,palmR:.8}),pose(2.8,{crouch:.12,shiftX:-.04,headZ:.08,handLX:.46,handLY:.58,handLZ:.2,handRX:.55,handRY:.75,handRZ:.12,palmL:.8,palmR:.8}),pose(3.5,{...both(.36,-.4,.24)}),pose(4.2,{})],
 bow:[pose(0,{}),pose(.35,{crouch:.2,shiftZ:-.015,...both(.06,-.8,.18)}),pose(1.0,{bodyX:.72,headX:.08,crouch:.3,shiftZ:-.085,...both(.03,-.75,.28)}),pose(1.7,{bodyX:.72,headX:.08,crouch:.3,shiftZ:-.085,...both(.03,-.75,.28)}),pose(2.45,{bodyX:-.025,headX:.035,crouch:.14,...both(.1,-.87,.12)}),pose(3.2,{})],
 heart:[pose(0,{}),pose(.42,{handLX:.24,handLY:-.42,handLZ:.42,handRX:.16,handRY:-.57,handRZ:.35}),pose(.9,{...both(-.22,-.12,.66),palmL:.6,palmR:.6,curlL:.6,curlR:.6,bodyZ:-.04,headZ:.12}),pose(2.6,{...both(-.22,-.12,.66),palmL:.6,palmR:.6,curlL:.6,curlR:.6,bodyZ:-.04,headZ:.12}),pose(3.15,{...both(.13,-.54,.32)}),pose(3.6,{})],
 point:[pose(0,{}),pose(.32,{headY:-.14,handRX:-.03,handRY:-.28,handRZ:.4,curlR:.7}),pose(.72,{bodyYaw:-.12,headY:-.3,shiftX:.025,handRX:.72,handRY:.12,handRZ:.53,pointR:1,curlR:1,palmR:.25}),pose(1.9,{bodyYaw:-.12,headY:-.3,shiftX:.025,handRX:.72,handRY:.12,handRZ:.53,pointR:1,curlR:1,palmR:.25}),pose(2.35,{handRX:.3,handRY:-.35,handRZ:.4}),pose(2.8,{})]
};
// One step-touch phrase: shift onto the support leg BEFORE lifting the travelling foot.
const danceHalf=[
 pose(0,{}),pose(.28,{shiftX:-.045,crouch:.28,bodyYaw:-.08,handLX:.2,handLY:-.55,handLZ:.33,handRX:-.08,handRY:-.3,handRZ:.47}),
 pose(.62,{shiftX:-.035,footLX:.1,stepL:.075,footLZ:.035,footPitchL:-.12,crouch:.18,bodyYaw:-.14,handLX:.4,handLY:.2,handLZ:.4,handRX:-.16,handRY:-.2,handRZ:.48}),
 pose(.96,{shiftX:.035,footLX:.18,crouch:.33,bodyYaw:-.04,handLX:.67,handLY:.58,handLZ:.21,handRX:.1,handRY:-.42,handRZ:.3,palmL:.7}),
 pose(1.25,{shiftX:.145,footLX:.18,crouch:.12,hipZ:-.07,bodyZ:.065,bodyYaw:.12,headZ:-.07,handLX:.67,handLY:.58,handLZ:.21,handRX:.13,handRY:-.47,handRZ:.27,palmL:.7}),
 pose(1.55,{shiftX:.15,footLX:.18,footRX:.09,stepR:.065,footRZ:.04,footPitchR:-.12,crouch:.17,hipZ:-.06,bodyZ:.06,headZ:-.07,handLX:.6,handLY:.49,handLZ:.25,handRX:.05,handRY:-.35,handRZ:.37,palmL:.6}),
 pose(1.82,{shiftX:.15,footLX:.18,footRX:.14,crouch:.23,bodyZ:.04,handLX:.52,handLY:.34,handLZ:.34,handRX:-.12,handRY:-.24,handRZ:.48,palmL:.5}),
 pose(2.08,{shiftX:.13,footLX:.18,footRX:.08,stepR:.06,footRZ:.03,crouch:.17,handLX:.4,handLY:.05,handLZ:.4,handRX:-.12,handRY:-.26,handRZ:.46}),
 pose(2.38,{shiftX:.02,footLX:.18,crouch:.28,handLX:.26,handLY:-.35,handLZ:.35,handRX:.12,handRY:-.5,handRZ:.32}),
 pose(2.68,{shiftX:-.045,footLX:.08,stepL:.07,footLZ:.035,crouch:.18,bodyYaw:.06,handLX:.16,handLY:-.62,handLZ:.24,handRX:.2,handRY:-.6,handRZ:.22}),pose(3.0,{})
];
function mirrored(values){const result={};for(const [key,value] of Object.entries(values)){const swapped=key.replace('L','@').replace('R','L').replace('@','R');result[swapped]=['shiftX','bodyZ','bodyYaw','hipYaw','hipZ','spine','headY','headZ','footLX','footRX'].includes(key)?-value:value;}return result;}
clips.dance=[...danceHalf,...danceHalf.slice(1).map(k=>pose(k.time+3.1,mirrored(k.values))),pose(6.8,{})];
clips.clap=[pose(0,{}),pose(.45,{...both(.15,-.15,.68),palmL:1,palmR:1,palmTurnL:-1.35,palmTurnR:1.35}),
 ...[.85,1.55,2.25].flatMap(t=>[pose(t-.2,{...both(.23,-.15,.64),palmL:1,palmR:1,palmTurnL:-1.35,palmTurnR:1.35}),pose(t,{...both(-.28,-.15,.7),palmL:1,palmR:1,palmTurnL:-1.35,palmTurnR:1.35,headX:.025,crouch:.16}),pose(t+.09,{...both(-.28,-.15,.7),palmL:1,palmR:1,palmTurnL:-1.35,palmTurnR:1.35,crouch:.15})]),pose(2.9,{...both(.14,-.3,.52),palmL:.7,palmR:.7}),pose(3.8,{})];
const tracks=Object.fromEntries(Object.entries(clips).map(([name,keys])=>[name,Object.fromEntries(Object.keys(STANCE).map(channel=>[channel,keys.map(k=>[k.time,k.values[channel]??STANCE[channel]])]))]));
export function sampleMove(name,age){
 const info=MOVES[name];if(!info||age<0||age>info.duration)return null;
 const p=Object.fromEntries(Object.entries(tracks[name]).map(([key,keys])=>[key,curve(keys,age)]));
 p.smile=name==='bow'?.4:.85;
 if(name==='spin'){p.spin=curve([[0,0],[.38,-.18],[.7,0],[1.25,2.05],[1.9,5.35],[2.38,Math.PI*2],[3.6,Math.PI*2]],age);p.pivot=smooth(age/.3)*smooth((3.25-age)/.5);}
 if(name==='hop')p.lift=flightHeight(age);
 if(name==='celebrate')p.stars=smooth(age/.5)*smooth((4.2-age)/.6);
 if(name==='heart'){p.heart=smooth(age/.7)*smooth((3.6-age)/.6);p.blush=.8;}
 return {pose:p,weight:smooth(age/.18)*smooth((info.duration-age)/.3),progress:age/info.duration};
}

// The move as it should look right now, including a move being stopped early: it fades out and a spin turns back the short way.
export function moveNow(act){
 if(!act)return null;
 const m=sampleMove(act.name,act.age);if(!m)return null;
 if(act.stop!==undefined){const f=1-smooth(act.stop);m.weight*=f;for(const k of ['pivot','lift'])if(m.pose[k])m.pose[k]*=f;if(m.pose.spin){const s=m.pose.spin;m.pose.spin=s<Math.PI?s*f:2*Math.PI-(2*Math.PI-s)*f;}}
 return m;
}
