"""Self-play mock draft: your team follows the tool's live recommendation every pick; the
other 11 teams draft via the opponent model (ADP + roster needs + runs). Validates the whole
recommendation stack end-to-end and shows the roster the tool builds. Run: python3 mock.py [slot]"""
import random, sys
import data, engine, config


def _my_pick(players, drafted, my_roster, my_slot, cur_pick, opp_rosters, recent, seed):
    """Reproduce the LIVE recommendation: recommend() candidates, then bench-mode upside /
    saturation once starters are full, else win-value order. Returns the chosen player dict."""
    opp_pos = {s: [p["pos"] for p in r] for s, r in opp_rosters.items()}
    recs = engine.recommend(players, drafted, my_roster, my_slot, cur_pick, rollouts=20,
                            seed=seed, opp_rosters=opp_pos, recent0=recent)
    if not recs:
        return None
    cands = [r["player"] for r in recs]
    rnd = (cur_pick - 1) // config.NUM_TEAMS + 1
    import live
    need = live.needs(my_roster, len([pk for pk in engine.snake_picks(my_slot) if pk >= cur_pick]))
    starter_needs = [n for n in need if n not in ("K", "DEF")]
    have_qb = any(p["pos"] == "QB" for p in my_roster)
    counts = {}
    for p in my_roster:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1
    if rnd >= config.UPSIDE_ROUND or not starter_needs:
        cands.sort(key=lambda p: engine.upside_score(p, have_qb, counts), reverse=True)
    return cands[0]


def run_mock(my_slot=11, seed=1):
    players = data.build_players()
    drafted, recent = set(), []
    rosters = {s: [] for s in range(1, config.NUM_TEAMS + 1)}
    rng = random.Random(seed)
    log = []
    for pick_no in range(1, config.NUM_TEAMS * config.ROUNDS + 1):
        slot = engine._slot_on_clock(pick_no)
        if slot == my_slot:
            pick = _my_pick(players, drafted, rosters[my_slot], my_slot, pick_no, rosters,
                            recent, seed)
        else:
            avail = sorted((p for p in players if p["pid"] not in drafted), key=lambda x: x["adp"])
            pick = engine._opp_pick(avail, pick_no, rng, [p["pos"] for p in rosters[slot]], recent)
        if pick:
            drafted.add(pick["pid"]); rosters[slot].append(pick)
            recent.append(pick["pos"]); recent = recent[-config.OPP_RUN_K:]
            log.append((pick_no, slot, pick))
    return rosters[my_slot], log


if __name__ == "__main__":
    slot = int(sys.argv[1]) if len(sys.argv) > 1 else config.DEFAULT_SLOT
    roster, log = run_mock(slot)
    print(f"\n=== MOCK DRAFT — your team (slot {slot}, {config.NUM_TEAMS}-team) ===\n")
    for i, p in enumerate(roster):
        pk = engine.snake_picks(slot)[i]
        rnd, inr = (pk - 1) // config.NUM_TEAMS + 1, (pk - 1) % config.NUM_TEAMS + 1
        print(f"  {rnd:2}.{inr:02d} (#{pk:3})  {p['pos']:3} {p['name'][:22]:22} "
              f"adp {p['adp']:5.0f}  vor {p['vor']:5.0f}  {p['team'] or ''}")
    from collections import Counter
    print("\n  roster:", dict(Counter(p["pos"] for p in roster)))
