"""Original reusable Paper Days drawing primitives; authored at 1080x1920.
The lower caption band (1400-1660) is reserved for the renderer.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from functools import lru_cache
import math, random, json, os
import numpy as np

PAPER='#F5F1E6'; INK='#354940'; SOFT='#79867A'; SAGE='#A7B9A1'; GREEN='#657C67'
PALE='#DCE3D2'; WOOD='#CAA77F'; TERRA='#C78569'; PEACH='#EAC2A0'; SKIN='#DEAF8D'
CREAM='#FFFAED'; DARK='#3C453A'; BLUE='#8FAEB1'; GOLD='#D8B474'
FONT_ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'assets','fonts')
FONT=os.path.join(FONT_ROOT,'SourceHanSansSC-Regular.otf')
SERIF=os.path.join(FONT_ROOT,'SourceHanSansSC-Bold.otf')

def clamp(x,a=0.,b=1.): return max(a,min(b,x))
def ease(x):
    x=clamp(x); return x*x*(3-2*x)
def lerp(a,b,t): return a+(b-a)*t

def rgba(hexcol, alpha=255):
    if isinstance(hexcol,tuple): return hexcol[:3]+(int(alpha),)
    h=hexcol.lstrip('#'); return tuple(int(h[i:i+2],16) for i in (0,2,4))+(int(alpha),)

def mixed(a,b,t):
    return tuple(int(lerp(x,y,t)) for x,y in zip(rgba(a)[:3],rgba(b)[:3]))

@lru_cache(maxsize=200)
def font(size,serif=False): return ImageFont.truetype(SERIF if serif else FONT,max(1,int(size)))

@lru_cache(maxsize=12)
def background(size):
    w,h=size
    im=Image.new('RGB',(w,h),PAPER)
    # Fine paper tooth is static, so grain never flickers across frames.
    rng=np.random.default_rng(20261007)
    grain=np.clip(rng.normal(128,7,(h,w)),0,255).astype(np.uint8)
    n=Image.fromarray(grain,mode='L')
    tint=Image.merge('RGB',(n,n,n))
    im=Image.blend(im,tint,0.033)
    d=ImageDraw.Draw(im,'RGBA')
    sx=w/1080; sy=h/1920
    d.ellipse((int(-300*sx),int(180*sy),int(1320*sx),int(1380*sy)),fill=(221,226,207,20))
    return im

class C:
    def __init__(self, im, scale=1., ox=0., oy=0.):
        self.im=im; self.d=ImageDraw.Draw(im,'RGBA'); self.s=scale; self.ox=ox; self.oy=oy
    def sub(self,x=0,y=0,s=1): return C(self.im,self.s*s,self.ox+self.s*x,self.oy+self.s*y)
    def p(self,p): return (self.ox+p[0]*self.s,self.oy+p[1]*self.s)
    def box(self,b): return [self.ox+b[0]*self.s,self.oy+b[1]*self.s,self.ox+b[2]*self.s,self.oy+b[3]*self.s]
    def line(self,p,fill=INK,w=3):
        q=[self.p(v) for v in p]
        self.d.line(q,fill=fill,width=max(1,round(w*self.s)),joint='curve')
        if w>=5:
            r=w*self.s/2
            for x,y in [q[0],q[-1]]: self.d.ellipse((x-r,y-r,x+r,y+r),fill=fill)
    def poly(self,p,fill=None,outline=None,w=3):
        q=[self.p(v) for v in p]
        self.d.polygon(q,fill=fill)
        if outline:self.d.line(q+[q[0]],fill=outline,width=max(1,round(w*self.s)),joint='curve')
    def rect(self,b,fill=None,outline=None,w=3,r=0):
        if r:self.d.rounded_rectangle(self.box(b),radius=max(1,r*self.s),fill=fill,outline=outline,width=max(1,round(w*self.s)))
        else:self.d.rectangle(self.box(b),fill=fill,outline=outline,width=max(1,round(w*self.s)))
    def ellipse(self,b,fill=None,outline=None,w=3):self.d.ellipse(self.box(b),fill=fill,outline=outline,width=max(1,round(w*self.s)))
    def arc(self,b,start,end,fill=INK,w=3):self.d.arc(self.box(b),start,end,fill=fill,width=max(1,round(w*self.s)))
    def text(self,xy,txt,size=30,fill=INK,anchor='la',serif=False):
        self.d.text(self.p(xy),txt,font=font(size*self.s,serif),fill=fill,anchor=anchor,stroke_width=0)
    def path(self,commands,fill=None,outline=None,w=3,closed=True):
        pts=[]; pos=(0,0)
        for cmd in commands:
            if cmd[0]=='M':pos=tuple(cmd[1:]);pts.append(pos)
            elif cmd[0]=='L':pos=tuple(cmd[1:]);pts.append(pos)
            elif cmd[0]=='C':
                x0,y0=pos;x1,y1,x2,y2,x3,y3=cmd[1:]
                for i in range(1,17):
                    t=i/16;u=1-t
                    pts.append((u**3*x0+3*u*u*t*x1+3*u*t*t*x2+t**3*x3,u**3*y0+3*u*u*t*y1+3*u*t*t*y2+t**3*y3))
                pos=(x3,y3)
            elif cmd[0]=='Q':
                x0,y0=pos;x1,y1,x2,y2=cmd[1:]
                for i in range(1,13):
                    t=i/12;u=1-t;pts.append((u*u*x0+2*u*t*x1+t*t*x2,u*u*y0+2*u*t*y1+t*t*y2))
                pos=(x2,y2)
        if fill: self.poly(pts,fill)
        if outline:self.line(pts+([pts[0]] if closed else []),outline,w)
    def dash(self,p,fill=SOFT,w=3,seg=10):
        for a,b in zip(p,p[1:]):
            dx=b[0]-a[0];dy=b[1]-a[1];L=math.hypot(dx,dy)
            if not L:continue
            for n in range(0,int(L),seg*2):
                r0=n/L;r1=min((n+seg)/L,1)
                self.line([(a[0]+dx*r0,a[1]+dy*r0),(a[0]+dx*r1,a[1]+dy*r1)],fill,w)

# Icons and hand-made objects. Their forms recur to preserve physical continuity.
def paper(c,x,y,w=180,h=220,title=None,lines=5,fold=True,angle=0,colour=CREAM,alpha=255):
    z=c.sub(x,y); sh=rgba(INK,18*alpha/255)
    z.poly([(9,15),(w+9,17),(w+6,h+18),(9,h+16)],sh)
    z.poly([(0,0),(w-18 if fold else w,0),(w,18 if fold else 0),(w,h),(-3,h-3)],rgba(colour,alpha),rgba(SOFT,alpha),2)
    if fold:z.poly([(w-18,0),(w-18,20),(w,18)],rgba('#E9E3D3',alpha),rgba(SOFT,alpha),1.5)
    if title:z.text((18,18),title,min(28,w/5),rgba(INK,alpha))
    for i in range(lines):
        yy=65+i*24
        if yy<h-12:z.line([(19,yy),(w-25-(i%3)*13,yy+1)],rgba(SOFT,alpha*.43),2.5)
    return z

def notebook(c,x,y,w=170,h=130,opened=False,title='待学',alpha=255):
    z=c.sub(x,y)
    if opened:
        z.poly([(-w,8),(-9,0),(0,13),(9,0),(w,8),(w, h),(10,h-8),(0,h),( -10,h-8),(-w,h)],rgba('#FFF9E9',alpha),rgba(INK,alpha),3)
        z.line([(0,13),(0,h)],rgba(SOFT,alpha),2)
        z.text((-w+18,25),title,26,rgba(INK,alpha))
        for i in range(4):
            z.line([(20,36+i*21),(w-20,39+i*21)],rgba(SOFT,alpha*.52),2)
            if i>0:z.line([(-w+20,39+i*21),(-20,37+i*21)],rgba(SOFT,alpha*.52),2)
    else:
        z.poly([(0,0),(w,5),(w-3,h),(0,h-4)],rgba('#849883',alpha),rgba(INK,alpha),3)
        z.line([(12,0),(12,h-4)],rgba('#526B57',alpha),4)
        z.rect((w*.2,h*.26,w*.87,h*.62),rgba('#F1ECDC',alpha),r=3)
        z.text((w*.53,h*.4),title,25,rgba(INK,alpha),anchor='mm')
        z.line([(w-9,10),(w-9,h-10)],rgba('#FFF5DF',alpha),3)

def mug(c,x,y,s=1,tea=.7,steam=True):
    z=c.sub(x,y,s)
    z.ellipse((-43,62,56,89),rgba(INK,20));z.ellipse((27,3,62,47),None,INK,4)
    z.path([('M',-34,0),('C',-34,30,-30,58,-18,64),('C',-5,72,18,69,29,60),('C',39,47,39,21,36,0)],fill='#E9C79F',outline=INK,w=3)
    z.ellipse((-35,-9,36,12),CREAM,INK,3);z.ellipse((-28,-4,29,8),'#9F7956',None)
    z.path([('M',-21,22),('C',-25,43,-17,56,-5,58)],outline=rgba(CREAM,130),w=4,closed=False)
    if steam:
        for dx,dy in [(-10,0),(12,-7)]:z.path([('M',dx,-20+dy),('C',dx-9,-34+dy,dx+10,-41+dy,dx+2,-56+dy)],outline=rgba(SOFT,80),w=2.5,closed=False)

def remote(c,x,y,s=1,press=0):
    z=c.sub(x,y,s)
    z.rect((-23,-62,23,55),'#67746A',INK,3,15)
    z.ellipse((-8,-46,8,-30),TERRA,None)
    for yy in [-12,8,28]:
        for xx in [-10,10]:z.ellipse((xx-4,yy-4,xx+4,yy+4),PALE,None)
    z.rect((-12,-24,12,-17),rgba('#E9E9D4',230),r=3)
    if press>0:z.ellipse((-10,-34,15,-8),SKIN,INK,2)

def clock_machine(c,x,y,s=1,feed=.35,alpha=255):
    z=c.sub(x,y,s)
    z.ellipse((-91,129,99,147),rgba(INK,15*alpha/255))
    # Clearly a paper metaphor rather than an app panel.
    z.poly([(-75,-31),(54,-41),(87,-20),(86,106),(-75,112)],rgba('#F0DEC0',alpha),rgba(INK,alpha),3)
    z.poly([(54,-41),(87,-20),(62,-13)],rgba('#DBC6A7',alpha),rgba(INK,alpha),2)
    z.rect((-54,-13,58,63),rgba('#E2E5CF',alpha),rgba(INK,alpha),2,6)
    z.ellipse((-27,-5,30,52),rgba(CREAM,alpha),rgba(INK,alpha),2)
    z.line([(1,7),(1,24),(15,30)],rgba(INK,alpha),3)
    for dx,dy in [(0,0),(0,41),(-20,20),(20,20)]:z.ellipse((dx-1,dy+2,dx+2,dy+5),rgba(SOFT,alpha))
    z.rect((-50,80,55,88),rgba(INK,alpha),r=3)
    hh=15+feed*130
    z.path([('M',-36,87),('L',39,87),('C',43,107,30,119,37,128),('L',37,87+hh),('Q',0,77+hh,-34,91+hh),('L',-35,89)],fill=rgba(CREAM,alpha),outline=rgba(SOFT,alpha),w=2)
    for i in range(max(0,int(hh/22)-1)):z.line([(-23,106+i*22),(23,106+i*22)],rgba(SOFT,alpha*.37),2)

def plant(c,x,y,s=1):
    z=c.sub(x,y,s)
    z.ellipse((-45,63,50,81),rgba(INK,18))
    z.poly([(-42,0),(40,0),(30,69),(-28,69)],'#B58A6C',INK,3)
    z.ellipse((-43,-11,41,11),'#D5AD88',INK,3)
    for dx,yy,lean in [(-5,-35,-1),(11,-77,1),(-5,-107,-1),(10,-132,1)]:
        z.line([(0,0),(dx,yy)],'#647C61',4)
        z.path([('M',dx,yy+8),('C',dx+lean*65,yy+1,dx+lean*61,yy-44,dx+lean*17,yy-26),('C',dx+lean*1,yy-17,dx,yy-5,dx,yy+8)],fill='#8EA484',outline='#647C61',w=2)
        z.line([(dx,yy),(dx+lean*40,yy-21)],rgba('#5C775B',180),1.5)

def guitar(c,x,y,s=1,tilt=-30,strings=True):
    # x/y is centre of body; full neck + head extend along negative local y.
    z=c.sub(x,y,s); ang=math.radians(tilt)
    def rot(p):return (p[0]*math.cos(ang)-p[1]*math.sin(ang),p[0]*math.sin(ang)+p[1]*math.cos(ang))
    def po(points,fill=None,out=None,w=3):z.poly([rot(p) for p in points],fill,out,w)
    def ln(points,fill=INK,w=3):z.line([rot(p) for p in points],fill,w)
    # Smooth parametric guitar outline drawn as curved sampled points.
    pts=[]
    cmds=[('M',0,-105),('C',-26,-103,-64,-90,-61,-52),('C',-59,-27,-42,-23,-49,-5),('C',-56,9,-91,23,-87,63),('C',-82,113,-37,131,0,130),('C',42,128,86,106,88,64),('C',89,22,56,8,50,-5),('C',44,-24,63,-28,63,-53),('C',62,-88,27,-104,0,-105)]
    pos=(0,0)
    for cmd in cmds:
        if cmd[0]=='M':pos=tuple(cmd[1:]);pts.append(pos)
        else:
            x0,y0=pos;x1,y1,x2,y2,x3,y3=cmd[1:]
            for i in range(1,17):
                t=i/16;u=1-t;pts.append((u**3*x0+3*u*u*t*x1+3*u*t*t*x2+t**3*x3,u**3*y0+3*u*u*t*y1+3*u*t*t*y2+t**3*y3))
            pos=(x3,y3)
    po(pts,'#B78554',INK,4)
    po([(px*.91,py*.95) for px,py in pts],'#D6AD71',None)
    po([(-15,-266),(15,-266),(17,37),(-17,37)],'#705A42',INK,2)
    po([(-23,-318),(20,-321),(19,-263),(-16,-263)],'#B38356',INK,3)
    for yy in [-308,-290,-274]:
        ln([(-24,yy),(-35,yy)],'#6F7667',4);ln([(23,yy),(32,yy)],'#6F7667',4)
    # Sound hole as a rotated circle is unchanged.
    cx,cy=rot((0,-9));z.ellipse((cx-34,cy-34,cx+34,cy+34),'#5B4737',INK,2)
    z.ellipse((cx-29,cy-29,cx+29,cy+29),'#423E31',None)
    for yy in [-251,-231,-211,-191,-169,-146,-123,-99,-77]:ln([(-13,yy),(13,yy)],'#C5B699',1.5)
    po([(-37,63),(37,63),(36,77),(-36,77)],'#75553B',INK,2)
    if strings:
        for xx in [-10,-6,-2,2,6,10]:ln([(xx,-307),(xx,66)],'#E9D8B5',1)
    ln([(-61,49),(-60,69),(-51,89)],rgba(CREAM,100),3)


def face(c,x,y,s=1,mood='uneasy',gaze=1,blink=False):
    z=c.sub(x,y,s)
    z.ellipse((-57,-65,59,61),SKIN,INK,3)
    z.ellipse((-66,-6,-40,27),SKIN,INK,2);z.arc((-62,1,-47,21),270,100,SOFT,1.8)
    z.path([('M',-55,-10),('C',-73,-54,-45,-89,-4,-89),('C',22,-100,64,-69,59,-26),('C',47,-43,22,-48,12,-64),('C',-9,-42,-32,-42,-43,-24),('L',-42,10)],fill='#4C5142',outline=INK,w=3)
    z.path([('M',-31,-61),('C',-11,-81,11,-78,23,-68)],outline='#70705A',w=3,closed=False)
    # eyes and eyebrows have quiet asymmetry, never a cure-like grin.
    for xx in [-16,26]:
        if blink:z.line([(xx-7,2),(xx+8,3)],INK,3)
        else:
            z.ellipse((xx+gaze*2-3,-2,xx+gaze*2+3,7),INK)
        by=-17+(3 if mood in ['tired','uneasy'] and xx<0 else 0)
        z.line([(xx-9,by),(xx+8,by-3 if mood=='uneasy' and xx>0 else by+1)],INK,2.5)
    z.path([('M',12,6),('L',18,20),('L',8,24)],outline=rgba('#9C725D',180),w=2,closed=False)
    z.ellipse((-28,16,-9,24),rgba('#CE8872',65));z.ellipse((31,16,48,24),rgba('#CE8872',65))
    if mood=='laugh':z.arc((-3,25,30,46),0,170,INK,3);z.line([(1,30),(24,31)],CREAM,2)
    elif mood=='soft':z.arc((0,25,28,40),5,156,INK,2.5)
    elif mood=='tired':z.path([('M',0,39),('Q',11,33,22,36)],outline=INK,w=2.5,closed=False)
    else:z.path([('M',-1,35),('Q',11,32,24,36)],outline=INK,w=2.5,closed=False)


def person(c,x=426,y=786,s=1,pose='remote',mood='uneasy',gaze=1,t=0,blink=False):
    z=c.sub(x,y,s)
    # Stable body proportions, draping sweater, believable bent legs and slippers.
    z.path([('M',-86,155),('C',-74,214,-78,242,-123,282),('L',-141,359),('C',-150,378,-127,389,-111,372),('L',-45,293),('L',-6,217)],fill='#747E70',outline=INK,w=4)
    z.path([('M',-8,174),('C',47,181,73,216,62,248),('L',16,326),('L',50,374),('C',61,397,43,406,24,391),('L',-24,351),('C',-48,329,-38,314,-18,276),('L',7,241),('L',-62,225)],fill='#8B9381',outline=INK,w=4)
    z.path([('M',-139,356),('L',-170,370),('C',-187,378,-190,398,-169,399),('L',-111,390),('L',-110,373)],fill='#E5D9BD',outline=INK,w=3)
    z.path([('M',26,372),('C',52,372,84,389,79,405),('C',77,417,45,414,31,405),('L',17,394)],fill='#E5D9BD',outline=INK,w=3)
    z.path([('M',-53,43),('C',-100,48,-106,96,-107,144),('L',-92,201),('C',-57,219,10,220,51,190),('C',67,151,64,110,37,60),('C',20,47,0,45,-15,45)],fill='#C99371',outline=INK,w=3.5)
    z.path([('M',-23,31),('L',-25,59),('Q',-5,76,16,59),('L',15,24)],fill=SKIN,outline=INK,w=3)
    z.path([('M',-30,57),('Q',-3,88,24,60)],outline='#905F49',w=3,closed=False)
    for xx,yy in [(-71,132),(-48,187),(23,158)]:z.path([('M',xx,yy),('Q',xx+11,yy+9,xx+23,yy+1)],outline=rgba('#916A54',130),w=2,closed=False)
    # Camera-facing left arm, right arm change with activity.
    if pose=='guitar':
        guitar(z,13,151,s=.95,tilt=53)
        # Fretting hand lies on neck, strumming hand over the sound hole.
        sy=math.sin(t*math.pi*14)*8
        z.path([('M',-74,85),('Q',-105,153,-59,165),('Q',-17,181,27,156+sy)],outline=INK,w=36,closed=False)
        z.path([('M',-74,85),('Q',-105,153,-59,165),('Q',-17,181,27,156+sy)],outline='#C99371',w=30,closed=False)
        z.ellipse((8,139+sy,49,174+sy),SKIN,INK,2)
        for yy in [150,156,162]:z.line([(29,yy+sy),(46,yy+3+sy)],'#AA7C63',1.5)
        z.path([('M',37,79),('Q',96,113,147,48)],outline=INK,w=33,closed=False)
        z.path([('M',37,79),('Q',96,113,147,48)],outline='#C99371',w=28,closed=False)
        z.ellipse((135,29,170,66),SKIN,INK,2)
        for xx in [144,150,156]:z.line([(xx,35),(xx+5,59)],'#AA7C63',1.5)
    elif pose=='rest':
        z.path([('M',-81,82),('Q',-110,150,-65,191),('L',-18,194)],outline=INK,w=35,closed=False)
        z.path([('M',-81,82),('Q',-110,150,-65,191),('L',-18,194)],outline='#C99371',w=29,closed=False)
        z.ellipse((-23,178,22,205),SKIN,INK,2)
        z.path([('M',39,83),('Q',77,146,44,173),('L',10,190)],outline=INK,w=32,closed=False)
        z.path([('M',39,83),('Q',77,146,44,173),('L',10,190)],outline='#C99371',w=26,closed=False)
        z.ellipse((-3,175,31,199),SKIN,INK,2)
    else:
        z.path([('M',-79,82),('Q',-106,143,-64,171),('L',-20,179)],outline=INK,w=34,closed=False)
        z.path([('M',-79,82),('Q',-106,143,-64,171),('L',-20,179)],outline='#C99371',w=28,closed=False)
        z.ellipse((-27,164,14,189),SKIN,INK,2)
        z.path([('M',40,79),('Q',67,130,104,126),('L',137,102)],outline=INK,w=32,closed=False)
        z.path([('M',40,79),('Q',67,130,104,126),('L',137,102)],outline='#C99371',w=26,closed=False)
        remote(z,145,89,.65,press=1 if pose=='pause' else 0)
        z.ellipse((120,89,149,115),SKIN,INK,2)
    # Head always painted last, so shoulders and neck join cleanly.
    face(z,-8,-18,1,mood,gaze,blink)


def cat(c,x,y,s=1,t=0):
    phase=(t*4.2)%1
    bump=math.sin(clamp((phase-.72)/.25)*math.pi)*10
    z=c.sub(x,y,s); bob=math.sin(t*2*math.pi)*4
    z.ellipse((-57,60,72,77),rgba(INK,20))
    z.path([('M',49,44),('C',113+bump,66-bump,119+bump,-19-bump,77,-23),('C',57,-28,66,-2,76,4)],outline='#A77D50',w=19,closed=False)
    z.ellipse((-45,-6,55,67),'#D7AD70',INK,3)
    z.poly([(-41,-25),(-40,-71),(-13,-53),(18,-54),(47,-75),(46,-26)],'#D7AD70',INK,3)
    z.ellipse((-44,-57,49,13),'#D7AD70',INK,3)
    z.poly([(-34,-51),(-33,-65),(-21,-54)],'#C78678',None);z.poly([(26,-54),(41,-68),(40,-49)],'#C78678',None)
    z.arc((-27,-33,-7,-15),180,350,INK,3);z.arc((14,-34,34,-16),185,355,INK,3)
    z.poly([(-3,-17),(9,-17),(3,-11)],'#A87065',None)
    z.path([('M',3,-11),('L',3,-3),('Q',-3,5,-12,-2)],outline=INK,w=2,closed=False)
    z.path([('M',3,-3),('Q',10,5,17,-2)],outline=INK,w=2,closed=False)
    for xx in [-1,1]:
        z.line([(xx*19,-7),(xx*57,-14)],SOFT,1.5);z.line([(xx*21,0),(xx*58,4)],SOFT,1.5)
    z.ellipse((-38,43,-7,73),'#E6C48A',INK,2);z.ellipse((20,44,49,74),'#E6C48A',INK,2)
    # Paw bats a rolling yarn ball: original, simple and legible.
    py=10+math.sin(t*math.pi*4)*12
    z.path([('M',-32,10),('Q',-49,30,-62,py)],outline=INK,w=20,closed=False)
    z.path([('M',-32,10),('Q',-49,30,-62,py)],outline='#D7AD70',w=15,closed=False)
    bx=-102+214*(ease(phase/.76) if phase<.76 else 1-.28*ease((phase-.76)/.24))
    z.ellipse((bx-19,42,bx+20,80),TERRA,INK,2)
    z.arc((bx-16,47,bx+16,76),20,270,'#E2B69A',2);z.arc((bx-8,42,bx+12,80),60,250,'#E2B69A',2)
    z.path([('M',bx+13,76),('C',bx+23,94,bx-15,102,bx-27,92)],outline=TERRA,w=2,closed=False)


def tv(c,x=739,y=570,s=1,paused=False,t=0,cat_show=False,dull=0):
    z=c.sub(x,y,s)
    z.line([(-44,158),(-62,192)],INK,7);z.line([(47,158),(62,192)],INK,7)
    z.rect((-136,-15,136,165),'#616E61',INK,4,13)
    z.rect((-122,-2,122,145),mixed('#D0DDC3','#CDCFC3',dull),INK,2,6)
    z.ellipse((99,150,106,157),'#CFBA87')
    if cat_show:cat(z,17,72,.63,t)
    else:
        # Two deliberately invented drama stills; no borrowed TV images.
        z.poly([(-120,107),(-74,42),(-27,85),(19,35),(77,107),(122,72),(122,143),(-122,143)],'#A4B29B')
        z.ellipse((-92,9,-48,53),'#E5C288')
        ep=int(t*4)%2
        z.ellipse((-39,48,12,100),PEACH,INK,2)
        z.path([('M',-43,75),('C',-49,41,-23,30,-2,46),('C',11,48,14,61,13,69),('L',-18,59),('L',-33,82)],fill='#666A52',outline=INK,w=2)
        z.poly([(-39,100),(12,101),(43,144),(-61,144)],'#B7876E',INK,2)
        z.ellipse((-25,70,-19,77),INK);z.ellipse((-5,70,1,77),INK)
        if ep:z.arc((-24,77,2,93),5,165,INK,2)
        else:z.line([(-18,88),(-4,88)],INK,2)
    if paused:
        z.ellipse((64,8,108,52),rgba(CREAM,210))
        z.rect((76,20,82,42),INK,r=1);z.rect((90,20,96,42),INK,r=1)


def room(c,t=0,pose='remote',mood='uneasy',paused=False,clock=False,guitar_stand=True,dusk=0,cat_show=False,course_open=False,paper_list=0,gaze=1,clock_small=False):
    # Room architecture is constant through story, research transitions return here.
    z=c
    wall=mixed('#EAEAD8','#DBDCCD',dusk*.55)
    z.path([('M',81,469),('C',105,272,287,214,501,222),('C',762,217,952,355,952,562),('L',951,1255),('Q',541,1381,92,1255)],fill=wall)
    z.line([(98,1143),(925,1143)],rgba(INK,45),2)
    z.poly([(93,1146),(930,1146),(941,1255),(535,1350),(88,1260)],'#E3D6BF')
    # Soft irregular late-day window light and visible mullions.
    win=mixed('#D8E5D7','#C4CBBB',dusk)
    z.rect((142,291,388,644),'#E8DDC5',INK,3,5)
    z.rect((153,303,377,630),win,INK,2,3)
    z.ellipse((285,331,352,398),mixed('#F2D893','#D0AE85',dusk))
    z.path([('M',156,561),('C',214,499,230,557,286,508),('C',321,471,349,496,376,477),('L',377,629),('L',154,629)],fill='#B5C4AE')
    z.line([(265,306),(265,630)],'#788675',5);z.line([(156,469),(376,469)],'#788675',5)
    z.rect((135,638,398,654),'#C8B28E',INK,2,4)
    z.poly([(159,655),(376,655),(660,1128),(308,1128)],rgba('#FFF4CE',int(87*(1-dusk*.6))))
    # Curtains, slightly curved cloth with fold seams.
    z.path([('M',120,280),('L',152,281),('C',149,430,158,514,133,671),('L',107,670),('C',123,543,103,446,120,280)],fill='#ECE5D4',outline='#A5AC9A',w=2)
    z.path([('M',382,282),('L',414,281),('C',404,442,422,573,430,673),('L',399,670),('C',372,528,390,429,382,282)],fill='#ECE5D4',outline='#A5AC9A',w=2)
    z.line([(119,274),(416,274)],INK,4)
    # A framed botanical drawing gives the room an inhabited, specific identity.
    z.rect((495,330,614,486),'#C6B291',INK,2,2);z.rect((506,341,603,475),'#F5EEDD',None)
    z.line([(554,456),(549,370)],'#8A9477',2)
    for yy,sgn in [(430,1),(410,-1),(392,1)]:z.path([('M',550,yy),('Q',550+sgn*38,yy-28,550+sgn*26,yy-3),('Q',550+sgn*8,yy+10,550,yy)],fill='#AEBDA0')
    z.text((555,461),'SUNDAY',9,SOFT,anchor='mm')
    # TV credenza / books / basket.
    z.rect((667,761,919,971),'#C9AD87',INK,3,4)
    z.line([(685,971),(680,1019)],INK,5);z.line([(895,971),(904,1019)],INK,5)
    z.line([(674,858),(912,858)],'#947B5F',2)
    z.rect((684,782,789,848),'#D9C29E','#987F63',2,4);z.rect((800,782,904,848),'#D9C29E','#987F63',2,4)
    z.ellipse((757,810,765,818),'#7F7660');z.ellipse((819,810,827,818),'#7F7660')
    for bx,ww,hh,col in [(690,20,66,SAGE),(714,14,72,TERRA),(735,18,61,'#D2B481'),(757,18,68,BLUE)]:
        z.rect((bx,938-hh,bx+ww,938),col,INK,1.5);z.line([(bx+3,929),(bx+ww-3,929)],rgba(CREAM,180),1)
    z.rect((815,884,892,943),'#B79570',INK,2,5)
    for yy in range(891,940,9):z.line([(820,yy),(887,yy)],rgba('#F1DAB5',120),2)
    tv(z,795,584,.81,paused,t,cat_show,dusk*.2)
    # Rug and couch lower in the composition, all essential objects above y1350.
    z.ellipse((134,1036,901,1324),rgba('#A6B19B',65))
    for k in [0,1,2]:z.arc((142+k*15,1048+k*12,890-k*15,1310-k*12),4,178,rgba('#87967F',45),2)
    z.ellipse((153,1020,661,1135),rgba(INK,21))
    z.line([(195,1034),(179,1100)],INK,7);z.line([(602,1031),(617,1094)],INK,7)
    z.rect((171,676,624,982),'#9EAE96',INK,4,51)
    z.rect((190,702,397,914),'#B6C3AA','#73886F',2,34)
    z.rect((399,702,604,914),'#ADBEA1','#73886F',2,34)
    z.rect((173,900,625,1039),'#9AAC91',INK,3,25)
    z.line([(196,992),(601,992)],'#6E846C',2)
    z.rect((146,828,229,1043),'#A4B598',INK,4,35)
    z.rect((585,828,665,1043),'#A4B598',INK,4,35)
    # Cushion and folded woven throw.
    z.path([('M',206,741),('Q',256,708,296,751),('L',306,831),('Q',260,855,211,836)],fill='#D2BE93',outline='#8D9073',w=2)
    z.line([(224,755),(283,822)],rgba('#A08963',90),2);z.line([(281,749),(225,824)],rgba('#A08963',90),2)
    z.path([('M',195,891),('Q',250,875,314,906),('L',332,1019),('Q',295,1070,244,1038),('L',195,1039)],fill='#D0BA9C',outline='#8F8C70',w=2)
    for xx in range(217,322,18):z.line([(xx,915),(xx+7,1035)],rgba('#9A9477',120),2)
    for xx in range(247,325,10):z.line([(xx,1040),(xx+2,1057)],'#A29877',2)
    plant(z,123,840,.7)
    person(z,434,779,1,pose,mood,gaze,t,blink=(int(t*90)%41 in [0]))
    if guitar_stand:
        z.line([(729,1191),(686,1213)],INK,4);z.line([(729,1191),(764,1219)],INK,4)
        guitar(z,734,1083,.71,tilt=12)
    # Coffee table front: elliptical tabletop, clear object relationships.
    z.line([(550,1220),(531,1306)],'#8E755A',8);z.line([(836,1204),(855,1291)],'#8E755A',8)
    z.ellipse((442,1127,887,1273),'#AE906C',INK,3);z.ellipse((442,1119,887,1258),'#DDC3A0',INK,3)
    z.path([('M',474,1206),('C',572,1249,763,1250,852,1194)],outline=rgba('#B19572',100),w=2,closed=False)
    mug(z,571,1164,.63,steam=dusk<.5)
    notebook(z,716 if course_open else 684,1150,80 if course_open else 122,78,opened=course_open,title='待学')
    if pose in ['guitar','rest']:remote(z,832,1190,.48)
    if paper_list>0:
        hh=110+paper_list*290
        z.path([('M',714,1183),('L',803,1181),('C',810,1218,787,1247,792,1282),('L',795,min(1340,1180+hh)),('L',709,min(1334,1183+hh)),('C',704,1263,729,1230,714,1183)],fill=CREAM,outline=SOFT,w=2)
        z.text((730,1194),'待学',20)
        for yy in range(1232,min(1330,int(1180+hh)),22):z.line([(726,yy),(778,yy+2)],rgba(SOFT,150),2)
    if clock:
        if clock_small:clock_machine(z,855,400,.42,.23,175)
        else:
            z.ellipse((505,597,518,610),rgba(CREAM,205),SOFT,1.5);z.ellipse((531,567,552,588),rgba(CREAM,220),SOFT,1.5)
            clock_machine(z,645,430,.8,.15+.52*ease(t))


def heading(c,text,sub=None,y=218):
    c.text((98,y),text,42,INK,serif=True)
    if sub:c.text((100,y+65),sub,24,SOFT)

def desk(c,t=0):
    c.path([('M',73,385),('Q',506,294,960,386),('L',978,1231),('Q',529,1358,63,1224)],fill='#D8C3A2',outline='#9C977D',w=2)
    # Quiet long grain marks are a physical desk, not a presentation panel.
    for i in range(14):
        yy=413+i*58
        c.path([('M',93,yy),('C',293,yy-16,411,yy+12,935,yy-5)],outline=rgba('#AF9572',40),w=2,closed=False)
    c.poly([(844,456),(858,450),(932,853),(918,859)],'#7B8D77',INK,2)
    c.poly([(918,859),(932,853),(930,884)],'#D9BB88',INK,1)
    c.line([(63,1219),(977,1226)],rgba('#A28865',80),4)

def hand(c,x,y,s=1,left=False):
    z=c.sub(x,y,s);flip=-1 if left else 1
    pts=[(flip*0,76),(flip*9,22),(flip*5,-15),(flip*14,-20),(flip*22,10),(flip*29,-45),(flip*40,-44),(flip*40,5),(flip*46,-36),(flip*57,-32),(flip*51,11),(flip*59,-19),(flip*69,-12),(flip*58,38),(flip*45,78)]
    z.poly(pts,SKIN,INK,2.5)
    z.poly([(flip*-7,72),(flip*53,79),(flip*61,132),(flip*-17,136)],'#C99371',INK,2.5)
    z.line([(flip*5,87),(flip*51,91)],'#956D56',2)

def little_person(c,x,y,s=1,mood='soft',top=GREEN):
    z=c.sub(x,y,s)
    z.path([('M',-61,119),('C',-57,61,-30,42,0,43),('C',36,41,55,64,65,118)],fill=top,outline=INK,w=2)
    face(z,0,0,.62,mood,1)

# Event timing is optional. Keys may be seconds with duration, or normalized times.
def event_progress(events,key,t,default_start=0,span=.15):
    if not events:return ease((t-default_start)/span)
    data=events.get('anchors',events) if isinstance(events,dict) else events
    ev=None
    if isinstance(data,dict):ev=data.get(key)
    elif isinstance(data,list):
        ev=next((a for a in data if a.get('key',a.get('id'))==key),None)
    start=default_start
    if isinstance(ev,(int,float)):start=float(ev)
    elif isinstance(ev,dict):
        if 'progress' in ev:start=float(ev['progress'])
        elif 'normalized_progress' in ev:start=float(ev['normalized_progress'])
        elif 'normalized_time' in ev:start=float(ev['normalized_time'])
        elif 'time' in ev or 'start' in ev or 'local_seconds' in ev:
            sec=ev.get('local_seconds',ev.get('time',ev.get('start',0)))
            duration=events.get('duration',1) if isinstance(events,dict) else 1
            start=float(sec)/max(.01,float(duration))
    span=min(span,max(.025,(1-start)*.7))
    return ease((t-start)/span)



def configure_fonts(regular, emphasis=None):
    global FONT, SERIF
    FONT = str(regular)
    SERIF = str(emphasis or regular)
    font.cache_clear()
