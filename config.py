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

# --- season-sim objective (variance-aware expected wins) ---
USE_WIN_VALUE = True    # False -> fall back to deterministic sum-of-projections leaf
REG_WEEKS = 14          # H2H regular-season weeks (playoffs start week 15)
RISK_LAMBDA = 0.0       # >0 chases ceiling (μ+λσ), <0 chases floor. 0 = pure E[wins].
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

# --- opponent modeling: how simulated opponents pick (beyond raw ADP) ---
OPP_NEED_BETA = 0.55    # boost positions an opponent still needs (roster-need pressure)
OPP_RUN_GAMMA = 0.45    # boost positions running hot recently (position-run contagion)
OPP_RUN_K = 8           # sliding window (picks) for run detection

# --- roster synergy: correlations/combinations the sim should reward ---
STACK_RHO = 0.35        # QB <-> same-team pass-catcher weekly correlation (raises ceiling)
STACK_MU = 1.2          # weekly ceiling value added per QB+pass-catcher stack among starters
HANDCUFF_BONUS = 0.08   # expected-wins bump per rostered handcuff of your own RB (insurance)
