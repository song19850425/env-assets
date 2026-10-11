# -*- coding: utf-8 -*-
import os, json, collections, statistics, random, sys
MOD=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fires=json.load(open(os.path.join(MOD,'data','north6','fires-north6.json'),encoding='utf-8'))
print('六省火点', len(fires))
byp=collections.defaultdict(list)
for f in fires: byp[f['province']].append(f)
P_H=(12.0,24.0,24.0); P_E=(0.08,0.30,0.15); P_V=(9.0,25.0,20.0)
rng=random.Random(7)
def mc(mwd, n=8000):
    out=[]
    for _ in range(n):
        h=rng.triangular(*P_H); e=rng.triangular(*P_E); v=rng.triangular(*P_V)
        out.append(mwd*h*3600/e/v/1e7)
    out.sort(); return out
print()
print('%-6s %9s %8s %9s %14s %10s'%('省/市','火点','点位','持续点位','Σ(FRP×天)','折煤万吨/两年(P50)'))
res={}
for pv in ['河北','山西','山东','河南','天津','北京']:
    fs=byp[pv]
    acc=collections.defaultdict(lambda:{'days':set(),'frps':[]})
    for f in fs:
        a=acc['%.2f,%.2f'%(f['lat'],f['lng'])]
        a['days'].add(f['date']); a['frps'].append(f['frp'])
    hot={k:a for k,a in acc.items() if len(a['days'])>=10}
    mwd=sum(statistics.median(a['frps'])*len(a['days']) for a in hot.values())
    o=mc(mwd)
    q=lambda x: o[int(len(o)*x)]
    res[pv]=dict(fire=len(fs),pts=len(acc),hot=len(hot),mwd=round(mwd,1),
                 coal50=round(q(.5),1),coal10=round(q(.1),1),coal90=round(q(.9),1))
    print('%-6s %9d %8d %9d %14.1f %10.1f'%(pv,len(fs),len(acc),len(hot),mwd,q(.5)))
tot=sum(r['mwd'] for r in res.values())
o=mc(tot); q=lambda x: o[int(len(o)*x)]
print()
print('六省合计：持续点位 %d 个｜Σ(FRP×天) %.0f｜折煤 P10/P50/P90 = %.0f / %.0f / %.0f 万吨/两年'%(
    sum(r['hot'] for r in res.values()), tot, q(.1), q(.5), q(.9)))
print('  年均 %.1f 万吨煤'%(q(.5)/2))
json.dump(res, open(os.path.join(MOD,'data','north6','emission-by-prov.json'),'w',encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('已写出 emission-by-prov.json')
