"""Bridge for the subagent mock: given the current draft state, print the tool's pick.
Loads the dumped board (not a live rebuild — fast) and runs the real engine.recommend +
late-round upside sort, exactly like the live app. Used by the 'mock vs subagents' harness.

Usage: python3 toolpick.py <board.json> <slot> <pick_no> "<drafted names | sep>" "<my roster names | sep>"
Prints one line: "<pos>\t<name>"
"""
import json, sys
import engine, config, live

board_path, slot, pick_no = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
drafted_names = [n.strip() for n in (sys.argv[4] if len(sys.argv) > 4 else "").split("|") if n.strip()]
roster_names = [n.strip() for n in (sys.argv[5] if len(sys.argv) > 5 else "").split("|") if n.strip()]

board = json.load(open(board_path))
by_name = {p["name"]: p for p in board}
drafted = {by_name[n]["pid"] for n in drafted_names if n in by_name}
my_roster = [by_name[n] for n in roster_names if n in by_name]

recs = engine.recommend(board, drafted, my_roster, slot, pick_no, rollouts=20, seed=7)
if not recs:
    print("QB\tnone"); sys.exit()
cands = [r["player"] for r in recs]
rnd = (pick_no - 1) // config.NUM_TEAMS + 1
need = live.needs(my_roster, len([pk for pk in engine.snake_picks(slot) if pk >= pick_no]))
have_qb = any(p["pos"] == "QB" for p in my_roster)
counts = {}
for p in my_roster:
    counts[p["pos"]] = counts.get(p["pos"], 0) + 1
if rnd >= config.UPSIDE_ROUND or not [n for n in need if n not in ("K", "DEF")]:
    cands.sort(key=lambda p: engine.upside_score(p, have_qb, counts), reverse=True)
pick = cands[0]
print(json.dumps({"pos": pick["pos"], "name": pick["name"]}))
