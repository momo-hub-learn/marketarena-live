#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ["ADD", "HOLD", "REDUCE", "EXIT", "ABSTAIN"]
TICKERS = ["AAPL", "NVDA", "AMZN", "META"]
OPENROUTER = "https://openrouter.ai"
ASTRA_MODEL = "openai/gpt-6-astra"
JEV_MODEL = "typesafe/jev-1.13"
DEEPSEEK_MODEL = "deepseek/deepseek-v4.1-flash"

def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def iso(ts: dt.datetime | None = None) -> str:
    return (ts or utcnow()).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")

def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, obj: Any, *, canonical: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if canonical:
        path.write_bytes(canonical_bytes(obj))
    else:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def http_json(url: str, *, method="GET", headers=None, body=None, timeout=30) -> Any:
    hdr = {"User-Agent": "MarketArena/0.1 (+https://github.com/momo-hub-learn/marketarena-live)"}
    if headers:
        hdr.update(headers)
    data = None if body is None else canonical_bytes(body)
    req = urllib.request.Request(url, data=data, method=method, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.status >= 400:
            raise RuntimeError(f"HTTP {r.status}: {raw[:500]!r}")
        return json.loads(raw)

def yahoo_snapshot(ticker: str, frozen_at: dt.datetime) -> dict[str, Any]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?interval=1m&range=1d&includePrePost=true"
    data = http_json(url)
    result = data["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    last_ts = None
    last_price = None
    cutoff = int(frozen_at.timestamp())
    for ts, price in zip(timestamps, closes):
        if ts is not None and price is not None and ts <= cutoff:
            last_ts, last_price = ts, float(price)
    if last_price is None:
        last_price = float(meta.get("regularMarketPrice"))
        last_ts = int(meta.get("regularMarketTime") or cutoff)
    previous = meta.get("chartPreviousClose") or meta.get("previousClose") or meta.get("regularMarketPreviousClose")
    previous = float(previous) if previous is not None else None
    change_pct = ((last_price / previous) - 1.0) * 100.0 if previous else None
    return {
        "ticker": ticker,
        "observed_price": round(last_price, 4),
        "observed_at": iso(dt.datetime.fromtimestamp(last_ts, dt.timezone.utc)),
        "previous_close": previous,
        "change_pct_vs_previous_close": round(change_pct, 4) if change_pct is not None else None,
        "currency": meta.get("currency", "USD"),
        "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
        "regular_market_open": meta.get("regularMarketOpen"),
        "regular_market_day_high": meta.get("regularMarketDayHigh"),
        "regular_market_day_low": meta.get("regularMarketDayLow"),
        "regular_market_volume": meta.get("regularMarketVolume"),
        "source": url,
    }

def yahoo_news(ticker: str, frozen_at: dt.datetime, limit=3) -> list[dict[str, Any]]:
    url = "https://query1.finance.yahoo.com/v1/finance/search?" + urllib.parse.urlencode(
        {"q": ticker, "quotesCount": 0, "newsCount": limit, "enableFuzzyQuery": "false"}
    )
    try:
        data = http_json(url)
    except Exception:
        return []
    cutoff = int(frozen_at.timestamp())
    out = []
    for item in data.get("news") or []:
        published = item.get("providerPublishTime")
        if published and published > cutoff:
            continue
        out.append({
            "title": item.get("title"),
            "publisher": item.get("publisher"),
            "published_at": iso(dt.datetime.fromtimestamp(published, dt.timezone.utc)) if published else None,
            "url": item.get("link") or item.get("clickThroughUrl", {}).get("url"),
        })
    return out[:limit]

def make_packet(round_id: str) -> tuple[dict[str, Any], bytes, str]:
    frozen_at = utcnow()
    quotes = {}
    news = {}
    for ticker in TICKERS:
        quotes[ticker] = yahoo_snapshot(ticker, frozen_at)
        news[ticker] = yahoo_news(ticker, frozen_at)
    packet = {
        "schema": "marketarena.packet.v3",
        "round_id": round_id,
        "truth_class": "paper-live",
        "frozen_at": iso(frozen_at),
        "universe": TICKERS,
        "quotes": quotes,
        "news": news,
        "portfolio": {"cash_usd": 10000.0, "equity_usd": 10000.0, "positions": {}},
        "allowed_actions": ACTIONS,
        "arena_rules": {
            "paper_only": True,
            "no_leverage": True,
            "no_shorting": True,
            "add_size_pct_equity": 10,
            "reduce_size_pct_equity": 10,
            "contestants_cannot_see_leaderboard": True,
            "contestants_cannot_see_rival_decisions": True,
        },
        "provenance": {
            "quote_source": "Yahoo Finance public chart endpoint",
            "news_source": "Yahoo Finance public search endpoint",
            "limitations": [
                "Public web data may be delayed, incomplete, or corrected later.",
                "This is not an exchange-grade licensed feed.",
                "Paper-trading research experiment; not investment advice.",
            ],
        },
    }
    raw = canonical_bytes(packet)
    return packet, raw, sha256_bytes(raw)

def public_state(round_id: str, packet: dict[str, Any], digest: str, decision_window: int, reveal_pause: int) -> dict[str, Any]:
    frozen = dt.datetime.fromisoformat(packet["frozen_at"].replace("Z", "+00:00"))
    deadline = frozen + dt.timedelta(seconds=decision_window)
    return {
        "schema": "marketarena.public-round.v2",
        "round_id": round_id,
        "truth_class": "paper-live",
        "phase": "FROZEN",
        "packet_digest": digest,
        "packet_frozen_at": packet["frozen_at"],
        "decision_deadline": iso(deadline),
        "reveal_pause_seconds": reveal_pause,
        "reveal_at": None,
        "contestants": {
            "astra": {"name": "Astra", "model_id": ASTRA_MODEL, "status": "WAITING"},
            "jev": {"name": "Jev", "model_id": JEV_MODEL, "status": "WAITING"},
            "deepseek": {"name": "DeepSeek", "model_id": DEEPSEEK_MODEL, "status": "WAITING"},
            "quant": {"name": "Quant", "model_id": "season0-gap-rule-v1", "status": "WAITING"},
            "hybrid": {"name": "Astra + Jev", "model_id": f"{ASTRA_MODEL}+{JEV_MODEL}", "status": "WAITING"},
        },
        "event_chain_valid": True,
        "updated_at": iso(),
    }

def append_event(round_dir: Path, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = round_dir / "events.jsonl"
    prev = "GENESIS"
    if path.exists():
        lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        if lines:
            prev = json.loads(lines[-1])["event_hash"]
    event = {"ts": iso(), "type": event_type, "prev_hash": prev, "payload": payload}
    event["event_hash"] = sha256_bytes(canonical_bytes(event))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return event

def openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")
    return key

def openrouter(path: str, body: dict[str, Any], *, timeout=120) -> tuple[dict[str, Any], int]:
    started = time.monotonic()
    attempts = 3 if path.endswith("/decisions") else 2
    last = None
    for attempt in range(attempts):
        try:
            data = http_json(
                OPENROUTER + path,
                method="POST",
                headers={
                    "Authorization": f"Bearer {openrouter_key()}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/momo-hub-learn/marketarena-live",
                    "X-Title": "MarketArena",
                },
                body=body,
                timeout=timeout,
            )
            return data, int((time.monotonic() - started) * 1000)
        except Exception as e:
            last = e
            # Billing/auth/configuration failures are deterministic; transport failures are not.
            if any(code in str(e) for code in ("HTTP Error 400", "HTTP Error 401", "HTTP Error 402", "HTTP Error 403")):
                raise
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise last

def decision_schema() -> dict[str, Any]:
    per = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ACTIONS},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string", "maxLength": 220},
        },
        "required": ["action", "confidence", "reason"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decisions": {
                "type": "object",
                "additionalProperties": False,
                "properties": {t: per for t in TICKERS},
                "required": TICKERS,
            }
        },
        "required": ["decisions"],
    }

