"""Constant monitor for all of David's drafted leagues: surfaces hot WAIVER adds and the best
win-win TRADES, as a digest you can run on a schedule.

Waivers use two signals: (1) Sleeper's leaguewide TRENDING adds (real-time role-change/breakout
hype) intersected with who's actually available in YOUR league, and (2) the best available body at
each position (for bye/injury/streaming). Trades reuse the trade engine.

Run: python3 monitor.py            (all drafted 2026 leagues for config.MY_USER_ID)
     python3 monitor.py --md       (markdown, for posting to Sage / the share site)
     python3 monitor.py --post     (post the digest to David via Sage's Discord bot)
"""
import json, os, sys, urllib.request
from collections import defaultdict
import data, config, trades

MD = "--md" in sys.argv or "--post" in sys.argv
LINEUP_ONLY = "--lineup-only" in sys.argv   # only the time-sensitive set-your-lineup checks
SPIKE = 40000   # trending-add count that counts as a "stampede" worth an urgent ping
BAD_INJ = {"Out", "IR", "PUP", "Sus", "DNR", "NA", "Doubtful"}   # won't (likely) play this week
FLEX_POS = ("RB", "WR", "TE")
STREAM_POS = ("QB", "K", "DEF")   # positions you routinely stream week-to-week
MIN_SWAP_WK = 1.5   # only flag a start/sit worth ~1.5+ pts/week (season adj_proj / 17)
SAGE_NOTIFY = os.environ.get("SAGE_NOTIFY_URL", "http://127.0.0.1:7779/notify")


def post_sage(title, body, level="info"):
    """Post the digest to David via Sage's /notify endpoint (bearer SAGE_NOTIFY_KEY). Sage truncates
    each message to 1900 chars, so chunk the body and title each piece."""
    key = os.environ.get("SAGE_NOTIFY_KEY")
    if not key:
        print("(no SAGE_NOTIFY_KEY set — printed only)"); return
    chunks, cur = [], ""
    for line in body.split("\n"):
        if len(cur) + len(line) + 1 > 1700:   # leave room for the '**[LEVEL]** <title>\n' prefix
            chunks.append(cur); cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    for i, chunk in enumerate(chunks):
        t = title if len(chunks) == 1 else f"{title} ({i + 1}/{len(chunks)})"
        req = urllib.request.Request(SAGE_NOTIFY, data=json.dumps(
            {"level": level, "title": t, "body": chunk}).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)


def _api(path):
    r = urllib.request.Request(f"https://api.sleeper.app/v1/{path}", headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r, timeout=20))


def drafted_leagues():
    out = []
    for L in _api(f"user/{config.MY_USER_ID}/leagues/nfl/{config.SEASON}"):
        did = L.get("draft_id")
        try:
            if did and _api(f"draft/{did}").get("status") == "complete":
                out.append((L["league_id"], L.get("name", "?"), L.get("total_rosters", 12)))
        except Exception:
            pass
    return out


def trending_add(limit=40):
    """player_id -> add count over the last 24h (leaguewide waiver hype)."""
    try:
        rows = _api(f"players/nfl/trending/add?lookback_hours=24&limit={limit}")
        return {r["player_id"]: r.get("count", 0) for r in rows}
    except Exception:
        return {}


def current_week():
    try:
        return _api("state/nfl").get("week") or 1
    except Exception:
        return 1


def fresh_injuries():
    """pid -> live injury_status, on a 30-min cache (the board's Sleeper meta is cached 24h — too
    stale for a set-your-lineup alert)."""
    try:
        return {pid: m.get("injury_status") for pid, m in data.sleeper_players(ttl=1800).items()}
    except Exception:
        return {}


def wval(p, week):
    """Weekly value proxy: 0 if on bye or won't play, else season adj_proj as a talent proxy.
    # ponytail: no per-week matchup projections available; adj_proj is the proxy. Upgrade to a
    # weekly source if one appears."""
    if not p:
        return -1.0
    if p.get("bye") == week or p.get("inj") in BAD_INJ:
        return 0.0
    return p["adj_proj"]


def optimize(pool, slots, week):
    """Best legal starting lineup from `pool` given Sleeper `slots` (roster_positions minus BN)."""
    avail = sorted([p for p in pool if p], key=lambda p: -wval(p, week))
    chosen, used = [], set()
    for s in [x for x in slots if x != "FLEX"]:
        c = next((p for p in avail if id(p) not in used and p["pos"] == s), None)
        if c:
            used.add(id(c)); chosen.append(c)
    for _ in [x for x in slots if x == "FLEX"]:
        c = next((p for p in avail if id(p) not in used and p["pos"] in FLEX_POS), None)
        if c:
            used.add(id(c)); chosen.append(c)
    return chosen


