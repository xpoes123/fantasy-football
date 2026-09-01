# Fantasy Draft Advisor — Session Handoff & Context

> Living doc for future Claude sessions. Read this first. Captures what the tool is, how it
> works, what we learned drafting live with it, and the roadmap. Last updated after the
> 2026-08-31 live draft of "Touchdowns and Transactions" (David drafted slot 10).

## What this is
A live, opponent-aware Sleeper draft advisor for David's fantasy football leagues. Terminal
tool (`live.py`) + deployed web app (`web.py` → **fantasy.djiang.xyz**, FastAPI/uvicorn on the
Hetzner VPS, systemd unit `fantasy`, Caddy reverse-proxy, port 7793, deploy key clone of the
private repo `xpoes123/fantasy-football`). Polls the live Sleeper draft and, after every pick,
recommends the optimal pick — accounting for scarcity, roster construction, and how opponents
are actually drafting.

## David's 4 leagues (all PPR; money ~equal, but stakes/relationships differ)
1. **Touchdowns and Transactions** (12-team) — work randoms — cares LEAST; used as the live test.
   `league 1395399704828723200`, `draft 1395399705847947264`, David = `xpoes`
   `1393861289477959680`, drafted **slot 10**.
2. **Work pod league** (12-team, slot **11**) — **NEXT DRAFT (2 days out from 2026-08-31).**
3. **High school friends league**
4. **Friend group league** (newer)
Auto-discover all via `GET /user/1393861289477959680/leagues/nfl/2026`. Sizes: 8/12/12/14, all
PPR. Flex differs: 12-team = 2 FLEX (RB/WR/TE); 8- & 14-team = 1 WRRB_FLEX (RB/WR only).

## How the model works (pipeline)
`adj_proj = blended_projection × Vegas × age × injury × SOS × coaching × BUMP(scheme/role) × WEDGES`
then **VOR** = adj_proj − replacement-level, then the **VONA Monte Carlo** engine.

- **Projections** (`data.py`): **RotoWire (via `api.sleeper.com/projections`) blended with ESPN**,
  joined on Sleeper `player_id` (fallback: espn_id, then normalized name+pos). Blending denoises
  per-source outliers. `pts_ppr`.
- **Adjustment layers** (`data.py`): Vegas team implied-points (Odds API), position age curves,
  injury/availability haircut (`injury_mult` + `overrides.GAMES_MISSED`), strength-of-schedule
  (`SOS_TEAM`, season DVP + Wk15-17 playoff slate), coaching prowess (`COACHING`), scheme/role
  `BUMP` (126 entries, from research), and `WEDGES` (TD-regression + O-line + opportunity +
  durability, merged into one damped/clamped factor).
- **Engine** (`engine.py`): VOR + a **variance-aware season objective** — each starter gets a
  weekly μ/σ (σ from position CV), team weekly score ~N(μ_T,σ_T²), objective = expected H2H wins
  = `Σweeks · Φ((μ_T−μ_L)/√(σ_T²+σ_L²))` vs a league-average team. Roster completed to 15 (incl.
  guaranteed QB/TE/K/DEF) before scoring. `RISK_LAMBDA` knob chases ceiling (μ+λσ). Stacks
  (QB↔pass-catcher) add covariance + a ceiling bonus; handcuff-of-own-RB adds insurance value.
- **Opponent model** (`engine._opp_pick`): ADP-pressure with **ADP-scaled spread** (elites barely
  slide) + chaos floor + **per-opponent roster-NEED boost** + **run-contagion**, seeded from the
  REAL draft (slot→positions from live picks). Makes survival draft-specific.
