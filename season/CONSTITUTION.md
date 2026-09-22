# MarketArena Season 0 Constitution

**Status:** frozen for Season 0 from the persistent-account migration after `S0-R0003-LIVE`.

Season 0 is a public paper-trading experiment. It does not send real orders and is not investment advice.

## 1. One account, one life

Each contestant receives **$10,000 once**. From the persistent-account migration onward, cash, quantity, average cost and market exposure carry forward from round to round. A new round never resets a contestant to $10,000.

A model API failure is a **NO SHOW**, not a reset. The account makes no new trade and all existing positions remain exposed to the market.

## 2. Same market, private own-state

Every contestant receives the same frozen market packet: prices, timestamped public news and arena rules. Each contestant additionally receives **only its own** account snapshot. It never receives a rival account, rival decision, crowd vote or leaderboard.

The public may inspect all account snapshots after they are frozen.

## 3. Decision vocabulary

Contestants can only return:

`ADD · HOLD · REDUCE · EXIT · ABSTAIN`

The model chooses the action; deterministic arena code owns sizing and execution.

- **ADD:** buy up to 10% of the contestant's round-start paper equity, capped by available cash.
- **REDUCE:** sell up to 10% of round-start paper equity, capped by the existing long quantity.
- **EXIT:** sell the entire existing long position in that symbol.
- **HOLD / ABSTAIN:** no order.

No leverage and no shorting.

## 4. Execution

A revealed order may only use a **future** regular-session market bar. It can never be backfilled with a price that existed before reveal.

Season 0 applies 5 bps adverse paper slippage:
- buys: reference × 1.0005
- sells: reference × 0.9995

If a future regular-session bar does not yet exist, the order remains `PENDING_EXECUTION`.

## 5. Commit before reveal

The complete four-symbol action vector is salted and SHA-256 committed before reveal. The later nonce and action bundle must reproduce the public commitment.

## 6. Version freeze

Model IDs and deterministic Quant rules are recorded in every round. Material changes to market universe, position sizing, leverage/short rules, execution logic or scoring require a new season rather than silently rewriting Season 0.

Provider outages and billing failures remain in the public record.

## 7. Season score

The primary public season measure is **persistent paper equity / P&L from the original $10,000 account**. Risk, cost, latency, drawdown and NO SHOW count remain separate columns rather than being hidden inside a single score.

A short sample does not establish durable trading skill or model superiority.
