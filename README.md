# Fantasy draft advisor — Touchdowns and Transactions

Live, scarcity-aware draft assistant for the Sleeper league *Touchdowns and
Transactions* (12-team **PPR snake**, 15 rounds). Polls the Sleeper draft and, after
every pick, tells you the optimal pick — not by raw projected points, but by **Value
Over Replacement + Monte Carlo board simulation**, so it accounts for positional
scarcity and what will still be on the board at your *future* picks.

## Why not just draft the highest projection?
Josh Allen projects ~370 pts — more than any RB. But every team only starts 1 QB and
there are ~15 startable QBs, so an elite QB is barely above replacement. Meanwhile the
elite-RB cliff is steep and RBs dry up fast. The Monte Carlo sim makes this concrete:
it simulates opponents drafting (via an ADP-pressure model) and shows a comparable QB
survives to a later round while the elite RB won't — so it grabs scarcity now.

## Objective — variance-aware expected wins (season model)
Rosters are scored not by a deterministic sum of projections but by **expected H2H
regular-season wins**: each starter's weekly score is a normal (mean = season/17, sd =
position CV × mean), the team's weekly total is `N(μ_T, σ_T²)`, and
`P(win a week) = Φ((μ_T − μ_L)/√(σ_T²+σ_L²))` vs a league-average team. Rosters are
completed to 15 before scoring so byes/depth/K/DEF count. Consistency vs boom/bust now
matters, and a **risk knob** (`config.RISK_LAMBDA`, >0 ceiling / <0 floor) tunes it.
Set `config.USE_WIN_VALUE=False` to revert to the sum objective.

## Data (all live; verified working)
- **Sleeper / RotoWire** — `api.sleeper.com/projections` gives RotoWire season
  projections + ADP, id-keyed (no fuzzy join), incl. real DEF projections. Primary source.
- **ESPN fantasy API** — 2026 projections + ADP. **Blended** with RotoWire (mean of the
  two) to denoise per-source outliers, and the fallback when RotoWire lacks a player.
- **Sleeper API** — league scoring/roster, live picks, player age/injury/team.
- **Odds API** — full-season game spreads/totals → per-team implied points, used to
  nudge projections by offensive environment. Key lives in `.env` (gitignored).

Adjustments applied to each projection: Vegas team environment · position age curves
(RB cliff ≥28, etc.) · injury/IR games-missed haircut · your manual `overrides.py`.

## Run it
```bash
echo 'ODDS_API_KEY=your_key_here' > .env      # already set up locally
python3 test_engine.py                        # sanity check (no network)
python3 live.py                               # auto-detects your slot once draft is live
python3 live.py --slot 7                      # force your slot before draft_order is set
python3 data.py                               # print the ranked board and exit
```

The live screen shows: your recommended picks (with expected roster value + positional
cliffs), best available, your roster + unfilled slots, and recent picks to spot runs.
It refreshes automatically on every pick — no manual entry.

## Tune during the draft
Edit `overrides.py` (then restart) for things the feeds can't see:
- `GAMES_MISSED` — known IR/injury timetables (e.g. a player back midseason).
- `BUMP` — your own reads: `1.10` to like a player 10% more than consensus, `0.90` to fade.

## Files
`config.py` league constants + `.env` loader · `data.py` build the ranked board ·
`overrides.py` manual knobs · `engine.py` VOR + Monte Carlo · `live.py` live loop ·
`test_engine.py` checks · `docs/superpowers/specs/` design.

## Deliberate simplifications
K/DEF are suppressed from recommendations until your last picks (nobody drafts them
early). Opponent model is pure ADP-pressure (no per-team positional need). Rollouts
look ahead 5 of your picks, not the full 15 rounds — enough to price scarcity.