def lineup_alerts(league_id, week, idx, inj_now, board, rostered):
    """For MY roster this week: (a) OUT/IR/bye players still in the starting lineup, (b) start/sit
    swaps where a bench player out-projects a starter, (c) K/DEF/QB streams when a starter can't go."""
    try:
        slots = [s for s in _api(f"league/{league_id}").get("roster_positions", []) if s != "BN"]
        mine = next((r for r in _api(f"league/{league_id}/rosters")
                     if r.get("owner_id") == config.MY_USER_ID), None)
        mm = next((m for m in _api(f"league/{league_id}/matchups/{week}")
                   if mine and m.get("roster_id") == mine["roster_id"]), None)
        if not mm:
            return None
    except Exception:
        return None

    # build each rostered player ONCE (with a fresh injury overlay) so object identity is stable
    # across the started/roster/optimal lists — else the same player has different id()s.
    pmap = {pid: {**idx[pid], "inj": inj_now.get(pid, idx[pid].get("inj"))}
            for pid in (mm.get("players") or []) if pid in idx and pid != "0"}
    started = [pmap[pid] for pid in (mm.get("starters") or []) if pid in pmap]
    roster = list(pmap.values())

    out_in = [p for p in started if p["inj"] in BAD_INJ or p.get("bye") == week]
    best = optimize(roster, slots, week)
    in_best, in_set = {id(p) for p in best}, {id(p) for p in started}
    # pair swaps only within a legal slot class: QB/K/DEF swap same-position, RB/WR/TE interchange via FLEX
    cls = lambda pos: pos if pos in ("QB", "K", "DEF") else "FLX"
    ups, downs = defaultdict(list), defaultdict(list)
    for p in best:
        if id(p) not in in_set:
            ups[cls(p["pos"])].append(p)
    for p in started:
        if id(p) not in in_best:
            downs[cls(p["pos"])].append(p)
    swaps = []
    for c in ups:
        u = sorted(ups[c], key=lambda p: -wval(p, week))
        d = sorted(downs.get(c, []), key=lambda p: wval(p, week))
        for up, dn in zip(u, d):
            delta = (wval(up, week) - wval(dn, week)) / 17.0   # season adj_proj -> pts/week
            if delta >= MIN_SWAP_WK:
                swaps.append((up, dn, delta))
    swaps.sort(key=lambda t: -t[2])

    stream = []
    for pos in STREAM_POS:
        starter = next((p for p in started if p["pos"] == pos), None)
        if starter and wval(starter, week) == 0:   # your guy is bye/out this week
            fa = sorted((p for p in board if p["pos"] == pos and p["pid"] not in rostered
                         and wval(p, week) > 0), key=lambda p: -wval(p, week))
            if fa:
                stream.append((pos, starter, fa[0]))
    return {"out_in": out_in, "swaps": swaps, "stream": stream}


def scan_league(league_id, teams_n, trend, board, idx, week=None, inj_now=None):
    config.LEAGUE_ID = league_id
    config.NUM_TEAMS = teams_n
    trades.MY_ROSTER = []; trades.TEAM_PATCHES = {}   # live rosters (no patches for the monitor)
    teams, _ = trades.load_league()
    mine = next((v for v in teams.values() if v["mine"]), None)
    if not mine:
        return None
    rostered = {p["pid"] for t in teams.values() for p in t["players"]}
    base = trades.lineup(mine["players"])
    needs, _sp = trades.needs_surplus(mine["players"])

    # HOT waivers: trending adds that are available here (esp. at a position you need)
    hot = []
    for pid, cnt in sorted(trend.items(), key=lambda kv: -kv[1]):
        p = idx.get(pid)
        if not p or pid in rostered or p["pos"] not in ("QB", "RB", "WR", "TE"):
            continue
        gain = trades.lineup(mine["players"] + [p]) - base
        hot.append((p, cnt, gain, p["pos"] in needs))
        if len(hot) >= 8:
            break
    # best available body at each position (streaming / bye fill)
    best = {}
    for pos in ("QB", "RB", "WR", "TE"):
        avail = sorted((p for p in board if p["pid"] not in rostered and p["pos"] == pos),
                       key=lambda x: -x["adj_proj"])
        best[pos] = avail[0] if avail else None
    # time-sensitive set-your-lineup checks (OUT-in-lineup / start-sit / streaming)
    alerts = lineup_alerts(league_id, week, idx, inj_now or {}, board, rostered) if week else None
    if LINEUP_ONLY:
        return {"needs": needs, "alerts": alerts}
    # trades
    _m, _b, deals = trades.find_trades(top=3)
    return {"needs": needs, "base": base, "hot": hot, "best": best, "deals": deals, "alerts": alerts}


