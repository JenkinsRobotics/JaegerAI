"""Generates tokens/jaeger-tokens.json (W3C Design Tokens format) from the approved proposal values."""
import json
P=json.load(open('../proposal-tokens.json')); S=json.load(open('../style-sweep-contrast.json'))
def c(v,d=None): 
    o={"$type":"color","$value":v}
    if d: o["$description"]=d
    return o
def L(h):
    h=h.lstrip('#');x=[int(h[i:i+2],16)/255 for i in (0,2,4)];x=[a/12.92 if a<=.04045 else ((a+.055)/1.055)**2.4 for a in x];return .2126*x[0]+.7152*x[1]+.0722*x[2]
def cr(a,b): x,y=sorted([L(a),L(b)],reverse=True);return (x+.05)/(y+.05)
def clamp_dark(h,bg,t=4.5):
    r,g,b=[int(h[i:i+2],16) for i in (1,3,5)];k=1.0
    while cr('#%02x%02x%02x'%(int(r*k),int(g*k),int(b*k)),bg)<t: k-=0.01
    return '#%02x%02x%02x'%(int(r*k),int(g*k),int(b*k))
J=P['jaeger']
role={'bg':'bg','surface':'surface','sidebar':'sidebar','raised':'raised','inset':'inset','border':'border','border_strong':'border-strong',
 'text':'text','text2':'text-2','text3':'text-3','faint':'faint','accent':'accent','accent_hover':'accent-hover','accent_text':'accent-text','on_accent':'on-accent','focus':'focus','ok':'ok','warn':'warn','error':'error','info':'info'}
color={m:{role[k]:c(v) for k,v in J[m].items() if k in role} for m in ('light','dark')}
color['light']['faint']["$description"]=color['dark']['faint']["$description"]="non-text UI only (>=3:1)"
tints={k:c(v,"white label passes 4.5") for k,v in P['tints'].items()}
# feels
def sweep(name,mode):
    t=S[name]['tokens'];return {'bg':c(t['bg']),'surface':c(t['surface']),'sidebar':c(t['bg']),'raised':c(t['raised']),'inset':c(t['raised']),
      'text':c(t['text']),'text-2':c(t['muted']),'text-3':c(t['muted']),'accent':c(t['accent_fill']),'accent-hover':c(t['accent_fill']),
      'accent-text':c(t['accent_text']),'on-accent':c(t['on_fill']),'focus':c(t['accent_text']),'ok':c(t['ok']),'warn':c(t['warn']),'error':c(t['error']),'info':c(t['accent_text']),'border-strong':c(t['border_strong'])}
def light_accent(fill):
    a=clamp_dark(fill,'#ffffff');t=clamp_dark(fill,'#f0f0f0')  # text must pass on the darkest light surface (inset)
    return {'accent':c(a),'accent-hover':c(clamp_dark(a,'#ffffff',6.0)),'accent-text':c(t),'focus':c(a),'info':c(t),'on-accent':c('#ffffff')}
