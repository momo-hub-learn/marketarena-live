#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ["astra", "jev", "deepseek", "quant", "hybrid"]
NAMES = {"astra":"Astra","jev":"Jev","deepseek":"DeepSeek","quant":"Quant","hybrid":"Astra + Jev"}
STARTING_CAPITAL = 10000.0

def readj(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def writej(p, o):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main():
    persistent = readj(ROOT / "season" / "season0_accounts.json")
    stats = {
        cid: {
            "id": cid,
            "name": NAMES[cid],
            "model_id": None,
            "settled_rounds": 0,
            "revealed_rounds": 0,
            "no_shows": 0,
            "total_ai_cost_usd": 0.0,
            "latencies_ms": [],
            "actions": Counter(),
            "curve": [{"round": "START", "season_equity_usd": STARTING_CAPITAL}],
        }
        for cid in IDS
    }
    rounds = []

    dirs = sorted(
        [p for p in (ROOT / "rounds").iterdir() if p.is_dir() and (p / "public_state.json").exists()],
        key=lambda p: (readj(p / "public_state.json").get("packet_frozen_at") or "", p.name),
    )

    for rd in dirs:
        state = readj(rd / "public_state.json")
        if not state.get("packet_frozen_at"):
            continue
        reveal = readj(rd / "reveal.json") if (rd / "reveal.json").exists() else {"contestants": {}, "no_shows": {}}
        settle = readj(rd / "settlement.json") if (rd / "settlement.json").exists() else None
        row = {
            "round_id": state["round_id"],
            "phase": state.get("phase"),
            "packet_frozen_at": state.get("packet_frozen_at"),
            "persistent_accounts": bool(state.get("persistent_accounts")),
            "accounts": {},
        }

        for cid in IDS:
            cstate = (state.get("contestants") or {}).get(cid) or {}
            s = stats[cid]
            s["model_id"] = s["model_id"] or cstate.get("model_id")
            if cstate.get("status") == "NO_SHOW" or cid in (reveal.get("no_shows") or {}):
                s["no_shows"] += 1

            r = (reveal.get("contestants") or {}).get(cid)
            if r:
                s["revealed_rounds"] += 1
                bundle = r["bundle"]
                lat = bundle.get("latency_ms")
                if lat is not None:
                    s["latencies_ms"].append(float(lat))
                s["total_ai_cost_usd"] += float((bundle.get("usage") or {}).get("cost") or 0)
                for d in (bundle.get("decisions") or {}).values():
                    s["actions"][d.get("action", "UNKNOWN")] += 1

            if settle and cid in (settle.get("accounts") or {}):
                a = settle["accounts"][cid]
                if settle.get("status") == "SETTLED":
                    s["settled_rounds"] += 1
                    # Only persistent-era settlements form the authoritative
                    # continuous-account curve. R0003 is the migration anchor.
                    if state["round_id"] == "S0-R0003-LIVE" or state.get("persistent_accounts"):
                        s["curve"].append({
                            "round": state["round_id"],
                            "season_equity_usd": round(float(a.get("equity_usd") or STARTING_CAPITAL), 6),
                        })
                row["accounts"][cid] = {
                    "equity_usd": a.get("equity_usd"),
                    "round_pnl_usd": a.get("round_pnl_usd", a.get("pnl_usd")),
                    "season_pnl_usd": a.get("pnl_usd"),
                    "return_pct": a.get("return_pct"),
                    "status": a.get("status") or settle.get("status"),
                }
        rounds.append(row)

    contestants = []
    for cid in IDS:
        s = stats[cid]
        account = persistent["accounts"][cid]
        equity = float(account.get("equity_usd", STARTING_CAPITAL))
        lats = s.pop("latencies_ms")
        acts = s["actions"]
        s["actions"] = dict(acts)
        total_actions = sum(acts.values())
        s["avg_latency_ms"] = round(sum(lats) / len(lats), 3) if lats else None
        s["abstain_rate"] = round(acts.get("ABSTAIN", 0) / total_actions, 6) if total_actions else None
        s["season_equity_usd"] = round(equity, 6)
        s["total_pnl_usd"] = round(equity - STARTING_CAPITAL, 6)
        s["total_return_pct"] = round((equity / STARTING_CAPITAL - 1) * 100, 6)
        s["cash_usd"] = round(float(account.get("cash_usd", 0.0)), 6)
        s["position_count"] = len(account.get("positions") or {})
        s["source_round"] = account.get("source_round")
        s["total_ai_cost_usd"] = round(s["total_ai_cost_usd"], 9)
        contestants.append(s)

    contestants.sort(key=lambda x: (-x["season_equity_usd"], x["no_shows"], x["total_ai_cost_usd"]))
    for rank, c in enumerate(contestants, 1):
        c["rank"] = rank

    out = {
        "schema": "marketarena.season.v2",
        "season": "Season 0 — Fast & Slow",
        "account_mode": "persistent",
        "starting_capital_usd": STARTING_CAPITAL,
        "ranking_metric": "Current persistent paper equity from the original $10,000 account. No-show count, cost and latency are reported separately.",
        "account_ledger_source_round": persistent.get("migration", {}).get("source_round"),
        "contestants": contestants,
        "rounds": rounds,
    }
    writej(ROOT / "season" / "season0.json", out)

if __name__ == "__main__":
    main()