def market_prompt(packet: dict[str, Any]) -> str:
    safe = {k: packet[k] for k in ["frozen_at", "universe", "quotes", "news", "portfolio", "allowed_actions", "arena_rules"]}
    return json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def normalize_bundle(decisions: dict[str, Any], model_id: str, latency_ms: int, usage=None, *, extra=None) -> dict[str, Any]:
    out = {}
    for ticker in TICKERS:
        row = decisions[ticker]
        action = str(row["action"]).upper()
        if action not in ACTIONS:
            raise ValueError(f"invalid action {action}")
        out[ticker] = {
            "action": action,
            "confidence": round(float(row.get("confidence", 0.0)), 6),
            "reason": str(row.get("reason", ""))[:220],
        }
        if "probabilities" in row:
            out[ticker]["probabilities"] = row["probabilities"]
    result = {"model_id": model_id, "latency_ms": latency_ms, "usage": usage or {}, "decisions": out}
    if extra:
        result["extra"] = extra
    return result

def llm_decisions(model: str, packet: dict[str, Any], system: str) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system
                + "\nThis is a paper-trading research benchmark, not advice to a person. Use only the supplied frozen packet. Do not infer future information. Return one action for every ticker. Keep each reason under 220 characters.",
            },
            {"role": "user", "content": market_prompt(packet)},
        ],
        "max_tokens": 1200,
    }
    if model == DEEPSEEK_MODEL:
        # Tool calling is broadly routed for V4.1 Flash and avoids providers that
        # return null content for response_format-based structured output.
        body["tools"] = [{
            "type": "function",
            "function": {
                "name": "submit_decisions",
                "description": "Submit the complete MarketArena paper-trading action vector.",
                "parameters": decision_schema(),
            },
        }]
        body["tool_choice"] = {"type": "function", "function": {"name": "submit_decisions"}}
    else:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "marketarena_trade_decisions", "strict": True, "schema": decision_schema()},
        }
    if model == ASTRA_MODEL:
        body["reasoning"] = {"effort": "medium"}
    data, latency = openrouter("/api/v1/chat/completions", body)
    message = data["choices"][0]["message"]
    if model == DEEPSEEK_MODEL:
        calls = message.get("tool_calls") or []
        if not calls:
            raise ValueError(f"DeepSeek returned no submit_decisions tool call: {message!r}")
        parsed = json.loads(calls[0]["function"]["arguments"])
    else:
        content = message.get("content")
        if not content:
            raise ValueError(f"{model} returned empty structured content: {message!r}")
        parsed = json.loads(content)
    return normalize_bundle(parsed["decisions"], model, latency, data.get("usage"))