feels={
 "jaeger":{"$description":"House default. No overrides.","light":{},"dark":{}},
 "shield-mono":{"$description":"Jenkins Robotics shield logo (2023-24). Pure black/white, 2px outlines, radius 0-4. High-contrast feel.","light":sweep('shield-mono-light','light'),"dark":sweep('shield-mono-dark','dark'),
    "radius":{"xs":{"$type":"dimension","$value":"0px"},"sm":{"$type":"dimension","$value":"2px"},"md":{"$type":"dimension","$value":"4px"},"lg":{"$type":"dimension","$value":"4px"},"xl":{"$type":"dimension","$value":"4px"}},"border-width":{"$type":"dimension","$value":"2px"}},
 "ares-bronze":{"$description":"ARES app (ARESApp.swift #d9b256 on #101014, helmet icon). Dark-first; light keeps jaeger neutrals with a clamped bronze accent.","dark":sweep('ares-bronze','dark'),"light":light_accent('#d9b256')},
 "mission-control":{"$description":"ares-minecraft dashboard HUD. Dark-first; cyan glow hairlines, grid tiles, mono labels. Light keeps jaeger neutrals with clamped HUD blue.","dark":dict(sweep('mission-control','dark'),**{"glow":{"$type":"shadow","$value":{"color":"#08ebf166","offsetX":"0px","offsetY":"0px","blur":"10px","spread":"0px"}}}),"light":light_accent('#3889fd'),
    "radius":{"sm":{"$type":"dimension","$value":"4px"},"md":{"$type":"dimension","$value":"6px"},"lg":{"$type":"dimension","$value":"8px"}}},
 "aurora":{"$description":"Classic flame-J colours. Dark-first; gradient is decoration only, never under text.","dark":dict(sweep('aurora','dark'),**{"gradient-decor":{"$type":"gradient","$value":[{"color":"#e05af6","position":0},{"color":"#9c4beb","position":0.4},{"color":"#4f45cb","position":0.7},{"color":"#3d84d8","position":1}]}}),"light":light_accent('#7b3fe0')},
 "vscode":{"$description":"Public MIT VS Code Modern defaults (not REA). Inside VS Code the host --vscode-* vars win.","light":{'bg':c('#ffffff'),'surface':c('#ffffff'),'sidebar':c('#f8f8f8'),'text':c('#3b3b3b'),'accent':c('#005fb8'),'accent-text':c('#005fb8'),'focus':c('#005fb8'),'info':c('#005fb8')},
    "dark":{'bg':c('#1f1f1f'),'surface':c('#1f1f1f'),'sidebar':c('#181818'),'raised':c('#252526'),'text':c('#cccccc'),'accent':c('#0078d4'),'accent-text':c('#4daafc'),'focus':c('#4daafc'),'info':c('#4daafc')},
    "radius":{"xs":{"$type":"dimension","$value":"2px"},"sm":{"$type":"dimension","$value":"4px"},"md":{"$type":"dimension","$value":"6px"},"lg":{"$type":"dimension","$value":"8px"}},"stream":{"$type":"string","$value":"vscode"},"motion-enter":{"$type":"duration","$value":"0ms"}},
 "grok":{"$description":"REA grokbot-re measurements; raw accent #1680f3 clamped to #0c73e4 (raw fails 3.88 under white).","light":{'accent':c('#0c73e4'),'accent-text':c(clamp_dark('#0c73e4','#f0f0f0')),'focus':c('#0c73e4'),'info':c(clamp_dark('#0c73e4','#f0f0f0'))},"dark":{'accent':c('#0c73e4'),'accent-text':c('#4d9bff'),'focus':c('#4d9bff'),'info':c('#4d9bff')},
    "font-size-body":{"$type":"dimension","$value":"14px"},"font-weight-body":{"$type":"number","$value":420},"line-height-body":{"$type":"dimension","$value":"22px"},"radius":{"xl":{"$type":"dimension","$value":"18px"}},"stream":{"$type":"string","$value":"grok"}},
}
later={"chatgpt":"deferred to later (REA values in proposal §2)","claude":"deferred to later","gemini":"deferred to later (pending REA data)"}
A=P['aether']
aether={"$description":"Aether brand override: shares every Jaeger neutral, text, status, type, space, radius and motion token; only accent differs (Aether Indigo).",
 "light":{k.replace('_','-'):c(v) for k,v in A['light'].items()},"dark":{k.replace('_','-'):c(v) for k,v in A['dark'].items()},
 "cad":{"part":c('#36d6c3'),"hardware":c('#ff8a3d'),"joint":c('#c38bff')}}
