"""Original Aether illustrated tool artwork. Regenerate with python3 generate.py.
All geometry is vector; no third-party icon fonts or embedded bitmap assets.
"""
from pathlib import Path

ROOT = Path(__file__).parent
icons = {}

def path(d, fill='none', stroke='var(--tool-edge,#627f98)', width=1.1, extra=''):
    return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round" {extra}/>'

def line(d, color='var(--tool-blue,#198fdf)', width=1.6, extra=''):
    return path(d, 'none', color, width, extra)

def circle(x,y,r,fill='var(--tool-blue,#198fdf)',stroke='none'):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}"/>'

def cube(x=8,y=5,s=16,blue=False):
    h=s*.32
    a=x+s/2
    return (path(f'M{x} {y+h} {a} {y} {x+s} {y+h} {a} {y+2*h}Z', 'url(#blueTop)' if blue else 'url(#metalTop)')+
        path(f'M{x} {y+h} {a} {y+2*h}V{y+s+h}L{x} {y+s}Z','url(#blueFront)' if blue else 'url(#metalFront)')+
        path(f'M{a} {y+2*h} {x+s} {y+h}V{y+s}L{a} {y+s+h}Z','url(#blueSide)' if blue else 'url(#metalSide)'))

blue='var(--tool-blue,#198fdf)'
orange='var(--tool-orange,#ef994c)'
pale='var(--tool-paper,#eff6fb)'
arrow=line('M16 15V2 M12 6 16 2 20 6',blue,1.8)
icons['extrude']=path('M5 23 16 18 27 23 16 29Z',pale,extra='stroke-dasharray="2 2"')+cube(8,7,16,True)+arrow
icons['part']=cube(6,4,20,True)
icons['new-part']=cube(4,5,18,True)+circle(25,24,6,pale)+line('M25 20V28 M21 24H29')
icons['assembly']=cube(3,12,12,True)+cube(16,12,12)+cube(10,2,12,True)
icons['revolve']=path('M6 12Q16 2 26 12L23 24Q16 30 9 24Z','url(#blueFront)')+path('M6 12Q16 20 26 12Q16 4 6 12Z','url(#blueTop)')+line('M16 3V28',orange,1.2,'stroke-dasharray="2 2"')+line('M4 17C0 26 25 32 29 21 M25 23 29 21 29 26',blue)
icons['loft']=path('M6 24 10 7 22 7 27 24 16 29Z','url(#blueFront)')+path('M10 7 16 3 22 7 16 11Z','url(#blueTop)')+line('M6 24 16 19 27 24 M8 17 16 13 24 17',pale,1)
icons['sweep']=path('M3 18Q14 19 15 6L23 8Q25 25 12 28L3 24Z','url(#blueFront)')+path('M15 6 21 3 28 7 23 11Z','url(#blueTop)')+path('M3 18 10 21V28L3 24Z','url(#blueSide)')+line('M5 12Q10 12 11 3',orange,1,'stroke-dasharray="2 2"')
icons['fillet']=path('M5 26V14Q5 5 14 5H23L28 11V25Z','url(#metalFront)')+path('M5 14Q5 5 14 5H23L28 11H17Q11 11 11 18Z','url(#blueTop)')+path('M11 18Q11 11 17 11H28V25H11Z','url(#metalTop)')
icons['chamfer']=path('M5 26V13L13 5H23L28 11V26Z','url(#metalFront)')+path('M5 13 13 5 23 5 28 11 17 11 11 18Z','url(#blueTop)')+path('M11 18 17 11H28V26H11Z','url(#metalTop)')
icons['shell']=cube(5,4,22)+path('M9 12 16 8 23 12 16 16Z','url(#blueSide)')+path('M9 12 16 16V25L9 21Z','url(#blueFront)')+path('M16 16 23 12V21L16 25Z','var(--tool-cavity,#244965)')
icons['draft']=path('M3 25 11 6 21 6 29 25 16 30Z','url(#blueFront)')+path('M11 6 16 3 21 6 16 10Z','url(#metalTop)')+path('M16 10 21 6 29 25 16 30Z','url(#metalSide)')+line('M3 4V25',orange,1,'stroke-dasharray="2 2"')
icons['mirror']=cube(2,9,11,True)+cube(19,9,11,True)+path('M16 2V30','none',orange,1.3,'stroke-dasharray="2 2"')
icons['plane']=path('M5 9 13 4V24L5 28Z','url(#metalTop)')+path('M19 8 27 3V23L19 28Z','url(#warm)')+line('M16 3V29',orange,1,'stroke-dasharray="2 2"')
icons['axis']=line('M6 27V5H28',orange,1.5,'stroke-dasharray="2 2"')+circle(6,5,2,orange)+circle(6,27,2,orange)
icons['point']=line('M16 3V29 M3 16H29',orange,1.4,'stroke-dasharray="2 2"')+circle(16,16,3,pale)+circle(16,16,1.8,orange)
icons['measure']=path('M4 13H29V20H4Z','url(#warm)')+line('M5 5V24 M24 5V24 M8 7H21', 'var(--tool-edge,#627f98)',1.5)+line('M9 15V18 M13 15V17 M17 15V18 M21 15V17',pale,1)
icons['insert']=path('M4 4H28V28H4Z','url(#blueFront)')+circle(21,11,3,pale)+path('M6 25 13 16 18 21 22 17 27 25Z',pale,'none')
icons['select']=path('M8 3 27 17 18 18 22 27 18 29 14 20 8 26Z','url(#blueTop)',blue)
icons['cut']=cube(5,4,22)+path('M12 8 19 5 25 9 18 12Z','url(#warm)')+path('M12 8 18 12V26L12 23Z','var(--tool-cavity,#244965)')+line('M10 3V20 M7 17 10 20 13 17',orange)
icons['hole']=cube(5,4,22)+f'<ellipse cx="16" cy="11" rx="5" ry="3" fill="var(--tool-cavity,#244965)" stroke="{blue}"/>'+line('M16 1V8',orange,1.4,'stroke-dasharray="2 2"')
icons['thread']=path('M9 5Q16 1 23 5V26Q16 31 9 26Z','url(#metalFront)')+''.join(line(f'M9 {y}Q16 {y+5} 23 {y}',blue,1.8) for y in (7,12,17,22))
icons['sheet']=path('M4 21 13 16V5L28 10V26L19 30Z','url(#blueFront)')+path('M4 21 13 16 28 26 19 30Z','url(#metalTop)')
icons['split']=cube(2,5,12)+cube(19,11,12,True)+line('M21 2 10 30',orange,1.3,'stroke-dasharray="2 2"')
icons['pattern']=''.join(cube(x,y,9,True) for x,y in ((2,3),(19,3),(2,18),(19,18)))
icons['copy']=cube(3,3,17)+cube(12,12,17,True)
icons['move']=cube(10,10,12,True)+line('M16 1V8 M13 4 16 1 19 4 M16 24V31 M13 28 16 31 19 28 M1 16H8 M4 13 1 16 4 19 M24 16H31 M28 13 31 16 28 19')
icons['rotate']=cube(8,9,16,True)+line('M4 14A12 12 0 0 1 27 9 M23 9H28V4',orange,1.8)
icons['scale']=cube(3,16,11,True)+line('M15 17 28 4 M21 4H28V11')+path('M12 3H29V21','none','var(--tool-edge,#627f98)',1,'stroke-dasharray="2 2"')
icons['sketch']=path('M3 10 21 3 29 22 11 29Z',pale)+line('M9 20 13 10 22 18Z',blue,1.2)+path('M12 25 24 7 28 10 16 28 11 29Z','url(#warm)')
icons['line']=line('M5 26 27 6',blue,2)+circle(5,26,2,pale)+circle(27,6,2,pale)
icons['arc']=line('M5 26Q4 5 27 6',blue,2)+circle(5,26,2,pale)+circle(27,6,2,pale)+line('M6 6V26 M6 6H27',orange,1,'stroke-dasharray="2 2"')
icons['curve']=line('M3 23C8 -4 20 37 29 7',blue,2)+circle(3,23,2,pale)+circle(29,7,2,pale)+line('M3 23 9 4 M29 7 23 28',orange,1)
icons['rectangle']=path('M5 7H27V25H5Z','url(#blueTop)',blue)+''.join(circle(x,y,1.8,pale) for x,y in ((5,7),(27,7),(5,25),(27,25)))
icons['circle']=circle(16,16,11,'url(#blueTop)',blue)+line('M16 16 25 9',orange,1.2)+circle(16,16,1.7,orange)
icons['polygon']=path('M16 3 28 10V23L16 29 4 23V10Z','url(#blueTop)',blue)+line('M16 16 28 10',orange,1.2)
icons['trim']=line('M3 8 29 24 M4 26 27 3',blue,2)+circle(8,6,3,pale)+circle(4,13,3,pale)+line('M10 9 22 24 M6 15 26 19',orange,2)
icons['offset']=path('M4 6H23V24H4Z','none',blue,1.8)+path('M10 12H29V30H10Z','none',orange,1.5)
icons['open']=path('M3 9H13L16 12H28V27H3Z','url(#metalFront)')+path('M3 16H30L25 28H3Z','url(#blueTop)')+line('M19 9V2 M15 6 19 2 23 6',blue)
icons['save']=path('M5 3H24L28 7V29H5Z','url(#blueFront)')+path('M10 3H22V12H10Z',pale)+path('M10 20H23V29H10Z','url(#metalTop)')+line('M19 5V10',blue,2)
icons['export']=cube(3,13,15,True)+line('M15 15 27 3 M19 3H27V11',orange,2)
icons['import']=cube(3,13,15,True)+line('M27 3 15 15 M15 7V15H23',orange,2)
icons['document']=path('M6 2H21L27 8V30H6Z',pale)+path('M21 2V8H27','url(#blueTop)')+line('M11 14H22 M11 19H22 M11 24H18')
icons['history']=circle(17,17,11,'url(#metalTop)','var(--tool-edge,#627f98)')+line('M17 9V17L23 20',blue,1.8)+line('M3 12V5H10 M3 5 8 9',orange,1.8)
icons['link']=path('M12 21 8 25A5 5 0 0 1 1 18L9 10A5 5 0 0 1 16 10 M20 11 24 7A5 5 0 0 1 31 14L23 22A5 5 0 0 1 16 22','none',blue,3)+line('M11 21 21 11',orange,2)
icons['fit']=cube(9,8,14,True)+line('M3 11V3H11 M21 3H29V11 M29 21V29H21 M11 29H3V21')
icons['grid']=path('M2 21 19 6 31 15 14 30Z','url(#metalTop)')+line('M6 17 18 26 M10 13 22 22 M15 9 27 18 M6 24 23 9 M10 27 27 12',blue,1)
icons['properties']=path('M5 3H27V29H5Z',pale)+line('M10 9H23 M10 16H23 M10 23H23','var(--tool-edge,#627f98)',1.5)+circle(14,9,2.5,blue)+circle(20,16,2.5,blue)+circle(13,23,2.5,blue)
icons['settings']=path('M13 2H19L20 6 24 8 28 7 31 13 28 16 28 20 30 23 25 28 21 26 18 28 17 31 11 29 11 25 7 23 3 24 1 18 5 15 5 11 3 8 8 4 12 6Z','url(#metalTop)')+circle(16,16,6,'url(#blueFront)')+circle(16,16,2,pale)
icons['inspect']=cube(3,4,17,True)+circle(20,20,7,'url(#metalTop)',blue)+line('M25 25 30 30',orange,3)
icons['remove']=cube(3,3,20)+circle(24,24,7,'url(#warm)')+line('M21 21 27 27 M27 21 21 27',pale,2)
icons['ground']=cube(9,3,15,True)+line('M16 21V26 M5 26H27 M8 29 11 26 M15 29 18 26 M22 29 25 26',orange,1.5)
icons['suppressed']=cube(6,4,20)+line('M3 29 29 3',orange,2)
icons['connector']=path('M3 16 16 3 29 16 16 29Z','url(#blueTop)')+circle(16,16,5,pale,blue)+line('M16 6V12 M16 20V26 M6 16H12 M20 16H26',orange)
icons['angle']=line('M4 5V27H29','var(--tool-edge,#627f98)',2)+path('M4 12A15 15 0 0 1 19 27L4 27Z','url(#blueTop)',blue)+line('M4 27 27 4',orange,1.5)
icons['parallel']=path('M4 9 26 3V9L4 15Z','url(#blueTop)')+path('M4 24 26 18V24L4 30Z','url(#metalTop)')
icons['perpendicular']=path('M3 22H29V28H3Z','url(#metalTop)')+path('M12 3H19V22H12Z','url(#blueFront)')+line('M20 16H25V21',orange)
icons['concentric']=circle(16,16,12,'url(#metalTop)','var(--tool-edge,#627f98)')+circle(16,16,7,'url(#blueFront)')+circle(16,16,3,pale)+line('M16 1V31 M1 16H31',orange,1,'stroke-dasharray="2 2"')
icons['eye']=path('M2 16Q16 -2 30 16Q16 34 2 16Z',pale)+circle(16,16,7,'url(#blueFront)')+circle(16,16,3,'var(--tool-cavity,#244965)')
icons['pan']=path('M7 18V9Q10 6 12 9V16 4Q15 1 17 4V15 6Q20 3 22 6V16 10Q25 7 27 10V22Q24 30 15 30L4 20Q3 16 7 18Z','url(#blueTop)')
icons['material']=circle(16,16,12,'url(#metalFront)','var(--tool-edge,#627f98)')+path('M7 21Q9 7 24 8Q21 3 16 4A12 12 0 0 0 7 21Z','url(#blueTop)','none')+circle(12,9,2,pale)
icons['light']=circle(16,14,8,'url(#warm)')+line('M13 23H19 M13 27H19 M16 1V3 M3 14H5 M27 14H29 M5 4 7 6 M25 4 23 6',orange,1.7)
icons['home']=path('M3 14 16 3 29 14','url(#blueTop)',blue)+path('M7 14V29H25V14','url(#metalTop)')+path('M13 20H19V29H13Z','url(#blueFront)')
icons['check']=circle(16,16,12,'url(#blueTop)',blue)+line('M9 16 14 21 24 10',blue,2.5)
icons['help']=circle(16,16,12,'url(#metalTop)','var(--tool-edge,#627f98)')+line('M11 11C11 5 23 6 22 12Q22 15 16 17V20',blue,2)+circle(16,25,1.4,blue)
icons['list']=path('M4 3H28V29H4Z',pale)+''.join(circle(9,y,1.8,blue)+line(f'M14 {y}H24','var(--tool-edge,#627f98)',1.4) for y in (9,16,23))
icons['panels']=path('M3 4H29V28H3Z',pale)+path('M3 4H29V10H3Z','url(#blueTop)')+path('M3 10H11V28H3Z','url(#metalFront)')+line('M23 10V28','var(--tool-edge,#627f98)',1)
for name,face in [('top','M6 10 16 5 26 10 16 15Z'),('front','M6 10 16 15V27L6 22Z'),('right','M16 15 26 10V22L16 27Z')]:
    icons['view-'+name]=cube(6,5,20)+path(face,'url(#blueFront)',blue)