def jev_decisions(packet: dict[str, Any], *, extra_state=None, model_id=JEV_MODEL) -> dict[str, Any]:
    state = {"market_packet": {k: packet[k] for k in ["frozen_at", "quotes", "news", "portfolio", "arena_rules"]}}
    if extra_state is not None:
        state["astra_theses"] = extra_state
    criteria = {
        "ADD": "Increase the long allocation by the arena's fixed amount only when the frozen evidence supports taking more risk.",
        "HOLD": "Keep the existing allocation unchanged.",
        "REDUCE": "Reduce an existing long allocation by the arena's fixed amount. If no long exists, prefer ABSTAIN rather than invent a short.",
        "EXIT": "Exit an existing long position completely. If no long exists, prefer ABSTAIN.",
        "ABSTAIN": "Take no new market action because evidence is insufficient, conflicting, stale, or the requested sell is impossible from the current portfolio.",
    }
    questions = {}
    for ticker in TICKERS:
        questions[ticker] = {
            "type": "choice",
            "instructions": f"For {ticker}, choose the single paper-trading action that best fits the frozen market packet and current portfolio. No leverage or shorting.",
            "criteria": criteria,
        }
    data, latency = openrouter(
        "/api/alpha/decisions",
        {"model": model_id, "state": json.dumps(state, ensure_ascii=False, sort_keys=True), "questions": questions},
    )
    decisions = {}
    for ticker in TICKERS:
        ans = (data.get("answers") or {}).get(ticker) or {}
        choice_obj = ans.get("choice")
        choice = choice_obj.get("choice") if isinstance(choice_obj, dict) else choice_obj
        if choice not in ACTIONS:
            raise ValueError(f"Jev returned invalid choice for {ticker}: {ans!r}")
        probs = ans.get("probabilities")
        conf = ans.get("confidence")
        if isinstance(choice_obj, dict):
            probs = probs or choice_obj.get("probabilities")
            conf = conf if conf is not None else choice_obj.get("confidence")
        decisions[ticker] = {
            "action": choice,
            "confidence": float(conf or 0),
            "reason": "Structured Jev decision from the frozen packet.",
            "probabilities": probs or {},
        }
    return normalize_bundle(decisions, model_id, latency, data.get("usage"), extra={"jev_raw_model": data.get("model")})

def astra_theses(packet: dict[str, Any]) -> tuple[dict[str, Any], int, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "theses": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    t: {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "thesis": {"type": "string", "maxLength": 400},
                            "invalidation": {"type": "string", "maxLength": 300},
                            "evidence_quality": {"type": "string", "enum": ["low", "medium", "high"]},
                        },
                        "required": ["thesis", "invalidation", "evidence_quality"],
                    }
                    for t in TICKERS
                },
                "required": TICKERS,
            }
        },
        "required": ["theses"],
    }
    body = {
        "model": ASTRA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are the slow research layer in a paper-trading decision benchmark. Use only the supplied frozen packet. For each ticker, write a compact market thesis, a concrete invalidation condition, and an evidence-quality label. Do not choose an action and do not use future information.",
            },
            {"role": "user", "content": market_prompt(packet)},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "marketarena_theses", "strict": True, "schema": schema}},
        "reasoning": {"effort": "medium"},
        "max_tokens": 1400,
    }
    data, latency = openrouter("/api/v1/chat/completions", body)
    parsed = json.loads(data["choices"][0]["message"]["content"])
    return parsed["theses"], latency, data.get("usage")