aether['light']['accent-hover']=c('#4038b8'); aether['dark']['accent-hover']=c('#5148c8')
dim=lambda v:{"$type":"dimension","$value":v}
tok={
 "$schema":"https://design-tokens.github.io/community-group/format/","$description":"Jaeger design tokens v1.0.0 (approved 2026-10-21). Single source of truth. Generated outputs: jaeger.css, jaeger-vscode-map.css, aether.css, JaegerTokens.swift, theme.py.",
 "meta":{"version":{"$type":"string","$value":"1.0.0"},"default-feel":{"$type":"string","$value":"jaeger"},"default-stream":{"$type":"string","$value":"jaeger"},"default-icon":{"$type":"string","$value":"shield-blue"},"default-avatar":{"$type":"string","$value":"bronze-helmet"}},
 "color":{"light":color['light'],"dark":color['dark'],"tint":tints,"tint-label":c('#ffffff')},
 "font":{"family-sans":{"$type":"fontFamily","$value":["-apple-system","BlinkMacSystemFont","SF Pro Text","Segoe UI","system-ui","sans-serif"]},
   "family-mono":{"$type":"fontFamily","$value":["ui-monospace","SF Mono","Menlo","Consolas","monospace"]},
   "size-body-app":dim("13px"),"size-body-web":dim("14px"),"line-height":{"$type":"number","$value":1.54},
   "scale":{k:dim(f"{v}px") for k,v in zip(["xs","sm","body","md","lg","xl","xxl"],[11,12,13,14,16,20,26])},
   "weight":{"regular":{"$type":"fontWeight","$value":400},"medium":{"$type":"fontWeight","$value":560},"strong":{"$type":"fontWeight","$value":650}}},
 "space":{str(i+1):dim(f"{v}px") for i,v in enumerate([4,8,12,16,20,24,32,40,48,64])}|{"half":dict(dim("2px"),**{"$description":"hairline nudges only"})},
 "radius":{"xs":dim("4px"),"sm":dim("6px"),"md":dim("8px"),"lg":dim("12px"),"xl":dim("18px"),"pill":dim("999px")},
 "motion":{"duration":{k:{"$type":"duration","$value":f"{v}ms"} for k,v in dict(instant=50,fast=100,base=150,slow=200,slower=300).items()},
   "easing":{"out":{"$type":"cubicBezier","$value":[.16,1,.3,1]},"press":{"$type":"cubicBezier","$value":[.215,.61,.355,1]},"standard":{"$type":"cubicBezier","$value":[.4,0,.2,1]}},
   "press-scale":{"$type":"number","$value":0.98},"enter-rise":dim("4px"),"reduced-motion":{"$type":"string","$value":"all transitions off under prefers-reduced-motion"}},
 "sound":{"$description":"Setting appearance.sounds, default off. Original synthesized cues, <250ms, peak -18 dBFS; muted when unfocused except attention.",
   "send":{"$type":"string","$value":"jg.sound.send","$description":"A5->E6, 60ms each, soft attack"},"done":{"$type":"string","$value":"jg.sound.done","$description":"C6 bell, 180ms decay; only if turn >8s"},
   "attention":{"$type":"string","$value":"jg.sound.attention","$description":"two 90ms D6 pulses 120ms apart"},"error":{"$type":"string","$value":"jg.sound.error","$description":"E4/F4 minor second 160ms low-passed"}},
 "feel":feels,"feel-later":{k:{"$type":"string","$value":v} for k,v in later.items()},
 "brand":{"aether":aether},
 "asset":{"icon":{k:{"$type":"string","$value":v} for k,v in {"shield-blue":"assets/shield-blue.svg","shield-dark":"assets/shield-dark.svg","shield-light":"assets/shield-light.svg","template":"assets/shield-template.svg"}.items()},
   "avatar":{"bronze-helmet":{"$type":"string","$value":"assets/avatar-bronze-{full|face}-{px}.png","$description":"face crop at <=32pt, full above"}}},
}
json.dump(tok,open('tokens/jaeger-tokens.json','w'),indent=1)
print('ok')
