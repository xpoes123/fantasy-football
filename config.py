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

LEAGUE_ID = "1395399704828723200"
DRAFT_ID = "1395399705847947264"
MY_USER_ID = "1393861289477959680"  # xpoes / "David RAMP"

NUM_TEAMS = 12
ROUNDS = 15

# starting lineup slots (from Sleeper draft settings)
SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}
FLEX_POS = ("RB", "WR", "TE")
BENCH = 5

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")  # set in .env (gitignored)

POLL_SECONDS = 3
CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "cache")