def hybrid_decisions(packet: dict[str, Any]) -> dict[str, Any]:
    theses, astra_ms, astra_usage = astra_theses(packet)
    jev = jev_decisions(packet, extra_state=theses)
    jev["model_id"] = f"{ASTRA_MODEL}+{JEV_MODEL}"
    jev["latency_ms"] += astra_ms
    jev["extra"] = {"astra_theses": theses, "astra_usage": astra_usage, **(jev.get("extra") or {})}
    return jev

def quant_decisions(packet: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    positions = packet["portfolio"]["positions"]
    out = {}
    for ticker in TICKERS:
        chg = packet["quotes"][ticker].get("change_pct_vs_previous_close")
        pos = float(positions.get(ticker, 0) or 0)
        if chg is None:
            action, reason = "ABSTAIN", "Missing previous-close comparison."
        elif chg >= 1.5:
            action, reason = "ADD", f"Frozen price is {chg:.2f}% above previous close (>= +1.5%)."
        elif chg <= -1.5 and pos > 0:
            action, reason = "REDUCE", f"Frozen price is {chg:.2f}% below previous close (<= -1.5%)."
        elif chg <= -1.5:
            action, reason = "ABSTAIN", "Negative threshold hit but no long position exists; shorting is forbidden."
        else:
            action, reason = "HOLD", f"Change {chg:.2f}% is inside the frozen +/-1.5% band."
        out[ticker] = {"action": action, "confidence": 1.0, "reason": reason}
    return normalize_bundle(out, "season0-gap-rule-v1", int((time.monotonic() - started) * 1000), {})

def contestant_call(name: str, packet: dict[str, Any]) -> dict[str, Any]:
    if name == "astra":
        return llm_decisions(
            ASTRA_MODEL,
            packet,
            "You are Astra, a deliberate research-first paper trader in MarketArena. Assess the supplied evidence conservatively and choose bounded actions.",
        )
    if name == "jev":
        return jev_decisions(packet)
    if name == "deepseek":
        return llm_decisions(
            DEEPSEEK_MODEL,
            packet,
            "You are DeepSeek, an independent general-purpose reasoning model competing in MarketArena. Use only the frozen packet and choose bounded paper-trading actions.",
        )
    if name == "quant":
        return quant_decisions(packet)
    if name == "hybrid":
        return hybrid_decisions(packet)
    raise KeyError(name)

def commitment(bundle: dict[str, Any], nonce: str) -> str:
    return sha256_bytes(canonical_bytes({"bundle": bundle, "nonce": nonce}))

def verify_commitment(bundle: dict[str, Any], nonce: str, expected: str) -> bool:
    return secrets.compare_digest(commitment(bundle, nonce), expected)

def prepare(args) -> None:
    round_dir = ROOT / "rounds" / args.round_id
    if round_dir.exists() and (round_dir / "packet.json").exists():
        raise RuntimeError(f"round already exists: {args.round_id}")
    packet, raw, digest = make_packet(args.round_id)
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "packet.json").write_bytes(raw)
    state = public_state(args.round_id, packet, digest, args.decision_window, args.reveal_pause)
    write_json(round_dir / "public_state.json", state)
    write_json(
        ROOT / "rounds" / "current.json",
        {"round_id": args.round_id, "path": f"rounds/{args.round_id}/public_state.json", "packet": f"rounds/{args.round_id}/packet.json"},
    )
    append_event(round_dir, "PACKET_FROZEN", {"packet_digest": digest, "frozen_at": packet["frozen_at"]})
    print(json.dumps({"round_id": args.round_id, "packet_digest": digest, "frozen_at": packet["frozen_at"]}))

