#!/usr/bin/env python3
"""Derive an 18-chapter template from the native 26-chapter build.

Steps: keep chapter masters for slots 0..17, delete slots 18..25 (files +
designmap refs + orphaned stories); on BaseTabs delete slot>=18 tabs/numbers;
vertically scale the kept tabs (S=P18/P26 about the margin-box top Y0) so 18
tabs tile the box, resize+recolour them at N=18, reposition the numbers; swap
the N=26 tab swatches for N=18 ones; repoint the demo pages.

Usage: python3 make_18ch.py
"""
import os, re, csv, glob, shutil
SRC, OUT, N = "template_build_masters", "template_build_18", 18

PAGE_H, M_TOP, M_BOT = 595.275590551, 22.170070866, 55.842519685
Y0 = M_TOP - PAGE_H/2                 # margin-box top in spread space (-275.468)
box_h = PAGE_H - M_TOP - M_BOT
P18 = box_h / N                       # new pitch 28.737
P26 = 20.7233                         # old tab pitch
S = P18 / P26                         # vertical scale 1.3868
TY0_NUM = -264.69                     # number-frame grid top (26)
SLOT = lambda ytop: round((ytop - Y0) / P26)          # tab slot from top-y
NSLOT = lambda ty: round((ty - TY0_NUM) / P26)        # slot from number ty
SY = lambda y: Y0 + (y - Y0) * S                      # vertical scale about Y0

# ---- N=18 swatches ---------------------------------------------------------
KEYS=["Black","292","130","Warm Gray 1"]; TRAP=["Black","Warm Gray 1","130","292"]
INK_REF={"Black":"Ink/$ID/Process Black","Warm Gray 1":"Ink/PANTONE Warm Gray 1 U","130":"Ink/PANTONE 130 U","292":"Ink/PANTONE 292 U"}
INK_NAME={"Black":"$ID/Process Black","Warm Gray 1":"PANTONE Warm Gray 1 U","130":"PANTONE 130 U","292":"PANTONE 292 U"}
COLOR_REF={"Black":"Color/Black","Warm Gray 1":"Color/PANTONE Warm Gray 1 U","130":"Color/PANTONE 130 U","292":"Color/PANTONE 292 U"}
COLOR_NAME={"Black":"Black","Warm Gray 1":"PANTONE Warm Gray 1 U","130":"PANTONE 130 U","292":"PANTONE 292 U"}
enc=lambda s:s.replace(" ","%20")
stops=[[float(v) for v in r] for r in list(csv.reader(open("template_build.tabstops.csv")))[1:]]
def tween(p):
    Sn=len(stops)-1; seg=min(int(p*Sn),Sn-1); p0,p1=seg/Sn,(seg+1)/Sn
    f=(p-p0)/(p1-p0) if p1>p0 else 0
    return {KEYS[k]:round(stops[seg][k]+f*(stops[seg+1][k]-stops[seg][k])) for k in range(4)}
tabs=[tween(i/(N-1)) for i in range(N)]
mixedinks,cgswatches,tab_fill=[],[],[]
for i,mix in enumerate(tabs):
    nz=[(k,mix[k]) for k in TRAP if mix[k]>0]
    if len(nz)==1: tab_fill.append(COLOR_REF[nz[0][0]]); continue
    name,cgs=f"tab_{i:02d}",f"uTABcgs{i}"
    il=" ".join(enc(INK_REF[k]) for k,_ in nz); pc=" ".join(str(p) for _,p in nz)
    inm=" ".join(enc(INK_NAME[k]) for k,_ in nz); cnm=" ".join(enc(COLOR_NAME[k]) for k,_ in nz)
    cl=" ".join(enc(COLOR_REF[k]) for k,_ in nz)
    mixedinks.append(f'\t<MixedInk Self="MixedInk/{name}" Model="Mixedinkmodel" Space="MixedInk" '
        f'InkList="{il}" InkPercentages="{pc}" BaseColor="n" InkNameList="{inm}" '
        f'MixedInkSpotColorNameList="{cnm}" MixedInkSpotColorList="{cl}" Name="{name}" '
        f'ColorEditable="true" ColorRemovable="true" Visible="true" SwatchCreatorID="7937" '
        f'SwatchColorGroupReference="{cgs}" />')
    cgswatches.append(f'\t\t<ColorGroupSwatch Self="{cgs}" SwatchItemRef="MixedInk/{name}" />')
    tab_fill.append(f"MixedInk/{name}")

