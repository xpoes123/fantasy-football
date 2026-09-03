"""In-season trade finder: scan every roster in the league, find 1-for-1 swaps that UPGRADE MY
starting lineup (trade from surplus into need) while the other side also gains (or stays fair) so
they'd actually accept. Values everything off the live board (adj_proj), scored by best-lineup.

Run: python3 trades.py            (uses config.LEAGUE_ID / MY_USER_ID)
"""
import json, urllib.request
import data, config

SLOTS = [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("K", 1), ("DEF", 1)]  # + FLEX from RB/WR/TE


def _api(path):
    r = urllib.request.Request(f"https://api.sleeper.app/v1/{path}", headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r, timeout=20))


def lineup(roster):
    """Best legal starting-lineup projected total (adj_proj)."""
    by = {pos: sorted((p["adj_proj"] for p in roster if p["pos"] == pos), reverse=True)
          for pos in ("QB", "RB", "WR", "TE", "K", "DEF")}
    tot, used = 0.0, {}
    for pos, n in SLOTS:
        tot += sum(by[pos][:n]); used[pos] = n
    flex = []
    for pos in ("RB", "WR", "TE"):
        flex += by[pos][used[pos]:]
    flex.sort(reverse=True)
    return tot + sum(flex[: config.SLOTS["FLEX"]])


def load_league():
    """{roster_id: {'name':..., 'players':[player dicts], 'mine':bool}} off the live rosters."""
    players = data.build_players()
    idx = {p["pid"]: p for p in players}
    rosters = _api(f"league/{config.LEAGUE_ID}/rosters")
    users = {u["user_id"]: (u.get("metadata", {}).get("team_name") or u.get("display_name") or u["user_id"])
             for u in _api(f"league/{config.LEAGUE_ID}/users")}
    out = {}
    for r in rosters:
        pls = [idx[pid] for pid in (r.get("players") or []) if pid in idx]
        out[r["roster_id"]] = {"name": users.get(r.get("owner_id"), f"roster {r['roster_id']}"),
                               "players": pls, "mine": r.get("owner_id") == config.MY_USER_ID}
    return out


def find_trades(min_my_gain=3.0, top=15):
    league = load_league()
    mine = next((v for v in league.values() if v["mine"]), None)
    if not mine:
        raise SystemExit("couldn't find your roster — check config.MY_USER_ID")
    my_base = lineup(mine["players"])
    deals = []
    for rid, t in league.items():
        if t["mine"]:
            continue
        their_base = lineup(t["players"])
        for a in mine["players"]:                      # I send a
            for b in t["players"]:                     # I get b
                if a["pos"] in ("K", "DEF") or b["pos"] in ("K", "DEF"):
                    continue
                new_mine = [p for p in mine["players"] if p is not a] + [b]
                new_theirs = [p for p in t["players"] if p is not b] + [a]
                dmine = lineup(new_mine) - my_base
                dtheirs = lineup(new_theirs) - their_base
                # only realistic deals: I gain AND the other side also gains (win-win) or stays
                # fair. A swap where they lose big is a fantasy they'd never accept — drop it.
                if dmine >= min_my_gain and dtheirs >= -4:
                    deals.append({"team": t["name"], "send": a, "get": b,
                                  "dmine": dmine, "dtheirs": dtheirs})
    # rank by the WEAKER side's gain — the most mutually-beneficial (and thus acceptable) first
    deals.sort(key=lambda d: min(d["dmine"], d["dtheirs"]), reverse=True)
    return mine, my_base, deals[:top]


if __name__ == "__main__":
    mine, base, deals = find_trades()
    print(f"\n=== TRADE FINDER — your best upgrades (lineup base {base:.0f}) ===\n")
    for d in deals:
        s, g = d["send"], d["get"]
        wl = "win-win" if d["dtheirs"] >= 0 else ("fair" if d["dtheirs"] > -8 else "THEY LOSE — hard sell")
        print(f"  +{d['dmine']:4.0f} you | {d['dtheirs']:+5.0f} them ({wl:20})  "
              f"SEND {s['pos']} {s['name'][:16]:16} -> GET {g['pos']} {g['name'][:16]:16}  @ {d['team'][:18]}")
    if not deals:
        print("  no lineup-upgrading 1-for-1s found — your starters are hard to improve via single swaps.")
