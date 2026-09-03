"""In-season trade engine for the league.

Three things:
  1. LEAGUE DEFICIENCY MAP — every team's positional need/surplus, so you see who's weak where
     (your trade targets) and which positions are a leaguewide seller's market.
  2. TRADE FINDER — searches 1-for-1 / 2-for-1 / 2-for-2 swaps that upgrade YOUR starting lineup
     while the other side ALSO gains (win-win = they accept). Ranked by mutual benefit.
  3. Respects YOUR player values via overrides.VALUE_OVERRIDE (name -> your adj_proj) — so it never
     suggests moving a guy you're high on for one you're low on.

Roster patches: Sleeper lags a few minutes after a trade. Set MY_ROSTER / TEAM_PATCHES below to
correct the live snapshot until it syncs (leave empty once synced).

Run: python3 trades.py            (uses config.LEAGUE_ID / MY_USER_ID)
"""
import json, urllib.request
from itertools import combinations
import data, config, overrides

STARTERS = [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("K", 1), ("DEF", 1)]  # + FLEX from RB/WR/TE
# starter-caliber baselines per position (adj_proj a real weekly starter clears) — for need/surplus
STARTER_BAR = {"QB": 230, "RB": 170, "WR": 175, "TE": 130, "K": 110, "DEF": 100}

# --- roster patches for the Sleeper sync lag (clear once the app catches up) ---
MY_ROSTER = [   # your ACTUAL current roster by name (overrides the live snapshot); [] = use live
    "CeeDee Lamb", "Zay Flowers", "Ladd McConkey", "Matthew Golden", "Chase Brown", "Cam Skattebo",
    "Kenny Gainwell", "Alvin Kamara", "Kaleb Johnson", "Dak Prescott", "Sam Darnold", "Isaiah Likely",
    "Cam Little", "New England Patriots",
]
TEAM_PATCHES = {  # team_name -> {"add": [names], "drop": [names]} to fix a partner's post-trade roster
    "mdjorup": {"add": ["Rome Odunze", "Michael Pittman", "Sam LaPorta"], "drop": ["Cam Skattebo", "Isaiah Likely"]},
}


def _api(path):
    r = urllib.request.Request(f"https://api.sleeper.app/v1/{path}", headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r, timeout=20))


def _val(p):
    """A player's value for lineup math — your override wins, else the board's adj_proj."""
    return overrides.VALUE_OVERRIDE.get(p["name"], p["adj_proj"])


def lineup(roster):
    """Best legal starting-lineup total (QB/2RB/2WR/TE/2FLEX/K/DEF), using YOUR values."""
    by = {pos: sorted((_val(p) for p in roster if p["pos"] == pos), reverse=True)
          for pos in ("QB", "RB", "WR", "TE", "K", "DEF")}
    tot, used = 0.0, {}
    for pos, n in STARTERS:
        tot += sum(by[pos][:n]); used[pos] = n
    flex = []
    for pos in ("RB", "WR", "TE"):
        flex += by[pos][used[pos]:]
    flex.sort(reverse=True)
    return tot + sum(flex[: config.SLOTS["FLEX"]])


def load_league():
    """{name: {'players':[dicts], 'mine':bool}} off the live rosters, with patches applied."""
    players = data.build_players()
    idx = {p["pid"]: p for p in players}
    byname = {p["name"]: p for p in players}
    users = {u["user_id"]: (u.get("metadata", {}).get("team_name") or u.get("display_name") or u["user_id"])
             for u in _api(f"league/{config.LEAGUE_ID}/users")}
    out = {}
    for r in _api(f"league/{config.LEAGUE_ID}/rosters"):
        name = users.get(r.get("owner_id"), f"roster {r['roster_id']}")
        pls = [idx[pid] for pid in (r.get("players") or []) if pid in idx]
        out[name] = {"players": pls, "mine": r.get("owner_id") == config.MY_USER_ID}
    # apply patches
    for name, patch in TEAM_PATCHES.items():
        if name in out:
            keep = [p for p in out[name]["players"] if p["name"] not in patch.get("drop", [])]
            out[name]["players"] = keep + [byname[n] for n in patch.get("add", []) if n in byname]
    if MY_ROSTER:
        mine = next((v for v in out.values() if v["mine"]), None)
        if mine:
            mine["players"] = [byname[n] for n in MY_ROSTER if n in byname]
    return out, byname