if os.path.exists(OUT): shutil.rmtree(OUT)
shutil.copytree(SRC, OUT)
def set_attr(tag,n,v):
    return re.sub(rf'\b{n}="[^"]*"',f'{n}="{v}"',tag) if re.search(rf'\b{n}="',tag) else tag[:-1]+f' {n}="{v}"'+tag[-1]

def mirror_block(block,new_self,new_story=None):
    """reflect a page item about the spine (x=0): new Self, negate every x
    (anchors + ItemTransform tx); optionally repoint ParentStory."""
    b=re.sub(r'(\bSelf=")[^"]*(")',rf'\g<1>{new_self}\g<2>',block,count=1)
    if new_story: b=re.sub(r'(\bParentStory=")[^"]*(")',rf'\g<1>{new_story}\g<2>',b,count=1)
    b=re.sub(r'ItemTransform="([^"]+)"',
             lambda m:'ItemTransform="'+" ".join(str(-float(v)) if i==4 else v
                     for i,v in enumerate(m.group(1).split()))+'"',b)
    b=re.sub(r'(Anchor|LeftDirection|RightDirection)="([-\d.eE+]+) ([-\d.eE+]+)"',
             lambda m:f'{m.group(1)}="{-float(m.group(2))} {m.group(3)}"',b)
    return b

def set_number(story,digit):
    """put a literal digit into the (empty) tab-number CharacterStyleRange."""
    return re.sub(r'<CharacterStyleRange([^>]*?)\s*/>',
                  rf'<CharacterStyleRange\1><Content>{digit}</Content></CharacterStyleRange>',
                  story, count=1)

new_stories=[]

TABFILL_RE=r'FillColor="(?:MixedInk/tab_\d+|Color/PANTONE 292 U|Color/Black)"'
def corners(block):
    a,b,c,d,tx,ty=map(float,re.search(r'ItemTransform="([^"]+)"',block).group(1).split())
    frame=block.split('<PDF',1)[0]
    return [(a*float(p.split()[0])+c*float(p.split()[1])+tx, b*float(p.split()[0])+d*float(p.split()[1])+ty)
            for p in re.findall(r'Anchor="([^"]+)"',frame)]

def rebuild_tab(block):
    """scale y about Y0, keep x, identity transform, recolour by new slot."""
    pts=corners(block); ys=[p[1] for p in pts]; xs=[p[0] for p in pts]
    idx=SLOT(min(ys))
    x0,x1=min(xs),max(xs); ny0,ny1=SY(min(ys)),SY(max(ys))
    quad=[(x1,ny0),(x0,ny0),(x0,ny1),(x1,ny1)]
    pa="".join(f'<PathPointType Anchor="{x} {y}" LeftDirection="{x} {y}" RightDirection="{x} {y}" />' for x,y in quad)
    open_tag=re.match(r'<Rectangle\b[^>]*>',block).group(0)
    nt=set_attr(open_tag,"ItemTransform","1 0 0 1 0 0"); nt=set_attr(nt,"FillColor",tab_fill[idx]); nt=set_attr(nt,"FillTint","100")
    return (nt+'<Properties><PathGeometry><GeometryPathType PathOpen="false"><PathPointArray>'
            +pa+'</PathPointArray></GeometryPathType></PathGeometry></Properties></Rectangle>')

def reposition_number(tag):
    it=list(map(float,re.search(r'ItemTransform="([^"]+)"',tag).group(1).split()))
    ty=it[5]
    it[5]=ty+(SY(ty)-ty)          # scale the frame origin about Y0
    return set_attr(tag,"ItemTransform"," ".join(str(round(v,6)) for v in it))

