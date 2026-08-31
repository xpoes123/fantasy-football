"""VONA Monte Carlo draft engine.

Given the current board state (who's drafted, my roster, my slot), evaluate each
candidate pick by simulating how the board flows to my future picks — opponents draft
via an ADP-pressure model — then scoring my best achievable starting lineup. Recommend
the pick that maximizes expected end-of-horizon roster value. This is what makes it pick
scarcity (elite RB) over raw EV (QB): the sim sees a comparable QB survive but the RB won't.
"""
import math, random
import config

SLOT_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]  # dedicated starter slots


def snake_picks(slot, rounds=config.ROUNDS, teams=config.NUM_TEAMS):
    """Overall pick numbers (1-indexed) belonging to `slot` in a snake draft."""
    out = []
    for r in range(1, rounds + 1):
        out.append((r - 1) * teams + (slot if r % 2 else teams + 1 - slot))
    return out


def start_value(roster):
    """Optimal starting-lineup projected total for a roster (+ small depth bonus).
    Greedy fill is optimal here: dedicated slots take each position's best, FLEX takes
    the best leftover among RB/WR/TE."""
    pools = {pos: sorted((p["adj_proj"] for p in roster if p["pos"] == pos), reverse=True)
             for pos in SLOT_ORDER}
    idx = {pos: 0 for pos in SLOT_ORDER}
    total = 0.0
    for pos in SLOT_ORDER:
        for _ in range(config.SLOTS[pos]):
            if idx[pos] < len(pools[pos]):
                total += pools[pos][idx[pos]]
                idx[pos] += 1
    # FLEX from leftover RB/WR/TE
    leftovers = []
    for pos in config.FLEX_POS:
        leftovers += pools[pos][idx[pos]:]
    leftovers.sort(reverse=True)
    total += sum(leftovers[: config.SLOTS["FLEX"]])
    # depth: bench insurance, lightly weighted
    bench = sum(leftovers[config.SLOTS["FLEX"]:])
    return total + 0.10 * bench


def _marginal(roster, p):
    return start_value(roster + [p]) - start_value(roster)


def _my_best(avail_by_vor, roster):
    """My greedy pick in a rollout: best marginal starting-lineup gain, VOR as tiebreak."""
    best, best_gain = None, -1e9
    for p in avail_by_vor[:40]:
        g = _marginal(roster, p)
        if g > best_gain or (g == best_gain and best and p["vor"] > best["vor"]):
            best, best_gain = p, g
    return best or (avail_by_vor[0] if avail_by_vor else None)


def _opp_pick(avail_by_adp, pick_no, rng, spread=12.0):
    """Opponent pick via ADP pressure: players at/under the current pick are 'overdue'
    (max weight); weight decays as ADP runs ahead of the current pick."""
    cands = avail_by_adp[:45]
    if not cands:
        return None
    weights = [math.exp(-max(0.0, p["adp"] - pick_no) / spread) for p in cands]
    r = rng.random() * sum(weights)
    for p, w in zip(cands, weights):
        r -= w
        if r <= 0:
            return p
    return cands[-1]


def _rollout(candidate, my_roster, universe, drafted, my_future, cur_pick, rng):
    """One simulated future. Returns end-horizon roster value if I take `candidate` now."""
    taken = set(drafted)
    taken.add(candidate["pid"])
    roster = my_roster + [candidate]
    mine = set(my_future)
    avail = [p for p in universe if p["pid"] not in taken]
    horizon = my_future[-1] if my_future else cur_pick
    for pick_no in range(cur_pick + 1, horizon + 1):
        if not avail:
            break
        if pick_no in mine:
            avail.sort(key=lambda x: x["vor"], reverse=True)
            p = _my_best(avail, roster)
            if p:
                roster.append(p)
        else:
            avail.sort(key=lambda x: x["adp"])
            p = _opp_pick(avail, pick_no, rng)
        if p:
            avail.remove(p)
    return start_value(roster)


def recommend(players, drafted, my_roster, my_slot, cur_pick,
              k=12, rollouts=40, lookahead=5, universe_size=220, seed=None):
    """Rank candidate picks by expected end-horizon roster value.

    players: full board (from data.build_players). drafted: set of pids already gone.
    my_roster: list of my player dicts. my_slot: 1..teams. cur_pick: next overall pick #.
    Returns list of dicts: {player, exp_value, delta} sorted best-first."""
    rng = random.Random(seed)
    universe = [p for p in players if p["pid"] not in drafted][:universe_size]

    my_all = snake_picks(my_slot)
    my_future = [pk for pk in my_all if pk > cur_pick][:lookahead]

    # Don't recommend K/DEF until the endgame — nobody drafts them early. Allow only when
    # my remaining picks are about to run out (last pick or two).
    my_remaining = len([pk for pk in my_all if pk >= cur_pick])
    have_pos = {p["pos"] for p in my_roster}
    allow_kdef = my_remaining <= (("K" not in have_pos) + ("DEF" not in have_pos) + 1)

    # candidate set: top-k available by VOR, plus best available at each unfilled starter pos
    avail = [p for p in players if p["pid"] not in drafted
             and (allow_kdef or p["pos"] not in ("K", "DEF"))]
    avail_by_vor = sorted(avail, key=lambda x: x["vor"], reverse=True)
    cands = list(avail_by_vor[:k])
    have = {p["pid"] for p in cands}
    for pos in SLOT_ORDER:
        for p in avail_by_vor:
            if p["pos"] == pos and p["pid"] not in have:
                cands.append(p); have.add(p["pid"]); break

    base = start_value(my_roster)
    results = []
    for c in cands:
        vals = [_rollout(c, my_roster, universe, drafted, my_future, cur_pick,
                         random.Random((seed or 0) + i)) for i in range(rollouts)]
        exp = sum(vals) / len(vals)
        results.append({"player": c, "exp_value": exp, "delta": exp - base})
    results.sort(key=lambda x: x["exp_value"], reverse=True)
    return results


if __name__ == "__main__":
    # sanity self-check: from an empty roster at pick 1, the engine must recommend a
    # top-tier RB/WR (elite scarcity), NOT a QB — the core behavior we're buying.
    import data
    players = data.build_players()
    recs = recommend(players, drafted=set(), my_roster=[], my_slot=1, cur_pick=1,
                     rollouts=25, seed=1)
    top = recs[0]["player"]
    print("Pick 1 recommendation:", top["name"], top["pos"], "| exp roster:",
          round(recs[0]["exp_value"], 1))
    for r in recs[:6]:
        p = r["player"]
        print(f"  {p['pos']:3} {p['name'][:22]:22} vor {p['vor']:6}  E[roster] {r['exp_value']:7.1f}")
    assert top["pos"] in ("RB", "WR"), f"expected elite RB/WR at 1.01, got {top['pos']}"
    print("OK: scarcity-aware (RB/WR over QB at 1.01)")
