# cbbtc-trend-rider

[![make.fun](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/axe7/cbbtc-trend-rider/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/axe7/cbbtc-trend-rider/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)

**cbbtc-trend-rider** — a patient two-tier trend bot that trades Coinbase Wrapped BTC (cbBTC) against USDC, minute by minute, with $1,000 of paper money. Built for [make.fun's btc-race-24h-20261123-0511 bounty](https://make.fun/bounty/btc-race-24h-20261123-0511). Nothing here trades for real.

## Why patient

A full-size round trip on this pool costs about 46 bps (4 bps fee + 2 bps slippage + ~17 bps of price impact at the dev window's depth). One-minute cbBTC bars are noisy — about 8 bps of standard deviation a minute — so a bot that trades every wiggle pays that round-trip tax dozens of times and bleeds out. This bot trades rarely, and only on a big, slow move.

## The strategy

- **Tier 1 (full size):** when the 240-minute momentum of the close tops +150 bps, buy with all cash and ride the trend. Exit when the 240-minute momentum turns below −150 bps, or on a 300 bps trailing stop below the peak close since entry.
- **Tier 2 (small probe, 10% of cash):** past bar 480, while flat, when the 60-minute momentum tops +50 bps and the close sits above its 120-bar EMA, buy a small probe. It tops up to full size on the Tier 1 signal, and exits on 60-minute momentum below −50 bps or a 150 bps trailing stop. At most 3 probes per window. The probe exists so the bot still makes a trade — and so meets the 1-trade guardrail — on a window with no big trend, where staying flat would otherwise mean no trade at all.

All decisions are integer functions of the bars the harness has sent (momentum in basis points, an integer EMA), so two runs on the same data answer identically. It never shorts and never uses leverage.

## Results on the published dev window

| Bot | Net PnL | Trades | Max drawdown |
| --- | --- | --- | --- |
| cbbtc-trend-rider | **+$19.73** | 1 | 2.03% |
| buy-and-hold (house baseline) | +$32.17 | 1 | 1.98% |

The trend rider gives up some of the rally by entering late, on purpose: on the same window run backwards (a mirror downtrend) it loses only −$2.85 while buy-and-hold loses −$38.40, and on the choppy second half of the window it ends essentially flat (+$0.19). The race window is unseen, so the bot is built to survive a down or sideways day, not just to ride an up day.

## Layout

- `main.py` — the bot (Python 3.13, standard library only).
- `vendor/makefun_bars.py` — the kit's bars-replay protocol shim, copied byte for byte (see the kit's rules: a shim copied under `vendor/` is left out of the authorship counts).

## Run it locally

From the competition kit directory:

```sh
node cli/makefun.mjs grade-local --kit . --bot <path-to-this-repo> --driver process
```