# ---- 1. delete chapter masters for slots 18..25, respace kept ones ----------
deleted_masters=[]
for f in glob.glob(OUT+"/MasterSpreads/*.xml"):
    t=open(f,encoding='utf-8').read()
    self=re.search(r'Self="([^"]+)"',t).group(1)
    is_chapter = self!="u1dc4d" and re.search(TABFILL_RE,t) and 'AppliedMaster="u1dc4d"' in t
    if not is_chapter: continue
    nty=[float(m.split()[-1]) for m in re.findall(r'<TextFrame\b[^>]*ItemTransform="([^"]+)"',t)]
    slot=NSLOT(nty[0]) if nty else 99
    if slot>=N:
        os.remove(f); deleted_masters.append(self); continue
    t=re.sub(r'<Rectangle\b[^>]*>.*?</Rectangle>',
             lambda m: rebuild_tab(m.group(0)) if re.search(TABFILL_RE,m.group(0)) else m.group(0),t,flags=re.S)
    t=re.sub(r'<TextFrame\b[^>]*>',lambda m: reposition_number(m.group(0)),t)
    # re-base off the full-strip BaseTabs onto tab-less Base so ONLY this
    # master's own tab shows (no inherited strip); clear the now-moot overrides.
    t=t.replace('AppliedMaster="u1dc4d"','AppliedMaster="ud5"')
    t=re.sub(r'OverrideList="[^"]*"','OverrideList=""',t)
    # the master owns only a LEFT-page tab+number; since it now inherits no
    # strip, mirror them onto the RIGHT page (own items) so both pages show it.
    tabb=re.search(r'<Rectangle\b[^>]*>.*?</Rectangle>',t,re.S).group(0)
    numb=re.search(r'<TextFrame\b[^>]*>.*?</TextFrame>',t,re.S).group(0)
    srcstory=re.search(r'ParentStory="([^"]+)"',numb).group(1)
    ns=f"uMRs{slot}"
    mtab=mirror_block(tabb,f"uMRt{slot}")
    mnum=mirror_block(numb,f"uMRf{slot}",ns)
    t=re.sub(r'[ \t]*</MasterSpread>',"\n"+mtab+"\n"+mnum+"\n\t</MasterSpread>",t,count=1)
    srcp=OUT+f"/Stories/Story_{srcstory}.xml"
    sst=set_number(open(srcp,encoding='utf-8').read(),str(slot+1))       # digit = position
    open(srcp,'w',encoding='utf-8').write(sst)                            # left number
    open(OUT+f"/Stories/Story_{ns}.xml","w",encoding='utf-8').write(sst.replace(f'Self="{srcstory}"',f'Self="{ns}"'))  # right number
    new_stories.append(ns)
    open(f,'w',encoding='utf-8').write(t)

# ---- 2. BaseTabs: drop slot>=18 tabs+numbers, respace the rest --------------
bt=[f for f in glob.glob(OUT+"/MasterSpreads/*.xml") if 'Self="u1dc4d"' in open(f,encoding='utf-8').read()][0]
t=open(bt,encoding='utf-8').read()
def bt_rect(m):
    blk=m.group(0)
    if not re.search(TABFILL_RE,blk): return blk
    if SLOT(min(p[1] for p in corners(blk)))>=N: return ''      # drop
    return rebuild_tab(blk)
t=re.sub(r'<Rectangle\b[^>]*>.*?</Rectangle>',bt_rect,t,flags=re.S)
def bt_num(m):
    blk=m.group(0)
    ty=float(re.search(r'ItemTransform="([^"]+)"',blk).group(1).split()[-1])
    slot=NSLOT(ty)
    if slot>=N: return ''                                        # drop
    ps=re.search(r'ParentStory="([^"]+)"',blk)                   # fill digit
    if ps and os.path.exists(OUT+f"/Stories/Story_{ps.group(1)}.xml"):
        p=OUT+f"/Stories/Story_{ps.group(1)}.xml"
        content=set_number(open(p,encoding='utf-8').read(),str(slot+1))   # read BEFORE truncating
        open(p,'w',encoding='utf-8').write(content)
    op=re.match(r'<TextFrame\b[^>]*>',blk).group(0)
    return reposition_number(op)+blk[len(op):]
