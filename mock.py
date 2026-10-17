"""Self-play mock draft: your team follows the tool's live recommendation every pick; the
other 11 teams draft via the opponent model (ADP + roster needs + runs). Validates the whole
recommendation stack end-to-end and shows the roster the tool builds. Run: python3 mock.py [slot]"""
import random, sys
import data, engine, config


def _my_pick(players, drafted, my_roster, my_slot, cur_pick, opp_rosters, recent, seed):
    """Reproduce the LIVE recommendation: recommend() candidates, then bench-mode upside /
    saturation once starters are full, else win-value order. Returns (chosen, detail) where
    detail = (mode, ranked[(player, exp_value, delta)]) for per-turn evaluation."""
    opp_pos = {s: [p["pos"] for p in r] for s, r in opp_rosters.items()}
    recs = engine.recommend(players, drafted, my_roster, my_slot, cur_pick, rollouts=20,
                            seed=seed, opp_rosters=opp_pos, recent0=recent)
    if not recs:
        return None, None
    rnd = (cur_pick - 1) // config.NUM_TEAMS + 1
    import live
    need = live.needs(my_roster, len([pk for pk in engine.snake_picks(my_slot) if pk >= cur_pick]))
    starter_needs = [n for n in need if n not in ("K", "DEF")]
    have_qb = any(p["pos"] == "QB" for p in my_roster)
    counts = {}
    for p in my_roster:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1
    ev = {r["player"]["pid"]: (r["exp_value"], r["delta"]) for r in recs}
    if rnd >= config.UPSIDE_ROUND or not starter_needs:
        ranked = sorted((r["player"] for r in recs),
                        key=lambda p: engine.upside_score(p, have_qb, counts), reverse=True)
        mode = "upside"
    else:
        ranked = [r["player"] for r in recs]
        mode = "finish-EV"
    detail = (mode, [(p, ev[p["pid"]][0], ev[p["pid"]][1]) for p in ranked])
    return ranked[0], detail


def run_mock(my_slot=11, seed=1):
    players = data.build_players()
    drafted, recent = set(), []
    rosters = {s: [] for s in range(1, config.NUM_TEAMS + 1)}
    rng = random.Random(seed)
    log, evals = [], {}
    for pick_no in range(1, config.NUM_TEAMS * config.ROUNDS + 1):
        slot = engine._slot_on_clock(pick_no)
        if slot == my_slot:
            pick, detail = _my_pick(players, drafted, rosters[my_slot], my_slot, pick_no, rosters,
                                    recent, seed)
            evals[pick_no] = detail
        else:
            avail = sorted((p for p in players if p["pid"] not in drafted), key=lambda x: x["adp"])
            pick = engine._opp_pick(avail, pick_no, rng, [p["pos"] for p in rosters[slot]], recent)
        if pick:
            drafted.add(pick["pid"]); rosters[slot].append(pick)
            recent.append(pick["pos"]); recent = recent[-config.OPP_RUN_K:]
            log.append((pick_no, slot, pick))
    return rosters[my_slot], log, evals


def _grade(chosen, pick_no):
    """One-line read on the pick: value vs ADP (reach/steal) + why."""
    reach = pick_no - chosen["adp"]                    # >0 = took him later than ADP (value)
    if chosen["adp"] >= 250:
        tag = "deep flyer"
    elif reach >= 12:
        tag = f"VALUE (+{reach:.0f} vs ADP)"
    elif reach <= -12:
        tag = f"reach ({reach:.0f} vs ADP)"
    else:
        tag = "at ADP"
    return tag


if __name__ == "__main__":
    slot = int(sys.argv[1]) if len(sys.argv) > 1 else config.DEFAULT_SLOT
    roster, log, evals = run_mock(slot)
    print(f"\n=== MOCK DRAFT (slot {slot}, {config.NUM_TEAMS}-team) — per-turn evaluation ===\n")
    my_counts = {}
    for i, chosen in enumerate(roster):
        pk = engine.snake_picks(slot)[i]
        rnd, inr = (pk - 1) // config.NUM_TEAMS + 1, (pk - 1) % config.NUM_TEAMS + 1
        mode, ranked = evals.get(pk) or ("?", [])
        my_counts[chosen["pos"]] = my_counts.get(chosen["pos"], 0) + 1
        have = "/".join(f"{v}{k}" for k, v in sorted(my_counts.items()))
        print(f"  {rnd:2}.{inr:02d} (#{pk:3}) [{mode:9}]  -> {chosen['pos']:3} {chosen['name'][:20]:20} "
              f"vor {chosen['vor']:5.0f}  adp {chosen['adp']:5.0f}  {_grade(chosen, pk)}")
        for p, exp, delta in ranked[:4]:
            mark = "*" if p["pid"] == chosen["pid"] else " "
            print(f"           {mark} {p['pos']:3} {p['name'][:20]:20} "
                  f"E[$] {exp:5.2f}  vor {p['vor']:5.0f}  adp {p['adp']:5.0f}")
        print(f"           roster after: {have}\n")
    from collections import Counter
    print("  final roster:", dict(Counter(p["pos"] for p in roster)))
