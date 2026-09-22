#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
IDS=["astra","jev","deepseek","quant","hybrid"]

def readj(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def writej(p,o):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    stats={i:{
        "id":i,"name":None,"model_id":None,"settled_rounds":0,"revealed_rounds":0,"no_shows":0,
        "total_pnl_usd":0.0,"total_return_pct":0.0,"total_ai_cost_usd":0.0,
        "latencies_ms":[],"actions":Counter(),"curve":[{"round":"START","season_equity_usd":10000.0}]
    } for i in IDS}
    rounds=[]
    dirs=sorted([p for p in (ROOT/"rounds").iterdir() if p.is_dir() and (p/"public_state.json").exists()])
    for rd in dirs:
        state=readj(rd/"public_state.json")
        reveal=readj(rd/"reveal.json") if (rd/"reveal.json").exists() else {"contestants":{},"no_shows":{}}
        settle=readj(rd/"settlement.json") if (rd/"settlement.json").exists() else None
        row={"round_id":state["round_id"],"phase":state.get("phase"),"packet_frozen_at":state.get("packet_frozen_at"),"accounts":{}}
        for cid in IDS:
            cstate=(state.get("contestants") or {}).get(cid) or {}
            s=stats[cid]
            s["name"]=s["name"] or cstate.get("name") or cid
            s["model_id"]=s["model_id"] or cstate.get("model_id")
            if cstate.get("status")=="NO_SHOW" or cid in (reveal.get("no_shows") or {}):
                s["no_shows"]+=1
            r=(reveal.get("contestants") or {}).get(cid)
            if r:
                s["revealed_rounds"]+=1
                bundle=r["bundle"]
                lat=bundle.get("latency_ms")
                if lat is not None: s["latencies_ms"].append(float(lat))
                cost=float((bundle.get("usage") or {}).get("cost") or 0)
                s["total_ai_cost_usd"]+=cost
                for d in (bundle.get("decisions") or {}).values():
                    s["actions"][d.get("action","UNKNOWN")]+=1
            if settle and cid in (settle.get("accounts") or {}):
                a=settle["accounts"][cid]
                if settle.get("status")=="SETTLED":
                    s["settled_rounds"]+=1
                    s["total_pnl_usd"]+=float(a.get("pnl_usd") or 0)
                    s["total_return_pct"]+=float(a.get("return_pct") or 0)
                    season_eq=10000.0+s["total_pnl_usd"]
                    s["curve"].append({"round":state["round_id"],"season_equity_usd":round(season_eq,6)})
                row["accounts"][cid]={
                    "equity_usd":a.get("equity_usd"),
                    "pnl_usd":a.get("pnl_usd"),
                    "return_pct":a.get("return_pct"),
                    "status":a.get("status") or settle.get("status")
                }
        rounds.append(row)
    contestants=[]
    for cid in IDS:
        s=stats[cid]
        l=s.pop("latencies_ms")
        acts=s["actions"]; s["actions"]=dict(acts)
        total_actions=sum(acts.values())
        s["avg_latency_ms"]=round(sum(l)/len(l),3) if l else None
        s["abstain_rate"]=round(acts.get("ABSTAIN",0)/total_actions,6) if total_actions else None
        s["total_pnl_usd"]=round(s["total_pnl_usd"],6)
        s["total_return_pct"]=round(s["total_return_pct"],6)
        s["total_ai_cost_usd"]=round(s["total_ai_cost_usd"],9)
        contestants.append(s)
    contestants.sort(key=lambda x:(-x["total_pnl_usd"],x["no_shows"],x["total_ai_cost_usd"]))
    for i,c in enumerate(contestants,1): c["rank"]=i
    out={
        "schema":"marketarena.season.v1",
        "season":"Season 0 — Fast & Slow",
        "ranking_metric":"Total settled-round paper P&L. No-show accounts remain flat at starting paper equity and are counted separately.",
        "contestants":contestants,
        "rounds":rounds
    }
    writej(ROOT/"season"/"season0.json",out)

if __name__=="__main__":
    main()
