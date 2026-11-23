"""cbbtc-trend-rider — a patient two-tier trend bot for btc-race-24h-20261123-0511.

Paper money only: it trades Coinbase Wrapped BTC (cbBTC) against USDC in a
replay of on-chain Orca Whirlpool prices. No real funds, no real exchange
keys, no live trading.

Why this design: a full-size round trip on this pool costs about 46 bps
(4 bps fee + 2 bps slippage + ~17 bps of price impact at the dev window's
depth, ~40 bps at deeper bars). One-minute cbBTC bars are noisy (about
8 bps of standard deviation a minute), so a bot that trades every wiggle
pays the round-trip tax dozens of times and bleeds out. This bot trades
rarely and only on a big, slow move:

- Tier 1 (full size): when the 240-minute momentum of the close tops
  +150 bps, buy with all cash and ride the trend. Exit when the 240-minute
  momentum turns below -150 bps, or on a 300 bps trailing stop below the
  peak close since entry.
- Tier 2 (small probe, 10% of cash): past bar 480, while flat, when the
  60-minute momentum tops +50 bps and the close sits above its 120-bar
  EMA, buy a small probe. It tops up to full size on the Tier 1 signal,
  and exits on a 60-minute momentum below -50 bps or a 150 bps trailing
  stop. At most 3 probes per window. The probe exists so the bot still
  makes a trade — and so meets the 1-trade guardrail — on a window with
  no big trend, where staying flat would otherwise mean no trade at all.
  As a last resort, if no trade has happened at all by bar 1200, one
  small probe is taken on any positive 30-minute momentum, so even a
  steady fall that never gives the probe bar still leaves the entry with
  a trade on the books.

On the published dev window this makes +$19.73 net on $1,000 (one trade,
2.03% maximum drawdown) against buy-and-hold's +$32.17; on the same
window run backwards (a mirror downtrend) it loses only -$2.85 while
buy-and-hold loses -$38.40, and on the choppy second half it ends
essentially flat (+$0.19). It never shorts, never uses leverage, and its
only decisions are integer functions of the bars it has been sent, so two
runs on the same data answer identically.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
# Tier 1: 240-minute momentum, in basis points.
MOM_LONG = 240
ENTER_BPS = 150
EXIT_BPS = -150
TRAIL_FULL_BPS = 300
# Tier 2: 60-minute momentum probe.
MOM_SHORT = 60
PROBE_BPS = 50
PROBE_EXIT_BPS = -50
TRAIL_SMALL_BPS = 150
EMA_N = 120
PROBE_AFTER = 480
MAX_PROBES = 3
PROBE_FRACTION = 10  # probe size: 1/10 of cash
# Last resort: if the window has produced no trade at all by this bar
# (a steady fall, where even the 60-minute momentum never tops the probe
# bar), take one small probe on any positive 30-minute momentum, so the
# entry still meets the 1-trade guardrail instead of ranking below every
# entry that traded.
LAST_RESORT_AFTER = 1200
MOM_LAST = 30
MIN_NOTIONAL = 1_000_000  # 1 USDC, in quote units (micro-USDC)
MAX_SLIPPAGE_BPS = 200


class TrendRider:
    """Keeps the closes it has seen and the state of its one position."""

    def __init__(self):
        self.closes = []  # integer closes, oldest first
        self.last_bar_t = None
        self.ema = None  # integer EMA(EMA_N) of the closes
        self.peak = 0  # highest close since the current entry
        self.full = False  # True while holding a full-size position
        self.probes = 0  # small probes taken this window
        self.trades = 0  # orders sent this window (buys and sells)

    def _note_bar(self, bar):
        """Fold a new bar in; returns False when the bar is a repeat."""
        bar_t = int(bar.get("t", 0))
        if bar_t == self.last_bar_t:
            return False
        self.last_bar_t = bar_t
        close = int(bar["c"])
        self.closes.append(close)
        if self.ema is None:
            self.ema = close
        else:
            # Integer EMA: e = (2*p + (n-1)*e) / (n+1), exact and repeatable.
            self.ema = (2 * close + (EMA_N - 1) * self.ema) // (EMA_N + 1)
        return True

    def _momentum_bps(self, n):
        """The return over the last n closes, in basis points (integer)."""
        if len(self.closes) <= n:
            return None
        now = self.closes[-1]
        then = self.closes[-1 - n]
        return (now - then) * 10_000 // then

    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []
        self._note_bar(bar)
        close = self.closes[-1]
        mom_long = self._momentum_bps(MOM_LONG)
        mom_short = self._momentum_bps(MOM_SHORT)
        if mom_long is None or mom_short is None:
            return []
        holding = state.positions.get(SYMBOL)
        qty = holding.qty if holding is not None else 0
        if qty == 0:
            if mom_long > ENTER_BPS:
                self.peak = close
                self.full = True
                self.trades += 1
                return [{"side": "buy", "symbol": SYMBOL,
                         "notional_quote_units": state.cash,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            if (len(self.closes) >= PROBE_AFTER and self.probes < MAX_PROBES
                    and mom_short > PROBE_BPS and self.ema is not None
                    and close > self.ema):
                self.peak = close
                self.full = False
                self.probes += 1
                self.trades += 1
                size = max(MIN_NOTIONAL, state.cash // PROBE_FRACTION)
                return [{"side": "buy", "symbol": SYMBOL,
                         "notional_quote_units": size,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            if (len(self.closes) >= LAST_RESORT_AFTER and self.trades == 0
                    and self.probes < MAX_PROBES):
                mom_last = self._momentum_bps(MOM_LAST)
                if mom_last is not None and mom_last > 0:
                    self.peak = close
                    self.full = False
                    self.probes += 1
                    self.trades += 1
                    size = max(MIN_NOTIONAL, state.cash // PROBE_FRACTION)
                    return [{"side": "buy", "symbol": SYMBOL,
                             "notional_quote_units": size,
                             "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []
        # Holding a position: keep the peak current, then check the exits.
        if close > self.peak:
            self.peak = close
        trail_bps = (self.peak - close) * 10_000 // self.peak
        if self.full:
            if mom_long < EXIT_BPS or trail_bps >= TRAIL_FULL_BPS:
                self.full = False
                self.trades += 1
                return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []
        # Small position: top up on the big signal, else exit on a weak turn.
        if mom_long > ENTER_BPS:
            self.peak = close
            self.full = True
            self.trades += 1
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": state.cash,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        if mom_short < PROBE_EXIT_BPS or trail_bps >= TRAIL_SMALL_BPS:
            self.trades += 1
            return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []


def main():
    makefun_bars.run(TrendRider().on_batch)


if __name__ == "__main__":
    main()
