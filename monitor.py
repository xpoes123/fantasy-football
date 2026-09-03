"""Constant monitor for all of David's drafted leagues: surfaces hot WAIVER adds and the best
win-win TRADES, as a digest you can run on a schedule.

Waivers use two signals: (1) Sleeper's leaguewide TRENDING adds (real-time role-change/breakout
hype) intersected with who's actually available in YOUR league, and (2) the best available body at
each position (for bye/injury/streaming). Trades reuse the trade engine.

Run: python3 monitor.py            (all drafted 2026 leagues for config.MY_USER_ID)
     python3 monitor.py --md       (markdown, for posting to Discord / the share site)
"""
import json, os, sys, urllib.request
import data, config, trades

MD = "--md" in sys.argv or "--post" in sys.argv
SPIKE = 40000   # trending-add count that counts as a "stampede" worth an urgent ping


def post_discord(text):
    """Push the digest to a Discord channel via webhook (set DISCORD_WEBHOOK in .env). Chunks to
    stay under Discord's 2000-char limit."""
    hook = os.environ.get("DISCORD_WEBHOOK")
    if not hook:
        print("(no DISCORD_WEBHOOK set — printed only)"); return
    chunk = ""
    for line in text.split("\n") + ["\x00"]:
        if line == "\x00" or len(chunk) + len(line) + 1 > 1900:
            if chunk.strip():
                req = urllib.request.Request(hook, data=json.dumps({"content": chunk}).encode(),
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=15)
            chunk = ""
        if line != "\x00":
            chunk += line + "\n"


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


def scan_league(league_id, teams_n, trend, board, idx):
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
    # trades
    _m, _b, deals = trades.find_trades(top=3)
    return {"needs": needs, "base": base, "hot": hot, "best": best, "deals": deals}


def main():
    board = data.build_players()
    idx = {p["pid"]: p for p in board}
    trend = trending_add()
    lines = []
    h = (lambda s: lines.append(s))
    h(f"# 🏈 Fantasy monitor — {config.SEASON}" if MD else "=== FANTASY MONITOR ===")
    for lid, name, tn in drafted_leagues():
        r = scan_league(lid, tn, trend, board, idx)
        if not r:
            continue
        h(f"\n## {name} ({tn}-team)" if MD else f"\n--- {name} ({tn}-team) ---")
        h(f"needs: {'/'.join(r['needs']) or 'none'}")
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
    if "--post" in sys.argv:
        post_discord(out)
    return out


if __name__ == "__main__":
    main()
