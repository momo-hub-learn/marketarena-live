#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEASON_ACCOUNTS = ROOT / "season" / "season0_accounts.json"
TICKERS = ["AAPL", "NVDA", "AMZN", "META"]
IDS = ["astra", "jev", "deepseek", "quant", "hybrid"]
SLIPPAGE_BPS = 5
ACTION_PCT = 0.10
STARTING_CAPITAL = 10000.0

def iso(ts: dt.datetime | None = None) -> str:
    return (ts or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")

def readj(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))

def writej(p: Path, o: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "MarketArena/0.3"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def bars(ticker: str):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(ticker)}?interval=1m&range=5d&includePrePost=false"
    )
    d = http_json(url)["chart"]["result"][0]
    ts = d.get("timestamp") or []
    closes = ((d.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    pairs = [(int(t), float(c)) for t, c in zip(ts, closes) if t is not None and c is not None]
    return pairs, d.get("meta") or {}, url

def ceil_minute_epoch(ts: dt.datetime) -> int:
    x = int(ts.timestamp())
    return ((x + 59) // 60) * 60

def first_future_bar(pairs, epoch):
    for t, p in pairs:
        if t >= epoch:
            return t, p
    return None

def latest_regular_bar(pairs):
    if not pairs:
        raise RuntimeError("no regular market bars")
    return pairs[-1]

def copy_positions(raw: dict[str, Any]) -> dict[str, dict[str, float]]:
    out = {}
    for ticker, p in (raw or {}).items():
        qty = float(p.get("qty", 0.0))
        if qty <= 0:
            continue
        out[ticker] = {
            "qty": qty,
            "avg_cost": float(p.get("avg_cost", p.get("mark_price", 0.0))),
        }
    return out

def apply_action(
    *,
    ticker: str,
    action: str,
    execution: dict[str, Any] | None,
    start_equity: float,
    cash: float,
    positions: dict[str, dict[str, float]],
    realized_pnl: float,
):
    if action in ("HOLD", "ABSTAIN"):
        return cash, positions, realized_pnl, {"ticker": ticker, "action": action, "status": "NO_ORDER"}

    if execution is None:
        return cash, positions, realized_pnl, {"ticker": ticker, "action": action, "status": "PENDING_EXECUTION"}

    ref = float(execution["price"])
    current = positions.get(ticker)
    current_qty = float((current or {}).get("qty", 0.0))
    current_cost = float((current or {}).get("avg_cost", 0.0))

    if action == "ADD":
        notional = min(start_equity * ACTION_PCT, cash)
        if notional <= 1e-9:
            return cash, positions, realized_pnl, {
                "ticker": ticker, "action": action, "status": "BLOCKED", "reason": "Insufficient cash; leverage is forbidden."
            }
        fill = ref * (1 + SLIPPAGE_BPS / 10000)
        qty = notional / fill
        new_qty = current_qty + qty
        new_avg = ((current_qty * current_cost) + (qty * fill)) / new_qty if new_qty else fill
        positions[ticker] = {"qty": new_qty, "avg_cost": new_avg}
        cash -= notional
        return cash, positions, realized_pnl, {
            "ticker": ticker, "action": action, "status": "FILLED",
            "reference_price": ref, "fill_price": fill, "slippage_bps": SLIPPAGE_BPS,
            "notional_usd": notional, "qty": qty,
        }

    if current_qty <= 1e-12:
        return cash, positions, realized_pnl, {
            "ticker": ticker, "action": action, "status": "BLOCKED",
            "reason": "No existing long position; Season 0 forbids shorting."
        }

    fill = ref * (1 - SLIPPAGE_BPS / 10000)
    if action == "REDUCE":
        target_notional = start_equity * ACTION_PCT
        qty = min(current_qty, target_notional / fill)
    elif action == "EXIT":
        qty = current_qty
    else:
        raise ValueError(f"unsupported action: {action}")

    proceeds = qty * fill
    cash += proceeds
    realized_pnl += (fill - current_cost) * qty
    remain = current_qty - qty
    if remain <= 1e-12:
        positions.pop(ticker, None)
    else:
        positions[ticker] = {"qty": remain, "avg_cost": current_cost}

    return cash, positions, realized_pnl, {
        "ticker": ticker, "action": action, "status": "FILLED",
        "reference_price": ref, "fill_price": fill, "slippage_bps": SLIPPAGE_BPS,
        "notional_usd": proceeds, "qty": qty,
    }

def account_after_actions(
    *,
    cid: str,
    start: dict[str, Any],
    bundle: dict[str, Any] | None,
    error: str | None,
    market: dict[str, Any],
    state: dict[str, Any],
):
    cash = float(start.get("cash_usd", 0.0))
    start_equity = float(start.get("equity_usd", cash))
    realized = float(start.get("realized_pnl_usd", 0.0))
    positions = copy_positions(start.get("positions") or {})
    orders = []

    if bundle is not None:
        for ticker in TICKERS:
            action = bundle["decisions"][ticker]["action"]
            cash, positions, realized, order = apply_action(
                ticker=ticker, action=action, execution=market[ticker]["execution_reference"],
                start_equity=start_equity, cash=cash, positions=positions, realized_pnl=realized,
            )
            orders.append(order)

    holdings = 0.0
    marked = {}
    for ticker, p in positions.items():
        price = float(market[ticker]["mark"]["price"])
        qty = float(p["qty"])
        value = qty * price
        holdings += value
        marked[ticker] = {
            "qty": qty,
            "avg_cost": float(p["avg_cost"]),
            "mark_price": price,
            "market_value": value,
            "unrealized_pnl_usd": (price - float(p["avg_cost"])) * qty,
        }

    equity = cash + holdings
    result = {
        "name": state["contestants"][cid]["name"],
        "model_id": bundle.get("model_id") if bundle else state["contestants"][cid]["model_id"],
        "round_start_equity_usd": start_equity,
        "cash_usd": cash,
        "holdings_usd": holdings,
        "equity_usd": equity,
        "round_pnl_usd": equity - start_equity,
        "pnl_usd": equity - STARTING_CAPITAL,
        "return_pct": (equity / STARTING_CAPITAL - 1) * 100,
        "realized_pnl_usd": realized,
        "orders": orders,
        "positions": marked,
        "ai_cost_usd": float(((bundle or {}).get("usage") or {}).get("cost") or 0),
        "decision_latency_ms": (bundle or {}).get("latency_ms"),
    }
    if error is not None:
        result["status"] = "NO_SHOW"
        result["error"] = error
        result["orders"] = []
    return result

def append_mark_history(rd: Path, accounts_before: dict[str, Any], out: dict[str, Any]) -> None:
    path = rd / "marks.json"
    if path.exists():
        history = readj(path)
    else:
        history = {
            "schema": "marketarena.marks.v2",
            "round_id": out["round_id"],
            "points": [{
                "ts": accounts_before["frozen_at"],
                "status": "START",
                "equity_usd": {
                    cid: round(float(accounts_before["accounts"][cid]["equity_usd"]), 6)
                    for cid in IDS
                },
            }],
        }
    point = {
        "ts": out["generated_at"],
        "status": out["status"],
        "market_ts": max((x.get("mark") or {}).get("ts", "") for x in out["market"].values()),
        "equity_usd": {cid: round(float(a["equity_usd"]), 6) for cid, a in out["accounts"].items()},
    }
    last = history["points"][-1] if history["points"] else None
    if not last or last.get("market_ts") != point["market_ts"] or last.get("status") != point["status"]:
        history["points"].append(point)
    writej(path, history)

def update_persistent_accounts(packet: dict[str, Any], out: dict[str, Any]) -> None:
    if out["status"] != "SETTLED":
        return
    ledger = readj(SEASON_ACCOUNTS)
    old_stamp = ledger.get("updated_from_packet_frozen_at") or "1970-01-01T00:00:00Z"
    if packet["frozen_at"] <= old_stamp:
        return
    for cid in IDS:
        a = out["accounts"][cid]
        ledger["accounts"][cid] = {
            "name": a["name"],
            "cash_usd": a["cash_usd"],
            "equity_usd": a["equity_usd"],
            "realized_pnl_usd": a["realized_pnl_usd"],
            "positions": {
                ticker: {
                    "qty": p["qty"],
                    "avg_cost": p["avg_cost"],
                    "mark_price": p["mark_price"],
                    "market_value": p["market_value"],
                }
                for ticker, p in (a.get("positions") or {}).items()
            },
            "source_round": out["round_id"],
        }
    ledger["updated_from_packet_frozen_at"] = packet["frozen_at"]
    ledger["updated_at"] = out["generated_at"]
    writej(SEASON_ACCOUNTS, ledger)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round-id", required=True)
    args = ap.parse_args()

    rd = ROOT / "rounds" / args.round_id
    state = readj(rd / "public_state.json")
    packet = readj(rd / "packet.json")
    reveal = readj(rd / "reveal.json")
    if not (rd / "accounts_before.json").exists():
        raise RuntimeError("Persistent settlement requires accounts_before.json; legacy rounds are preserved unchanged.")
    accounts_before = readj(rd / "accounts_before.json")
    prior = readj(rd / "settlement.json") if (rd / "settlement.json").exists() else None

    revealed_at = dt.datetime.fromisoformat(reveal["revealed_at"].replace("Z", "+00:00"))
    exec_epoch = ceil_minute_epoch(revealed_at)
    market = {}
    pending_execution = False

    for ticker in TICKERS:
        pairs, meta, url = bars(ticker)
        prior_exec = ((prior or {}).get("market", {}).get(ticker, {}) or {}).get("execution_reference")
        if prior_exec:
            execution = prior_exec
        else:
            future = first_future_bar(pairs, exec_epoch)
            if future is None:
                execution = None
                pending_execution = True
            else:
                et, ep = future
                execution = {"ts": iso(dt.datetime.fromtimestamp(et, dt.timezone.utc)), "price": ep}
        mt, mp = latest_regular_bar(pairs)
        if execution is None and mt < exec_epoch:
            mark = {
                "ts": packet["quotes"][ticker]["observed_at"],
                "price": float(packet["quotes"][ticker]["observed_price"]),
                "basis": "frozen packet price while waiting for regular-session execution",
            }
        else:
            mark = {
                "ts": iso(dt.datetime.fromtimestamp(mt, dt.timezone.utc)),
                "price": mp,
                "basis": "latest regular-session 1m close",
            }
        reg = ((meta.get("currentTradingPeriod") or {}).get("regular") or {})
        market[ticker] = {
            "execution_reference": execution,
            "mark": mark,
            "regular_start_epoch": int(reg.get("start") or 0),
            "regular_end_epoch": int(reg.get("end") or 0),
            "source": url,
        }

    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    regular_end = max(x["regular_end_epoch"] for x in market.values())
    settled = bool(not pending_execution and regular_end and now >= regular_end)
    status = "PENDING_EXECUTION" if pending_execution else ("SETTLED" if settled else "INTRADAY")

    accounts = {}
    for cid in IDS:
        reveal_row = (reveal.get("contestants") or {}).get(cid)
        bundle = reveal_row.get("bundle") if reveal_row else None
        error = (reveal.get("no_shows") or {}).get(cid)
        accounts[cid] = account_after_actions(
            cid=cid,
            start=accounts_before["accounts"][cid],
            bundle=bundle,
            error=error,
            market=market,
            state=state,
        )

    out = {
        "schema": "marketarena.settlement.v3",
        "round_id": args.round_id,
        "status": status,
        "persistent_accounts": True,
        "execution_rule": "First FUTURE regular-session 1m bar at/after the first whole minute following reveal. ADD/REDUCE size is 10% of round-start paper equity, capped by cash/position. 5 bps adverse slippage.",
        "mark_rule": "All carried and new positions are marked to the latest available regular-session 1m close; final after regular market end.",
        "generated_at": iso(),
        "account_state_digest": state.get("account_state_digest"),
        "market": market,
        "accounts": accounts,
    }
    writej(rd / "settlement.json", out)
    append_mark_history(rd, accounts_before, out)
    update_persistent_accounts(packet, out)

    state["phase"] = "SETTLED" if settled else ("WAITING_FOR_OPEN" if pending_execution else "TRADING")
    state["settlement_status"] = status
    state["persistent_accounts"] = True
    state["updated_at"] = iso()
    writej(rd / "public_state.json", state)
    print(json.dumps({
        "round_id": args.round_id,
        "status": status,
        "accounts": {cid: round(a["equity_usd"], 4) for cid, a in accounts.items()},
    }))

if __name__ == "__main__":
    main()