def needs_surplus(roster):
    """(needs, surplus): positions below a startable bar (need) and extra startable bodies (surplus,
    tradeable). FLEX-aware: RB/WR/TE are judged against filling 2 starters + 2 flex = 4-ish slots."""
    pools = {pos: sorted([p for p in roster if p["pos"] == pos], key=lambda x: -_val(x))
             for pos in ("QB", "RB", "WR", "TE")}
    # how many startable-caliber at each flex position
    needs, surplus = [], []
    # flex-eligible starters needed ~= 2 RB + 2 WR + 1 TE + 2 flex; treat RB/WR as needing ~3-4 each
    tgt = {"QB": 1, "RB": 4, "WR": 4, "TE": 1}
    for pos, want in tgt.items():
        good = [p for p in pools[pos] if _val(p) >= STARTER_BAR[pos]]
        if len(good) < want - (1 if pos in ("RB", "WR") else 0):   # short of startable bodies
            needs.append(pos)
        surplus += good[want:]                                     # startable beyond what you start
    return needs, sorted(surplus, key=lambda x: -_val(x))


def league_report(teams):
    print("\n=== LEAGUE DEFICIENCY MAP (who to target) ===")
    pos_need = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
    for name, t in sorted(teams.items(), key=lambda kv: kv[1]["mine"], reverse=True):
        nd, sp = needs_surplus(t["players"])
        for p in nd:
            pos_need[p] = pos_need.get(p, 0) + 1
        tag = " (YOU)" if t["mine"] else ""
        nds = ("NEEDS " + "/".join(nd)) if nd else "balanced"
        sps = ", ".join(f"{p['pos']} {p['name'].split()[-1]}" for p in sp[:3])
        print(f"  {name[:16]:16}{tag:6} {nds:16}  surplus: {sps}")
    hot = sorted(pos_need.items(), key=lambda kv: -kv[1])
    print("  leaguewide seller's market:", ", ".join(f"{p}({n} teams need)" for p, n in hot if n) or "none")


def find_trades(min_gain=4.0, min_theirs=-5.0, top=12):
    teams, byname = load_league()
    mine = next((v for v in teams.values() if v["mine"]), None)
    my_base = lineup(mine["players"])
    my_set = {p["pid"] for p in mine["players"]}
    deals = []
    for name, t in teams.items():
        if t["mine"]:
            continue
        tb = lineup(t["players"])
        # candidate send/get bundles: 1-for-1, 2-for-1 (consolidate up), 2-for-2
        my_pool = [p for p in mine["players"] if p["pos"] not in ("K", "DEF")]
        th_pool = [p for p in t["players"] if p["pos"] not in ("K", "DEF")]
        sends = [(a,) for a in my_pool] + list(combinations(my_pool, 2))
        gets = [(b,) for b in th_pool] + list(combinations(th_pool, 2))
        for snd in sends:
            for get in gets:
                if abs(len(snd) - len(get)) > 1:            # keep bundles balanced-ish
                    continue
                nm = [p for p in mine["players"] if p not in snd] + list(get)
                nt = [p for p in t["players"] if p not in get] + list(snd)
                dmine = lineup(nm) - my_base
                dtheirs = lineup(nt) - tb
                if dmine >= min_gain and dtheirs >= min_theirs:
                    deals.append({"team": name, "snd": snd, "get": get, "dmine": dmine, "dtheirs": dtheirs})
    # rank by the weaker side's gain (acceptability), then prefer SMALLER packages, then my gain
    deals.sort(key=lambda d: (round(min(d["dmine"], d["dtheirs"])), -len(d["snd"]) - len(d["get"]),
                              d["dmine"]), reverse=True)
    # dedupe: one deal per (partner, best player received) — collapses throw-in variants of one swap
    seen, uniq = set(), []
    for d in deals:
        top_get = max(d["get"], key=_val)["name"]
        k = (d["team"], top_get)
        if k in seen:
            continue
        seen.add(k); uniq.append(d)
    return mine, my_base, uniq[:top]


def _names(bundle):
    return " + ".join(f"{p['pos']} {p['name'].split()[-1]}" for p in bundle)


if __name__ == "__main__":
    teams, _ = load_league()
    league_report(teams)
    mine, base, deals = find_trades()
    nd, sp = needs_surplus(mine["players"])
    print(f"\n=== YOUR TEAM (lineup {base:.0f}) — needs: {'/'.join(nd) or 'none'} · "
          f"surplus: {', '.join(p['name'].split()[-1] for p in sp[:4])} ===")
    print("\n=== BEST WIN-WIN TRADES FOR YOU ===")
    for d in deals:
        wl = "win-win" if d["dtheirs"] >= 0 else "slight give"
        print(f"  +{d['dmine']:4.0f} you | {d['dtheirs']:+5.0f} them ({wl:10})  "
              f"SEND {_names(d['snd']):28} -> GET {_names(d['get']):28} @ {d['team']}")
    if not deals:
        print("  no win-win upgrades found — your starters are hard to improve by trade right now.")
