#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
TICKERS=["AAPL","NVDA","AMZN","META"]
SLIPPAGE_BPS=5
ADD_PCT=0.10

def iso(ts: dt.datetime|None=None):
    return (ts or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")

def readj(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

def writej(p: Path,o: Any):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def http_json(url: str):
    req=urllib.request.Request(url,headers={"User-Agent":"MarketArena/0.2"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read())

def bars(ticker: str):
    # Five days lets a pre-market/after-hours reveal settle against the next
    # *future* regular-session bar without ever falling back to a past close.
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1m&range=5d&includePrePost=false"
    d=http_json(url)["chart"]["result"][0]
    ts=d.get("timestamp") or []
    closes=((d.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    pairs=[(int(t),float(c)) for t,c in zip(ts,closes) if t is not None and c is not None]
    return pairs,d.get("meta") or {},url

def ceil_minute_epoch(ts: dt.datetime):
    x=int(ts.timestamp())
    return ((x+59)//60)*60

def first_future_bar(pairs, epoch):
    for t,p in pairs:
        if t>=epoch:
            return t,p
    return None

def latest_regular_bar(pairs, meta):
    # includePrePost=false means returned bars are regular-session bars.
    if not pairs:
        raise RuntimeError("no regular market bars")
    return pairs[-1]

def append_mark_history(rd: Path, packet: dict, out: dict):
    path=rd/"marks.json"
    if path.exists():
        history=readj(path)
    else:
        start=float(packet["portfolio"]["equity_usd"])
        history={
            "schema":"marketarena.marks.v1",
            "round_id":packet["round_id"],
            "points":[{
                "ts":packet["frozen_at"],
                "status":"START",
                "equity_usd":{cid:start for cid in ["astra","jev","deepseek","quant","hybrid"]}
            }]
        }
    point={
        "ts":out["generated_at"],
        "status":out["status"],
        "market_ts":max((x.get("mark") or {}).get("ts","") for x in out["market"].values()),
        "equity_usd":{cid:round(float(a["equity_usd"]),6) for cid,a in out["accounts"].items()}
    }
    last=history["points"][-1] if history["points"] else None
    if not last or last.get("market_ts")!=point["market_ts"] or last.get("status")!=point["status"]:
        history["points"].append(point)
    writej(path,history)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--round-id",required=True)
    args=ap.parse_args()
    rd=ROOT/"rounds"/args.round_id
    state=readj(rd/"public_state.json")
    packet=readj(rd/"packet.json")
    reveal=readj(rd/"reveal.json")
    prior=readj(rd/"settlement.json") if (rd/"settlement.json").exists() else None

    revealed_at=dt.datetime.fromisoformat(reveal["revealed_at"].replace("Z","+00:00"))
    exec_epoch=ceil_minute_epoch(revealed_at)
    market={}
    pending_execution=False

    for t in TICKERS:
        pairs,meta,url=bars(t)
        prior_exec=((prior or {}).get("market",{}).get(t,{}) or {}).get("execution_reference")
        if prior_exec:
            et=dt.datetime.fromisoformat(prior_exec["ts"].replace("Z","+00:00"))
            ep=float(prior_exec["price"])
            execution={"ts":iso(et),"price":ep}
        else:
            future=first_future_bar(pairs,exec_epoch)
            if future is None:
                execution=None
                pending_execution=True
            else:
                et,ep=future
                execution={"ts":iso(dt.datetime.fromtimestamp(et,dt.timezone.utc)),"price":ep}
        mt,mp=latest_regular_bar(pairs,meta)
        reg=((meta.get("currentTradingPeriod") or {}).get("regular") or {})
        market[t]={
            "execution_reference":execution,
            "mark":{"ts":iso(dt.datetime.fromtimestamp(mt,dt.timezone.utc)),"price":mp},
            "regular_start_epoch":int(reg.get("start") or 0),
            "regular_end_epoch":int(reg.get("end") or 0),
            "source":url
        }

    now=int(dt.datetime.now(dt.timezone.utc).timestamp())
    regular_end=max(x["regular_end_epoch"] for x in market.values())
    settled=bool(not pending_execution and regular_end and now>=regular_end)
    status="PENDING_EXECUTION" if pending_execution else ("SETTLED" if settled else "INTRADAY")

    accounts={}
    start_equity=float(packet["portfolio"]["equity_usd"])
    for cid,row in reveal["contestants"].items():
        cash=start_equity; positions={}; orders=[]
        for t in TICKERS:
            d=row["bundle"]["decisions"][t]
            action=d["action"]
            execution=market[t]["execution_reference"]
            if action=="ADD" and execution is None:
                orders.append({"ticker":t,"action":"ADD","status":"PENDING_EXECUTION"})
                continue
            if action=="ADD":
                ref=float(execution["price"])
                notional=start_equity*ADD_PCT
                fill=ref*(1+SLIPPAGE_BPS/10000)
                qty=notional/fill
                cash-=notional
                positions[t]=positions.get(t,0)+qty
                orders.append({"ticker":t,"action":"ADD","status":"FILLED","reference_price":ref,"fill_price":fill,"slippage_bps":SLIPPAGE_BPS,"notional_usd":notional,"qty":qty})
            elif action in ("REDUCE","EXIT"):
                orders.append({"ticker":t,"action":action,"status":"BLOCKED","reason":"No existing long position; Season 0 forbids shorting."})
            else:
                orders.append({"ticker":t,"action":action,"status":"NO_ORDER"})

        holdings=0.0; marks={}
        for t,q in positions.items():
            mp=float(market[t]["mark"]["price"])
            v=q*mp; holdings+=v
            marks[t]={"qty":q,"mark_price":mp,"market_value":v}
        equity=cash+holdings
        accounts[cid]={
            "name":state["contestants"][cid]["name"],
            "model_id":row["bundle"]["model_id"],
            "cash_usd":cash,"holdings_usd":holdings,"equity_usd":equity,
            "pnl_usd":equity-start_equity,
            "return_pct":(equity/start_equity-1)*100,
            "orders":orders,"positions":marks,
            "ai_cost_usd":float((row["bundle"].get("usage") or {}).get("cost") or 0),
            "decision_latency_ms":row["bundle"].get("latency_ms")
        }

    for cid,err in (reveal.get("no_shows") or {}).items():
        accounts[cid]={
            "name":state["contestants"][cid]["name"],
            "model_id":state["contestants"][cid]["model_id"],
            "status":"NO_SHOW","cash_usd":start_equity,"holdings_usd":0.0,
            "equity_usd":start_equity,"pnl_usd":0.0,"return_pct":0.0,
            "orders":[],"positions":{},"error":err
        }

    out={
        "schema":"marketarena.settlement.v2",
        "round_id":args.round_id,
        "status":status,
        "execution_rule":"First FUTURE regular-session 1m bar at/after the first whole minute following reveal. Never backfill from a pre-decision bar. ADD receives 5 bps adverse paper slippage.",
        "mark_rule":"Latest available regular-session 1m close; final after regular market end.",
        "generated_at":iso(),"market":market,"accounts":accounts
    }
    writej(rd/"settlement.json",out)
    append_mark_history(rd,packet,out)
    state["phase"]="SETTLED" if settled else ("WAITING_FOR_OPEN" if pending_execution else "TRADING")
    state["settlement_status"]=status
    state["updated_at"]=iso()
    writej(rd/"public_state.json",state)
    print(json.dumps({"round_id":args.round_id,"status":status,"accounts":{k:round(v["equity_usd"],4) for k,v in accounts.items()}}))

if __name__=="__main__":
    main()
