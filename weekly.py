"""Weekly matchup-aware projections — the in-season backbone.

Sleeper serves RotoWire's per-week PPR projections (already opponent-adjusted) at
api.sleeper.com/projections/nfl/{season}/{week}. This replaces the season-total/17 proxy the
in-season code used, so start/sit, streaming and waivers become matchup-accurate.

Players with no weekly line (deep bench / not projected to play) return None — callers fall back to
the season proxy (adj_proj / GAMES).
"""
import data, config

_UA = {"User-Agent": "Mozilla/5.0"}
_POS = ("QB", "RB", "WR", "TE", "K", "DEF")


def weekly_proj(week, season=None, ttl=21600):
    """pid -> projected PPR points for `week` (dict). Empty if the week isn't published yet.
    Cached 6h on disk (projections update through Wed); same cache/stale-serve as data._get."""
    season = season or config.SEASON
    q = "&".join(f"position[]={p}" for p in _POS)
    url = f"https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular&{q}"
    out = {}
    for row in data._get(url, headers=_UA, ttl=ttl) or []:
        pts = (row.get("stats") or {}).get("pts_ppr")
        if pts is not None:
            out[row["player_id"]] = round(pts, 2)
    return out


def wk_points(p, week, wk):
    """This week's projected points for player dict `p`: live weekly line if present, else the
    season proxy (adj_proj / GAMES). Callers still zero out bye/injured players themselves."""
    if not p:
        return -1.0
    v = wk.get(p["pid"])
    return v if v is not None else p["adj_proj"] / config.GAMES


if __name__ == "__main__":   # smoke check: current week has projections and they look weekly-scaled
    import json, urllib.request
    st = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://api.sleeper.app/v1/state/nfl", headers=_UA)))
    wk = weekly_proj(st.get("week") or 1)
    assert wk, "no weekly projections returned"
    top = max(wk.values())
    assert 5 < top < 60, f"weekly points look wrong: max {top}"   # a weekly total, not a season total
    print(f"ok — {len(wk)} players, max {top} pts")
