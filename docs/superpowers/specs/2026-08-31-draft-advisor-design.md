# Dynamic Sleeper Draft Advisor — Design (2026-08-31)

**Goal:** Live draft assistant for the Sleeper league *Touchdowns and Transactions*
(`league_id 1395399704828723200`, `draft_id 1395399705847947264`). 12-team **PPR
snake**, 15 rounds. Starters: 1QB / 2RB / 2WR / 1TE / 2FLEX / 1K / 1DEF, 5 BN, 1 IR.
Me = `xpoes` / `1393861289477959680` (slot resolved live from `draft_order`).

Recommend the optimal pick after every pick, accounting for positional scarcity and
future board coverage — not just raw EV.

## Data sources (verified working 2026-08-31)
- **Sleeper API** — scoring/roster/draft settings, live picks, player metadata
  (age, `injury_status`, `years_exp`, team, `espn_id`). Join key: `espn_id`.
- **ESPN hidden fantasy API** — 2026 season projected fantasy points + ADP.
  Primary projection source. Fallback: nfl_data_py 2025 actuals if ESPN gaps.
- **Odds API** — full-season game spreads+totals → per-team season implied points
  (offensive-environment signal). Key in `ODDS_API_KEY` env.

## Pipeline (built once at startup, cached to data/cache/)
1. Sleeper `/players/nfl` → base table.
2. ESPN proj + ADP, joined on `espn_id`.
3. Adjust projections → `adj_proj`:
   - **Vegas**: team season implied pts vs league avg → ±multiplier.
   - **Age**: position age-curve multiplier (RB cliff ≥28, WR peak ~24-28, QB/TE flat).
   - **Injury/IR**: `injury_status` → games-missed haircut, PLUS hand-editable
     `overrides.py` for known timetables (e.g. Tucker Kraft). *Precise return weeks
     need a human — overrides is that knob.*
4. **VOR** = `adj_proj − replacement_level[pos]`; replacement level from league
   starter demand (12 teams × slots, incl. FLEX split across RB/WR/TE).

## Engine — VONA Monte Carlo
For each candidate in top-K available, run R rollouts: opponents pick via ADP-softmax
until my next pick and onward; I fill needs greedily by VOR; score my optimized
starting lineup at draft end. Recommend argmax expected end-roster value. This is why
an elite RB beats an equal-EV QB now — the sim shows a comparable QB survives but the
RB won't. Output: top-5 recs + "next-best at each position likely gone by pick ___".

## Interface
Terminal live tool (`live.py`): poll Sleeper draft ~every 3s, update state on each new
pick, print board + recommendations, highlight when it's my turn. Sleeper feeds picks —
no manual entry.

## Files
`config.py` ids/slots · `data.py` build player table · `overrides.py` manual injury/bumps
· `engine.py` VOR + MC · `live.py` main loop · `test_engine.py` sanity checks.

## Cut for time
K/DST modeling (stream — near-zero VOR, still auto-filled), auction values,
stack/handcuff bonuses.