def _lineup_section(h, a):
    """Render the set-your-lineup alerts (shared by full digest and --lineup-only)."""
    for p in a["out_in"]:
        why = "BYE" if p["inj"] not in BAD_INJ else p["inj"]
        h(f"🚑 {p['pos']} {p['name']} is **{why}** but still in your lineup — bench him")
    for up, down, d in a["swaps"]:
        h(f"🔀 start {up['pos']} {up['name']} over {down['name']} (+{d:.1f}/wk)")
    for pos, starter, fa in a["stream"]:
        why = "on bye" if starter.get("inj") not in BAD_INJ else starter["inj"]
        h(f"📡 stream {pos}: {starter['name']} is {why} — best available is {fa['name']}")


def _has_alerts(a):
    return bool(a and (a["out_in"] or a["swaps"] or a["stream"]))


def main():
    board = data.build_players()
    idx = {p["pid"]: p for p in board}
    week = current_week()
    inj_now = fresh_injuries()
    trend = {} if LINEUP_ONLY else trending_add()
    lines = []
    h = (lambda s: lines.append(s))
    hdr = f"Week {week}" + (" — set your lineup" if LINEUP_ONLY else "")
    h(f"# 🏈 Fantasy monitor — {hdr}" if MD else f"=== FANTASY MONITOR ({hdr}) ===")
    league_results = []
    for lid, name, tn in drafted_leagues():
        r = scan_league(lid, tn, trend, board, idx, week=week, inj_now=inj_now)
        league_results.append(r)
        if not r:
            continue
        if LINEUP_ONLY:
            if _has_alerts(r.get("alerts")):
                h(f"\n## {name}" if MD else f"\n--- {name} ---")
                _lineup_section(h, r["alerts"])
            continue
        h(f"\n## {name} ({tn}-team)" if MD else f"\n--- {name} ({tn}-team) ---")
        h(f"needs: {'/'.join(r['needs']) or 'none'}")
        if _has_alerts(r.get("alerts")):
            _lineup_section(h, r["alerts"])
        if r["hot"]:
            h("🔥 hot waivers (trending & available):")
            for p, cnt, gain, need in r["hot"][:5]:
                if need and cnt >= SPIKE:
                    flag = " 🚨 GRAB (need + stampede)"
                elif need:
                    flag = " ⭐ fills need"
                else:
                    flag = f" +{gain:.0f} lineup" if gain >= 2 else ""
                h(f"  {p['pos']} {p['name']} — {cnt:,} adds/24h{flag}")
        else:
            h("🔥 hot waivers: none available to you")
        h("📋 best free agent by pos: " + " · ".join(
            f"{pos} {r['best'][pos]['name'].split()[-1]}" for pos in ("QB", "RB", "WR", "TE") if r["best"][pos]))
        if r["deals"]:
            h("🔄 top trade:")
            d = r["deals"][0]
            h(f"  SEND {trades._names(d['snd'])} → GET {trades._names(d['get'])} @ {d['team']} "
              f"(+{d['dmine']:.0f} you / {d['dtheirs']:+.0f} them)")
    out = "\n".join(lines)
    print(out)
    has_alerts = any(_has_alerts(r.get("alerts")) for r in league_results if r)
    out_in_lineup = any(r["alerts"]["out_in"] for r in league_results if r and r.get("alerts"))
    if "--post" in sys.argv:
        if LINEUP_ONLY and not has_alerts:
            print("(lineup-only: every lineup is set correctly — not posting)")
        elif "--spike-only" in sys.argv and not any(
                need and cnt >= SPIKE for r in league_results if r for _p, cnt, _g, need in r["hot"]):
            print("(spike-only: nothing urgent — not posting)")
        else:
            # header line is lines[0]; use it as the Sage title, post the rest as the body
            post_sage(f"🏈 Fantasy monitor — {hdr}", "\n".join(lines[1:]),
                      level="warn" if out_in_lineup else "info")
    return out


if __name__ == "__main__":
    main()
