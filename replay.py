"""Replay a REAL completed Sleeper draft through the current model: at each of your actual
picks, show what the (now-improved) tool would recommend vs what you actually took.
Usage: python3 replay.py <draft_id> <my_slot>"""
import sys, json, urllib.request
import data, engine, config, live


def _api(path):
    with urllib.request.urlopen(f"https://api.sleeper.app/v1/{path}", timeout=20) as r:
        return json.load(r)


def _rec_top(players, drafted, my_roster, my_slot, cur_pick, opp_rosters, recent, n=3):
    """The tool's top-n picks for this state, with the full live ranking (win-value early,
    upside/saturation late, must-fill K/DEF)."""
    recs = engine.recommend(players, drafted, my_roster, my_slot, cur_pick, rollouts=20,
                            seed=7, opp_rosters=opp_rosters, recent0=recent)
    cands = [r["player"] for r in recs]
    rnd = (cur_pick - 1) // config.NUM_TEAMS + 1
    need = live.needs(my_roster, len([pk for pk in engine.snake_picks(my_slot) if pk >= cur_pick]))
    have_qb = any(p["pos"] == "QB" for p in my_roster)
    counts = {}
    for p in my_roster:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1
    if rnd >= config.UPSIDE_ROUND or not [x for x in need if x not in ("K", "DEF")]:
        cands.sort(key=lambda p: engine.upside_score(p, have_qb, counts), reverse=True)
    return cands[:n]


def replay(draft_id, my_slot):
    players = data.build_players()
    idx = {p["pid"]: p for p in players}
    picks = sorted(_api(f"draft/{draft_id}/picks"), key=lambda p: p["pick_no"])
    drafted, my_roster, recent = set(), [], []
    opp_rosters = {s: [] for s in range(1, config.NUM_TEAMS + 1)}
    rows = []
    for pk in picks:
        pno, slot, ppid = pk["pick_no"], pk.get("draft_slot"), pk["player_id"]
        if slot == my_slot:
            top = _rec_top(players, drafted, my_roster, my_slot, pno, opp_rosters, recent)
            actual = idx.get(ppid)
            rnd, inr = (pno - 1) // config.NUM_TEAMS + 1, (pno - 1) % config.NUM_TEAMS + 1
            rows.append((f"{rnd}.{inr:02d}", top, actual, pk.get("metadata", {})))
        p = idx.get(ppid)
        drafted.add(ppid)
        pos = p["pos"] if p else (pk.get("metadata") or {}).get("position")
        if pos:
            opp_rosters.setdefault(slot, []).append(pos)
            recent.append(pos); recent[:] = recent[-config.OPP_RUN_K:]
        if slot == my_slot and p:
            my_roster.append(p)
    return rows


if __name__ == "__main__":
    did = sys.argv[1] if len(sys.argv) > 1 else "1395399705847947264"  # Touchdowns
    slot = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    print(f"\n=== REPLAY draft {did}, slot {slot} — tool rec vs your actual pick ===\n")
    for rd, top, actual, meta in replay(did, slot):
        toolstr = " / ".join(f"{p['pos']} {p['name'].split()[-1]}" for p in top)
        an = actual["name"] if actual else (meta.get("first_name", "") + " " + meta.get("last_name", "")).strip()
        ap = actual["pos"] if actual else meta.get("position", "?")
        match = "  ✅ (tool's #1)" if top and actual and top[0]["pid"] == actual["pid"] else ""
        print(f"  {rd}  TOOL: {toolstr:34}  |  YOU took: {ap} {an}{match}")
