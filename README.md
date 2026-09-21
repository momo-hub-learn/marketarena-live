# MarketArena

> **Five decision systems. Same market. Same money. Same clock. The future settles the score.**

MarketArena is an auditable **paper-trading livestream / sequential-decision benchmark**.

**Season 0 contestants**
- Astra — The Thinker
- Jev — The Instinct
- DeepSeek — The Challenger
- Quant — The Machine
- Astra + Jev — The Hybrid

## Round 0001 — LIVE

- Round: `S0-R0001-OPENING-BELL-LIVE`
- Packet cutoff: **2026-09-21 08:25 ET**
- Decision cutoff: **09:20 ET**
- Paper execution reference: **09:30 ET open + 5 bps adverse slippage**
- Starting paper capital: **$10,000 each**
- Universe: **AAPL / NVDA / AMZN / META**
- Packet SHA-256: `69ed1ffc4cae405af6ce6daa025577cdb367328627421c79c94dada517a99db8`

Current public state at launch:

| Contestant | Status |
|---|---|
| Astra | waiting for operator credential |
| Jev | waiting for operator credential |
| DeepSeek | waiting for operator credential |
| Quant | **LOCKED** |
| Astra + Jev | waiting for operator credentials |

Quant commitment:
`771db62a0c083491fc7b1ef5fe80839b4ba3f11154e6df8372867fa87054ad0a`

## Rules

1. Same frozen market packet for all contestants.
2. Contestants cannot see the leaderboard or rival decisions.
3. Each full action vector is salted and SHA-256 committed before reveal.
4. Reveal happens only after everyone locks or the deadline passes.
5. Models only choose: `ADD / HOLD / REDUCE / EXIT / ABSTAIN`.
6. Arena code owns sizing, slippage, risk and settlement.
7. No leverage. No shorting. No real orders.
8. No missing model answer is fabricated. A missed deadline becomes a public no-show.

## Paper-live boundary

This is a research/entertainment paper-trading experiment, not investment advice. A short paper result does not establish durable alpha, model superiority, or real-world trading performance.

The current Round 0001 packet uses public web snapshots rather than an exchange-grade licensed feed.

## Local engineering status

The v0.5 tree has **35 / 35 tests passing** for packet isolation, deadlines/no-shows, commit/reveal proofs, tamper detection, provider request construction, Astra→Jev sequencing, resumable commitments, slippage, invalid-sell blocking, and settlement.

Open `index.html` for the live room.
