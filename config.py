"""Static league config + env. Everything the tool needs to know that doesn't change."""
import os

# load .env (gitignored) if present — no dependency, keeps secrets out of git
_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Work pod league: "Fantasy Deployed Engineering" (12-team PPR snake) — next draft.
LEAGUE_ID = "1395587120424316928"
DRAFT_ID = "1395587120973746176"
MY_USER_ID = "1393861289477959680"  # xpoes / "David RAMP"

SEASON = "2026"     # NFL season being drafted (projections, byes, preseason usage all key off this)
NUM_TEAMS = 12
ROUNDS = 15
DEFAULT_SLOT = 11  # David drafts slot 11 in the work-pod league; auto-detects once draft_order sets

# starting lineup slots (from Sleeper draft settings)
SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}
FLEX_POS = ("RB", "WR", "TE")
BENCH = 5

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")  # set in .env (gitignored)

POLL_SECONDS = 3
CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "cache")

# --- season-sim objective ---
# "finish": payout-weighted EV of your final standing (opponent-aware + prize-structure aware —
#           ceiling-seeking falls out endogenously). "wins": legacy expected-wins. "sum": raw proj.
OBJECTIVE = "finish"
USE_WIN_VALUE = True    # (legacy) only consulted when OBJECTIVE == "wins"
REG_WEEKS = 14          # H2H regular-season weeks (playoffs start week 15)
RISK_LAMBDA = 0.0       # >0 chases ceiling (μ+λσ), <0 chases floor. 0 = pure E[wins]. (wins-mode only)

# --- payouts: what each finishing place pays, per league (drives the finish-EV objective) ---
# Money is what you actually maximize. Only paid places matter; steeper top-heavy payouts =>
# more ceiling-seeking (chase 1st) since a "safe" non-paying finish is worth $0.
PAYOUTS = {
    "1395587120424316928": {1: 8, 2: 3, 3: 1},          # work pod "team": 8x/3x/money-back (of buy-in)
    # Poverty Franchises (fill league id when known): top-4 $400/$150/$100/$50
    "_poverty": {1: 400, 2: 150, 3: 100, 4: 50},
}
PAYOUT = PAYOUTS.get(LEAGUE_ID, {1: 8, 2: 3, 3: 1})
PLAYOFF_TEAMS = 6       # top-N make the playoffs (unused by v1 season-rank model; kept for bracket ext.)
# weekly coefficient of variation by position (how boom/bust a weekly score is)
POS_CV = {"QB": 0.30, "RB": 0.55, "WR": 0.65, "TE": 0.75, "K": 0.70, "DEF": 0.90}
GAMES = 17              # games a season projection is spread across

# --- late-round "upside mode" + waiver-streamable discount ---
# Once your starters are full (or ~round 9+), rank bench picks by CEILING, not floor, and
# devalue anything you can just stream off waivers.
UPSIDE_ROUND = 9        # bench/upside mode kicks in from this round (or when starters full)
UPSIDE_CV_LEAN = 0.5    # how much boom variance boosts the ceiling score
UPSIDE_HANDCUFF = 1.40  # multiplier for a handcuff (real path to a workhorse role)
UPSIDE_YOUTH = 1.20     # multiplier for young ascending RB/WR (age <= UPSIDE_YOUNG_AGE)
UPSIDE_YOUNG_AGE = 23
STREAM_DISCOUNT = 0.30  # K/DEF and a 2nd QB are freely streamable -> heavy discount
# beyond this many at a position, extras are low-value depth -> discount in upside mode
# (this is what stops it recommending a 5th WR when you're already deep there)
SATURATION = {"RB": 5, "WR": 4, "TE": 1, "QB": 1}

# --- opponent modeling: how simulated opponents pick (beyond raw ADP) ---
OPP_NEED_BETA = 0.55    # boost positions an opponent still needs (roster-need pressure)
OPP_RUN_GAMMA = 0.45    # boost positions running hot recently (position-run contagion)
OPP_RUN_K = 8           # sliding window (picks) for run detection

# --- value calibration: tame compounding priors + regress model toward market ---
# The soft situational multipliers (vegas env, age, SOS, coaching, manual bumps/wedges) all
# partly proxy "good offense" and used to MULTIPLY into runaway over-love. Combine them in
# log-space with a damping exponent and a hard cap so no stack of priors moves a projection
# more than the cap. (Injury/availability is separate — a real haircut, not capped.)
SIGNAL_DAMP = 0.6       # <1 shrinks the combined multiplier toward 1.0 (0 = ignore all priors)
SIGNAL_CAP_LO = 0.80    # a stack of priors can't drop a projection below −20%...
SIGNAL_CAP_HI = 1.20    # ...nor lift it above +20%
# Market blend: regress each model value toward the ADP-implied value for that slot. Keeps the
# edge for modest divergence, yanks extreme divergence back to consensus (kills Hampton/Zay
# over-love without becoming "just follow ADP").
BLEND_FREE = 0.12       # divergence (fraction of market value) kept fully — your real edge
BLEND_K = 3.0           # shrink rate beyond BLEND_FREE (bigger = harder pull to market)

# --- roster synergy: correlations/combinations the sim should reward ---
STACK_RHO = 0.35        # QB <-> same-team pass-catcher weekly correlation (raises ceiling)
STACK_MU = 1.2          # weekly ceiling value added per QB+pass-catcher stack among starters
HANDCUFF_BONUS = 0.08   # expected-wins bump per rostered handcuff of your own RB (insurance)
