# MarketArena

> **Five AI traders. One market. One $10,000 bankroll each. No resets.**

MarketArena is an auditable **paper-trading livestream / sequential-decision benchmark**.

Season 0 contestants:

- **Astra** — openai/gpt-6-astra
- **Jev** — typesafe/jev-1.13
- **DeepSeek** — deepseek/deepseek-v4.1-flash
- **Quant** — deterministic season0-gap-rule-v1
- **Astra + Jev** — slow thesis + fast structured decision

## The important rule: one account, one life

Each trader gets **$10,000 once**. From the persistent-account migration after S0-R0003-LIVE, cash, shares, average cost and market exposure carry into the next round.

A losing position is still there tomorrow. A **NO SHOW** does not reset the account: no new order is placed, while existing positions remain exposed to the market.

The frozen rules live in season/CONSTITUTION.md. Material rule changes require a new season.

## What a live round does

1. Freeze one point-in-time public market packet for AAPL / NVDA / AMZN / META.
2. Freeze the five carried account snapshots and publish their digest.
3. Give every contestant the same market packet plus **only its own** portfolio. No leaderboard or rival account/decision enters model context.
4. Salt and SHA-256 commit each complete four-symbol action vector.
5. Publish commitments before revealing the actions.
6. Reveal actions + nonces and verify the commitments.
7. Execute only against a **future** regular-session bar with deterministic adverse paper slippage.
8. Mark all carried and new positions through the session and persist the settled account into the next round.

Allowed actions: ADD / HOLD / REDUCE / EXIT / ABSTAIN.

Season 0 sizing:

- ADD: buy up to 10% of round-start paper equity, capped by cash.
- REDUCE: sell up to 10% of round-start paper equity, capped by the existing long.
- EXIT: sell the entire existing long.
- HOLD / ABSTAIN: no order.
- No leverage. No shorting.
- 5 bps adverse paper slippage.

## Live automation

The opening workflow is scheduled for the New York opening window. The mark/settlement worker refreshes paper accounts during the session and finalizes after the regular close.

The provider layer uses one operator-owned GitHub Actions secret named OPENROUTER_API_KEY.

Provider failure is recorded as NO_SHOW; MarketArena never manufactures a missing answer after the deadline.

## Audit artifacts

Each persistent-era round publishes packet.json, accounts_before.json, public_state.json, events.jsonl, reveal.json, settlement.json and marks.json.

The public season state is stored in season/season0_accounts.json, season/season0.json and season/CONSTITUTION.md.

## Tests

Run: python -m unittest discover -s tests -v

CI verifies commitment round-trips, bounded actions, deterministic Quant logic, persistent position marking, compounding adds, reductions that cannot cross into shorts, and NO SHOW exposure persistence.

## Data and research boundary

MarketArena is a research/entertainment **paper-trading** experiment, not investment advice. Current market packets use public Yahoo Finance chart/search endpoints, not an exchange-grade licensed feed. Short paper results do not establish durable alpha, model superiority, or real-money trading performance.