t=re.sub(r'<TextFrame\b[^>]*>.*?</TextFrame>',bt_num,t,flags=re.S)
open(bt,'w',encoding='utf-8').write(t)

# ---- 3. designmap: drop deleted master refs; swap tab swatches --------------
dm=OUT+"/designmap.xml"; d=open(dm,encoding='utf-8').read()
for self in deleted_masters:
    d=re.sub(rf'\s*<idPkg:MasterSpread src="MasterSpreads/MasterSpread_{self}\.xml" />','',d)
d=re.sub(r'\s*<ColorGroupSwatch Self="uTABcgs\d+"[^>]*/>','',d)              # old N=26 tab cgs
d=d.replace("\t</ColorGroup>","\n".join(cgswatches)+"\n\t</ColorGroup>")
open(dm,'w',encoding='utf-8').write(d)
g=OUT+"/Resources/Graphic.xml"; gx=open(g,encoding='utf-8').read()
gx=re.sub(r'\s*<MixedInk Self="MixedInk/tab_\d+"[^>]*/>','',gx)               # old N=26 mixed inks
open(g,'w',encoding='utf-8').write(gx.replace("</idPkg:Graphic>","\n".join(mixedinks)+"\n</idPkg:Graphic>"))

# ---- 4. orphaned-story cleanup (closure from remaining masters + donor) -----
def reads(p): return open(p,encoding='utf-8').read()
seed=set()
for f in glob.glob(OUT+"/MasterSpreads/*.xml")+[OUT+"/Spreads/Spread_u7973e.xml"]:
    seed|=set(re.findall(r'ParentStory="([^"]+)"',reads(f)))
keep=set(); frontier=set(seed)
while frontier:
    s=frontier.pop()
    if s in keep: continue
    keep.add(s); p=OUT+f"/Stories/Story_{s}.xml"
    if os.path.exists(p): frontier|=set(re.findall(r'ParentStory="([^"]+)"',reads(p)))-keep
removed_stories=0
for p in glob.glob(OUT+"/Stories/Story_*.xml"):
    sid=re.search(r'Story_(.+)\.xml$',p).group(1)
    if sid not in keep: os.remove(p); removed_stories+=1
d=open(dm,encoding='utf-8').read()
for m in re.findall(r'<idPkg:Story src="Stories/Story_([^"]+)\.xml" />',d):
    if m not in keep: d=re.sub(rf'\s*<idPkg:Story src="Stories/Story_{m}\.xml" />','',d)
sl=[x for x in re.search(r'StoryList="([^"]*)"',d).group(1).split() if x in keep]
d=re.sub(r'StoryList="[^"]*"',f'StoryList="{" ".join(sl)}"',d,count=1)
# register the cloned right-page number stories (new -> not handled above)
refs="".join(f'\t<idPkg:Story src="Stories/Story_{s}.xml" />\n' for s in new_stories)
d=re.sub(r'(\t<idPkg:Story\b)',refs+r'\1',d,count=1)
d=re.sub(r'StoryList="([^"]*)"',lambda m:f'StoryList="{m.group(1)} '+" ".join(new_stories)+'"',d,count=1)
open(dm,'w',encoding='utf-8').write(d)

# ---- 5. demo donor pages -> slot0 + slot17 ---------------------------------
sp=OUT+"/Spreads/Spread_u7973e.xml"; sx=open(sp,encoding='utf-8').read()
for page,master in {"u79767":"u1e21d","u79768":"u1e432"}.items():
    sx=re.sub(rf'(<Page\b[^>]*Self="{page}"[^>]*AppliedMaster=")[^"]*(")',rf'\g<1>{master}\g<2>',sx)
open(sp,'w',encoding='utf-8').write(sx)

print(f"deleted chapter masters: {len(deleted_masters)}  {deleted_masters}")
print(f"orphaned stories removed: {removed_stories}")
print(f"N={N} pitch={P18:.3f} scale S={S:.4f} | mixed-ink swatches={len(mixedinks)}")
print(f"chapter masters remaining: {len(glob.glob(OUT+'/MasterSpreads/*.xml'))} master files")
