#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, math, urllib.parse, urllib.request
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
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def http_json(url: str):
    req=urllib.request.Request(url,headers={"User-Agent":"MarketArena/0.1"})
    with urllib.request.urlopen(req,timeout=30) as r: return json.loads(r.read())

def bars(ticker: str):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1m&range=1d&includePrePost=false"
    d=http_json(url)["chart"]["result"][0]
    ts=d.get("timestamp") or []
    closes=((d.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    pairs=[(int(t),float(c)) for t,c in zip(ts,closes) if t is not None and c is not None]
    meta=d.get("meta") or {}
    return pairs,meta,url

def ceil_minute_epoch(ts: dt.datetime):
    x=int(ts.timestamp())
    return ((x+59)//60)*60

def first_bar_at_or_after(pairs, epoch):
    for t,p in pairs:
        if t>=epoch: return t,p
    if pairs: return pairs[-1]
    raise RuntimeError("no market bars")

def latest_regular_bar(pairs, meta):
    reg=((meta.get("currentTradingPeriod") or {}).get("regular") or {})
    start=int(reg.get("start") or 0); end=int(reg.get("end") or 2**31)
    eligible=[x for x in pairs if start<=x[0]<end]
    return eligible[-1] if eligible else pairs[-1]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--round-id",required=True)
    args=ap.parse_args()
    rd=ROOT/"rounds"/args.round_id
    state=readj(rd/"public_state.json"); packet=readj(rd/"packet.json"); reveal=readj(rd/"reveal.json")
    revealed_at=dt.datetime.fromisoformat(reveal["revealed_at"].replace("Z","+00:00"))
    exec_epoch=ceil_minute_epoch(revealed_at)
    market={}
    for t in TICKERS:
        pairs,meta,url=bars(t)
        et,ep=first_bar_at_or_after(pairs,exec_epoch)
        mt,mp=latest_regular_bar(pairs,meta)
        reg=((meta.get("currentTradingPeriod") or {}).get("regular") or {})
        market[t]={
            "execution_reference":{"ts":iso(dt.datetime.fromtimestamp(et,dt.timezone.utc)),"price":ep},
            "mark":{"ts":iso(dt.datetime.fromtimestamp(mt,dt.timezone.utc)),"price":mp},
            "regular_end_epoch":int(reg.get("end") or 0),
            "source":url
        }
    now=int(dt.datetime.now(dt.timezone.utc).timestamp())
    regular_end=max(x["regular_end_epoch"] for x in market.values())
    settled=bool(regular_end and now>=regular_end)
    accounts={}
    start_equity=float(packet["portfolio"]["equity_usd"])
    for cid,row in reveal["contestants"].items():
        cash=start_equity; positions={}; orders=[]
        for t in TICKERS:
            d=row["bundle"]["decisions"][t]; action=d["action"]; ref=market[t]["execution_reference"]["price"]
            if action=="ADD":
                notional=start_equity*ADD_PCT
                fill=ref*(1+SLIPPAGE_BPS/10000)
                qty=notional/fill
                cash-=notional; positions[t]=positions.get(t,0)+qty
                orders.append({"ticker":t,"action":"ADD","status":"FILLED","reference_price":ref,"fill_price":fill,"slippage_bps":SLIPPAGE_BPS,"notional_usd":notional,"qty":qty})
            elif action in ("REDUCE","EXIT"):
                orders.append({"ticker":t,"action":action,"status":"BLOCKED","reason":"No existing long position; Season 0 forbids shorting."})
            else:
                orders.append({"ticker":t,"action":action,"status":"NO_ORDER"})
        holdings=0.0
        marks={}
        for t,q in positions.items():
            mp=market[t]["mark"]["price"]; v=q*mp; holdings+=v; marks[t]={"qty":q,"mark_price":mp,"market_value":v}
        equity=cash+holdings
        accounts[cid]={
            "name":state["contestants"][cid]["name"],
            "model_id":row["bundle"]["model_id"],
            "cash_usd":cash,
            "holdings_usd":holdings,
            "equity_usd":equity,
            "pnl_usd":equity-start_equity,
            "return_pct":(equity/start_equity-1)*100,
            "orders":orders,
            "positions":marks,
            "ai_cost_usd":float((row["bundle"].get("usage") or {}).get("cost") or 0),
            "decision_latency_ms":row["bundle"].get("latency_ms")
        }
    for cid,err in (reveal.get("no_shows") or {}).items():
        accounts[cid]={
            "name":state["contestants"][cid]["name"],
            "model_id":state["contestants"][cid]["model_id"],
            "status":"NO_SHOW",
            "cash_usd":start_equity,"holdings_usd":0.0,"equity_usd":start_equity,
            "pnl_usd":0.0,"return_pct":0.0,"orders":[],"positions":{},"error":err
        }
    out={
        "schema":"marketarena.settlement.v1",
        "round_id":args.round_id,
        "status":"SETTLED" if settled else "INTRADAY",
        "execution_rule":"First regular-session 1m bar at/after the first whole minute following reveal; ADD receives 5 bps adverse paper slippage.",
        "mark_rule":"Latest available regular-session 1m close; becomes final after regular market end.",
        "generated_at":iso(),
        "market":market,
        "accounts":accounts
    }
    writej(rd/"settlement.json",out)
    state["phase"]="SETTLED" if settled else "TRADING"
    state["settlement_status"]=out["status"]; state["updated_at"]=iso()
    writej(rd/"public_state.json",state)
    print(json.dumps({"round_id":args.round_id,"status":out["status"],"accounts":{k:round(v["equity_usd"],4) for k,v in accounts.items()}}))

if __name__=="__main__": main()
