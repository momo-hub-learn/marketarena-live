# MarketArena

> **Five decision systems. Same market. Same money. Same clock. The future settles the score.**

MarketArena is an auditable **paper-trading livestream / sequential-decision benchmark**.

Season 0 contestants:

- **Astra** — `openai/gpt-6-astra`
- **Jev** — `typesafe/jev-1.13`
- **DeepSeek** — `deepseek/deepseek-v4.1-flash`
- **Quant** — deterministic `season0-gap-rule-v1`
- **Astra + Jev** — slow thesis + fast structured decision

The three model providers are called through a single operator-owned `OPENROUTER_API_KEY`. The secret is never committed to the repository.

## What a live round does

1. Fetches one point-in-time public market packet for AAPL / NVDA / AMZN / META.
2. Writes the exact frozen packet and its SHA-256 digest to the public repo **before model decisions**.
3. Sends the same packet and starting portfolio to all five contestants. No leaderboard or rival action is included.
4. Salts and SHA-256 commits each full four-symbol action vector.
5. Publishes commitments while actions remain private in the ephemeral Actions runner.
6. Waits through a short sealed period, then reveals actions + nonces so anyone can recompute each proof.
7. Preserves an append-only hash-linked event log.

Allowed actions: `ADD / HOLD / REDUCE / EXIT / ABSTAIN`.

## Start a round

The operator sets one GitHub Actions secret:

```text
OPENROUTER_API_KEY
```

Then either dispatch **Run paper-live round** in Actions, or update `rounds/START.json` with a new round ID. The default first real model round is `S0-R0002-LIVE`.

The live workflow intentionally records a provider failure as `NO_SHOW`; it does not manufacture or backfill an answer after the decision window.

## Model endpoints

- Astra and DeepSeek: OpenRouter `POST /api/v1/chat/completions` with strict JSON-schema output.
- Jev: OpenRouter `POST /api/alpha/decisions`, model pinned to `typesafe/jev-1.13`.
- Hybrid: one Astra thesis call, followed by a Jev bounded-action call.
- Quant: fixed ±1.5% previous-close rule; it cannot access an LLM.

## Data boundary

The current live packet uses Yahoo Finance public chart/search endpoints at workflow runtime. That is enough for a transparent public experiment, **not** an exchange-grade or licensed production feed. The repository records source URLs, timestamps and this limitation in every packet.

## Tests

Run:

```bash
python -m unittest discover -s tests -v
```

The first code-backed suite verifies proof round-trips, deterministic Quant behavior, bounded actions and canonical hashing. Additional public audit checks live in the round artifacts themselves.

## Research boundary

MarketArena is a research/entertainment paper-trading experiment, not investment advice. Short paper results do not establish durable alpha, model superiority, or real-money trading performance.