def decide(args) -> None:
    round_dir = ROOT / "rounds" / args.round_id
    packet = read_json(round_dir / "packet.json")
    state = read_json(round_dir / "public_state.json")
    deadline = dt.datetime.fromisoformat(state["decision_deadline"].replace("Z", "+00:00"))
    if utcnow() >= deadline:
        raise RuntimeError("decision window already closed")
    names = ["astra", "jev", "deepseek", "quant", "hybrid"]
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(contestant_call, n, packet): n for n in names}
        remaining = max(1.0, (deadline - utcnow()).total_seconds())
        try:
            for fut in concurrent.futures.as_completed(futures, timeout=remaining):
                n = futures[fut]
                try:
                    results[n] = fut.result()
                except Exception as e:
                    errors[n] = f"{type(e).__name__}: {e}"
        except TimeoutError:
            pass
        for fut, n in futures.items():
            if n not in results and n not in errors:
                fut.cancel()
                errors[n] = "NO_SHOW: decision deadline elapsed"
    private = {"round_id": args.round_id, "created_at": iso(), "decisions": {}, "errors": errors}
    reveal_at = utcnow() + dt.timedelta(seconds=args.reveal_pause)
    state["phase"] = "SEALED"
    state["reveal_at"] = iso(reveal_at)
    for n in names:
        if n in results:
            nonce = secrets.token_hex(32)
            c = commitment(results[n], nonce)
            private["decisions"][n] = {"bundle": results[n], "nonce": nonce, "commitment": c}
            state["contestants"][n]["status"] = "LOCKED"
            state["contestants"][n]["commitment"] = c
            append_event(round_dir, "DECISION_COMMITTED", {"contestant": n, "commitment": c})
        else:
            state["contestants"][n]["status"] = "NO_SHOW"
            state["contestants"][n]["error"] = errors.get(n, "NO_SHOW")[:240]
            append_event(round_dir, "NO_SHOW", {"contestant": n, "error": errors.get(n, "NO_SHOW")[:240]})
    state["updated_at"] = iso()
    write_json(round_dir / "public_state.json", state)
    priv = ROOT / ".private" / args.round_id
    priv.mkdir(parents=True, exist_ok=True)
    write_json(priv / "decisions.json", private)
    print(json.dumps({"phase": "SEALED", "locked": list(results), "errors": errors, "reveal_at": state["reveal_at"]}))

def reveal(args) -> None:
    round_dir = ROOT / "rounds" / args.round_id
    state = read_json(round_dir / "public_state.json")
    private = read_json(ROOT / ".private" / args.round_id / "decisions.json")
    reveal_at = dt.datetime.fromisoformat(state["reveal_at"].replace("Z", "+00:00"))
    if utcnow() < reveal_at:
        sleep_for = (reveal_at - utcnow()).total_seconds()
        print(f"waiting {sleep_for:.1f}s until reveal", flush=True)
        time.sleep(sleep_for)
    revealed = {}
    for n, row in private["decisions"].items():
        if not verify_commitment(row["bundle"], row["nonce"], row["commitment"]):
            raise RuntimeError(f"commitment verification failed for {n}")
        revealed[n] = row
        state["contestants"][n]["status"] = "REVEALED"
    result = {
        "schema": "marketarena.reveal.v1",
        "round_id": args.round_id,
        "revealed_at": iso(),
        "contestants": revealed,
        "no_shows": private.get("errors", {}),
    }
    write_json(round_dir / "reveal.json", result)
    state["phase"] = "REVEALED"
    state["updated_at"] = iso()
    write_json(round_dir / "public_state.json", state)
    append_event(round_dir, "ROUND_REVEALED", {"contestants": sorted(revealed), "no_shows": sorted(private.get("errors", {}))})
    print(json.dumps({"phase": "REVEALED", "contestants": list(revealed)}))

def verify_events(args) -> None:
    path = ROOT / "rounds" / args.round_id / "events.jsonl"
    prev = "GENESIS"
    count = 0
    for count, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        e = json.loads(line)
        got = e.pop("event_hash")
        if e["prev_hash"] != prev or sha256_bytes(canonical_bytes(e)) != got:
            raise RuntimeError(f"event chain failed at line {count}")
        prev = got
    print(f"event chain OK: {count} events")

def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("--round-id", required=True)
    a.add_argument("--decision-window", type=int, default=300)
    a.add_argument("--reveal-pause", type=int, default=120)
    a.set_defaults(func=prepare)
    a = sub.add_parser("decide")
    a.add_argument("--round-id", required=True)
    a.add_argument("--reveal-pause", type=int, default=120)
    a.set_defaults(func=decide)
    a = sub.add_parser("reveal")
    a.add_argument("--round-id", required=True)
    a.set_defaults(func=reveal)
    a = sub.add_parser("verify-events")
    a.add_argument("--round-id", required=True)
    a.set_defaults(func=verify_events)
    args = p.parse_args()
    try:
        args.func(args)
        return 0
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
