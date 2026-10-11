# -*- coding: utf-8 -*-
import sys, os, json, collections, datetime as dt
sys.path.insert(0,'.')
import synth_data as SD
MOD=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cc=json.load(open(os.path.join(MOD,'data','cloud-correction.json'),encoding='utf-8'))
lows=set(cc['days'])
print('低探测日 %d 天'%len(lows))
allf=SD.load(2024)+SD.load(2025)
acc=collections.defaultdict(set)
for f in allf: acc['%.2f,%.2f'%(f['lat'],f['lng'])].add(f['date'])
def segs(dates, gap, skip=None):
    ds=sorted(dates); out=[]; s=ds[0]; prev=ds[0]
    for d in ds[1:]:
        dd=(dt.date.fromisoformat(d)-dt.date.fromisoformat(prev)).days
        if skip is None:
            ok = dd<=gap
        else:
            # 中间隔着的日子若全是盲区日，则不算中断
            mid=[(dt.date.fromisoformat(prev)+dt.timedelta(days=k)).isoformat() for k in range(1,dd)]
            ok = dd<=gap or (mid and all(m in skip for m in mid))
        if ok: prev=d
        else: out.append((s,prev)); s=d; prev=d
    out.append((s,prev)); return out
def L(a,b): return (dt.date.fromisoformat(b)-dt.date.fromisoformat(a)).days+1
rows=[]
for k,ds in acc.items():
    if len(ds)<10: continue
    a=max(L(*x) for x in segs(ds,2))
    b=max(L(*x) for x in segs(ds,2,skip=lows))
    rows.append((k,len(ds),a,b))
rows.sort(key=lambda r:-r[3])
print()
print('=== 连续段：原口径（间隔≤2天）vs 云校正（跳过低探测日）===')
print('%-14s %6s %10s %10s %8s'%('点位','出现天','原最长','校正后','增幅'))
for k,n,a,b in rows[:15]:
    print('%-14s %6d %10d %10d %+7.1f%%'%(k,n,a,b,(b/a-1)*100 if a else 0))
print()
import statistics
print('全体 %d 个点位：原最长中位 %.0f 天 → 校正后 %.0f 天（+%.0f%%）'%(
    len(rows), statistics.median([r[2] for r in rows]), statistics.median([r[3] for r in rows]),
    (statistics.median([r[3] for r in rows])/statistics.median([r[2] for r in rows])-1)*100))
print('最长：原 %d 天 → 校正后 %d 天'%(max(r[2] for r in rows), max(r[3] for r in rows)))
for th in (30,60,90,120):
    print('  连续≥%d天：原 %d 个 → 校正后 %d 个'%(th,
        sum(1 for r in rows if r[2]>=th), sum(1 for r in rows if r[3]>=th)))