icons['wireframe']=cube(6,5,20)+line('M6 22 16 17 26 22 M16 5V17','var(--tool-orange,#ef994c)',1,'stroke-dasharray="2 2"')
icons['edge']=cube(6,5,20)+line('M16 15V31',orange,2.5)
icons['vertex']=cube(6,5,20)+circle(16,15,3,orange)
icons['face']=cube(6,5,20)+path('M16 15 26 10V25L16 31Z','url(#blueFront)',blue)
icons['emboss']=cube(5,5,21)+cube(12,4,10,True)
icons['frame']=path('M3 8 23 2 29 7 9 13V29L3 25Z','url(#metalTop)')+path('M9 13 29 7V13L15 17V31L9 29Z','url(#blueFront)')
icons['weld']=icons['sheet']+line('M13 16 26 25',orange,4,'stroke-dasharray="1 3"')
icons['push-pull']=cube(6,9,20)+arrow
icons['replace-face']=icons['face']+line('M3 7H12 M9 4 12 7 9 10',orange,1.7)
icons['thicken']=path('M3 14 20 4 29 12 12 22Z','url(#metalTop)')+path('M3 20 20 10 29 18 12 28Z','url(#blueFront)')
icons['tangent']=circle(16,18,10,'url(#blueTop)',blue)+line('M3 8H29',orange,2)+circle(16,8,2,orange)
icons['slider']=path('M3 20 24 5 29 9 8 24Z','url(#metalTop)')+cube(10,8,12,True)+line('M5 29 27 13 M21 13H27V19',orange)
icons['hinge']=cube(2,6,12)+cube(18,14,12,True)+line('M16 3V29',orange,3)+circle(16,4,3,'url(#warm)')
icons['mass']=path('M9 12H23L29 29H3Z','url(#metalFront)')+circle(16,8,5,'none',blue)+line('M11 20H21',blue,3)
icons['back']=line('M12 7 3 15 12 23 M3 15H20Q28 15 28 27',blue,2.5)
icons['add']=cube(5,4,19,True)+circle(25,24,6,pale)+line('M25 20V28 M21 24H29')

colors={'blueTop':('#d2f3ff','#68bcf4'),'blueFront':('#50c9ff','#1687d7'),'blueSide':('#359be6','#2560a4'),'metalTop':('#f6fbff','#c8d6e1'),'metalFront':('#d4e0ea','#8fa4b7'),'metalSide':('#9eb4c7','#627e96'),'warm':('#ffd7a1','#f29b49')}
for name,art in icons.items():
    defs=''.join(f'<linearGradient id="{key}" x1="0" y1="0" x2=".7" y2="1"><stop stop-color="var(--tool-{key}-a,{a})"/><stop offset="1" stop-color="var(--tool-{key}-b,{b})"/></linearGradient>' for key,(a,b) in colors.items() if f'url(#{key})' in art)
    (ROOT/f'{name}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none"><defs>{defs}</defs>{art}</svg>\n')
print(f'Wrote {len(icons)} original tool SVGs')