- **Survival + recs** (`engine.survival_probs`, `recommend`; surfaced in `web.py`): P(player
  available at your next pick). Recs split into **targets** (survival ≥45%) vs **snap-if-they-fall**;
  ranked by **urgency-adjusted value** (discount safe-forever survivors so scarce picks lead);
  **pair plan** for your next two picks; positional **tier cliffs**, **run alerts**, **byes**
  (stacked-bye warnings), **handcuffs**, and **leverage flags** (🔒 = handcuff to an opponent's RB).
- **Manual knobs** (`overrides.py`): `GAMES_MISSED` (injury/suspension games), `BUMP` (per-player
  multipliers), `HANDCUFFS`, `WEDGES`. Case-insensitive name match.

## Files
`config.py` (league consts + knobs) · `data.py` (build the board) · `engine.py` (VOR + MC +
survival + opponent model) · `overrides.py` (manual knobs) · `live.py` (terminal loop) ·
`web.py` (FastAPI + `/api/state`) · `static/index.html` (Tokyo-Night dashboard) ·
`test_engine.py` · `deploy/` (systemd unit + Caddy snippet).

## What we learned drafting live with it (KEY)
The model is **strong through the structured early/mid rounds** and **blind in two areas**:
1. **News/situation lag** — biggest weakness. Stale ADP & projections missed MarShawn Lloyd's
   surge (Jacobs went to Commissioner's Exempt list → Lloyd = GB lead back; had to manually bump
   1.15→1.50). The model doesn't transfer an out-starter's workload to the handcuff. The
   pre-draft **research-agent sweep** (injuries/scheme/wedges) was the single most valuable thing —
   re-run it fresh before every draft.
2. **Roster-construction nuance** — needed live fixes: don't recommend a 2nd QB/TE you're set at;
   don't push a 5th WR when saturated; don't rank a safe-forever QB over scarce picks (urgency
   fix); guarantee QB/TE in roster-completion (was wildly over-valuing an early QB/TE).
Also human beat the model on: **DEF-vs-your-roster correlation** (took Patriots D over Minnesota
because David had 7 NFC-North players — model only sees raw DEF projection) and **late-round
upside darts** (Nailor as a Mendoza-LV-QB bet).

Bugs fixed live (all shipped): name-join dropping stars, projection source (ESPN→blend), PPR-
neutral replacement ranks, softened preseason injury tags, off-board roster resolution, slot-
source guard, K/DEF gating, stale-cache resilience, survival-aware recs, urgency re-rank,
2nd-QB/TE gate, QB/TE roster-completion, leverage-flag label, XSS escaping. **Verify claims
against the live board before trusting — we got burned assuming "not in top-18" meant available.**

## Draft result (Touchdowns and Transactions, slot 10)
QB Goff · RB Hampton/Lloyd/Tuten/Gainwell/K.Johnson · WR ARSB/Zay/Odunze/Reed/Nailor · TE
Loveland · DEF NE+JAX · K Trey Smack. Strong: elite WR corps, whole GB backfield cornered
(Lloyd+K.Johnson insurance), scarce TE at value, smart correlation/streaming calls.

## Improvement roadmap
**SHIPPED (post-test-draft iteration, before the work-pod draft):**
- ✅ **Waiver-aware value** — `REPL_RANK` recalibrated to waiver depth (moderate RB-scarcity
  tilt: RB38/WR44/TE14/QB13). RB priced over what you can stream, not the last starter.
- ✅ **Upside mode** (late rounds) — `engine.upside_score`: once starters full or round ≥
  `UPSIDE_ROUND`, rank bench by ceiling (boom variance + handcuff-path + youth), discount
  streamable K/DEF/2nd-QB (`STREAM_DISCOUNT`).
- ✅ **Saturation awareness** (`config.SATURATION`) — discount a position you're already deep
  at (kills the "5th WR" spam). Plus existing hard-gates on 2nd QB/TE.
- ✅ **Handcuff workload-transfer** (`data.py`) — starter marked out (GAMES_MISSED ≥ 8) →
  auto-boost the backup's adj_proj by `starter.proj × (gm/17) × 0.32`. Lloyd auto-lands ~RB20.
- ✅ **DEF smarts** — `data.DIVISIONS` + `data.def_matchups()`; web attaches per-DEF
  `{conflict, matchup}`: roster-division conflict (Patriots-over-MIN call) + Week-1 opponent
  implied-points softness. Shown on DEF rows.
- ✅ **Player lookup** — `/api/player?q=` + header search box: any player's value + availability.
- ✅ **ADP_OVERRIDE** knob (`overrides.py`) — robust fresher-ADP (research sweep fills it;
  FantasyPros scrape was too brittle to depend on).

**STILL TODO:**
1. **Multi-league support** (must-have for the 8/14-team leagues) — per-league num_teams/slots/
   flex + replacement ranks; league picker in UI. Board (adj_proj, PPR) is shared; engine params
   differ. Current approach: repoint `config.py` per league (done manually for work-pod slot 11).
2. **Fresh pre-draft research sweep as one command** — re-run the injury/suspension + scheme/
   role + wedge subagents against the target league, auto-update `overrides.py`. Run day-of.
   THE remaining fix for news-lag. (Mechanisms to consume it — workload-transfer, ADP_OVERRIDE,
   BUMP/GAMES_MISSED — are all built; just need the automated sweep.)

## Operating it live (per draft)
1. Point `config.py` at the league's `LEAGUE_ID`/`DRAFT_ID`/`MY_USER_ID` + set `DEFAULT_SLOT`
   (auto-detects from `draft_order` once live). (Multi-league picker will replace this.)
2. Set `ODDS_API_KEY` in `.env` (gitignored).
3. Edit `overrides.py` for known injuries/suspensions/reads (or run the research sweep).
4. Deploy: commit → push → on VPS `cd /opt/fantasy && git pull && systemctl restart fantasy`.
5. Watch **fantasy.djiang.xyz** — auto-detects your slot, lights up on your pick, updates each pick.
6. Response ~1-2s on the clock (cached between polls); 3s frontend poll.

## 2026-09-01 session — objective rebuilt (game-theory + payouts)
David steered: the model must adapt to opponents and maximize PAYOUT EV, not run a fixed strategy.
- **`engine.finish_equity` / `config.OBJECTIVE="finish"`** — leaf is now payout-weighted EV of
  final standing (Binomial-over-field finish dist × `config.PAYOUT`). Ceiling-seeking is ENDOGENOUS
  → **RISK_LAMBDA upside hack retired** (don't reintroduce it). Payouts per league in `config.PAYOUTS`.
- **Over-love fix (`data.py`)** — log-damp-cap soft priors (±20% max) + market-blend toward ADP
  (keep edges, kill extremes). Hampton RB3→RB5. Late saturation brake 0.35→0.12.
- **`backtest.py`** — 2024 preseason→actual: model 2398pts/finish 1.20 beats ADP 2025/4.00 &
  proj-only 2101/2.50. Run for more slots/seasons.
- **Committee flag** (`web.committee_map`, info only) — draftable RB whose mate is also drafted =
  timeshare. `presnap`/`pretouch`/`depth` on players. `config.SEASON="2026"`.
- **UI** — loading bar + `board_age_s`/`computed_ms` freshness.
- **Deploy note:** VPS `git pull --ff-only` can refuse if the tree diverged — use
  `git fetch && git reset --hard origin/main` to force-sync (it's a deploy clone, safe).
- **Open thread:** finish-EV saturates early (VOR breaks ties). Fix: complete rollout rosters with
  realistic ADP-discounted survivors, not best-available. Plus the day-of research sweep.
