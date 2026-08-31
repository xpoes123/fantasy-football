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


# ---------------------------------------------------------------------------
# Variance-aware season objective. Instead of scoring a roster by the deterministic
# sum of its starters' season points, model each starter's WEEKLY score as a normal
# (mean = season/17, sd = position CV × mean) and compute expected H2H wins vs a
# league-average team. This makes boom/bust and consistency actually matter, and lets
# a risk knob chase floor or ceiling — a real (if analytic) season simulation.
# ---------------------------------------------------------------------------

def _starters(roster):
    """The players filling the 10 starting slots, chosen by projection (same rule as
    start_value): dedicated slots take each position's best, FLEX the best leftover."""
    pools = {pos: sorted((p for p in roster if p["pos"] == pos),
                         key=lambda x: -x["adj_proj"]) for pos in SLOT_ORDER}
    idx = {pos: 0 for pos in SLOT_ORDER}
    st = []
    for pos in SLOT_ORDER:
        for _ in range(config.SLOTS[pos]):
            if idx[pos] < len(pools[pos]):
                st.append(pools[pos][idx[pos]]); idx[pos] += 1
    leftovers = []
    for pos in config.FLEX_POS:
        leftovers += pools[pos][idx[pos]:]
    leftovers.sort(key=lambda x: -x["adj_proj"])
    return st + leftovers[: config.SLOTS["FLEX"]]


def weekly_moments(roster):
    """(mean, variance) of the roster's weekly team score from its optimal starters."""
    mu = var = 0.0
    for p in _starters(roster):
        m = p["adj_proj"] / config.GAMES
        cv = config.POS_CV.get(p["pos"], 0.6)
        mu += m
        var += (cv * m) ** 2
    return mu, var


def _complete(roster, avail_by_vor):
    """Greedily fill a partial roster to 15 so byes/depth/K/DEF enter the objective.
    Ensures one K and one DEF (their starter slots would otherwise score 0)."""
    need = 15 - len(roster)
    if need <= 0:
        return roster
    have = {p["pos"] for p in roster}
    picked = []
    for pos in ("K", "DEF"):
        if pos not in have:
            nxt = next((p for p in avail_by_vor if p["pos"] == pos), None)
            if nxt:
                picked.append(nxt)
    for p in avail_by_vor:
        if len(picked) >= need:
            break
        if p["pos"] in ("K", "DEF") or p in picked:
            continue
        picked.append(p)
    return roster + picked[:need]


def win_value(roster, mu_L, var_L):
    """Expected H2H regular-season wins vs a league-average team (μ_L, var_L).
    P(win a week) = Φ((μ_T − μ_L)/√(var_T+var_L)); ×REG_WEEKS. RISK_LAMBDA shifts μ_T
    by λ·σ_T to chase ceiling (λ>0) or floor (λ<0)."""
    mu, var = weekly_moments(roster)
    mu_eff = mu + config.RISK_LAMBDA * math.sqrt(var) if var > 0 else mu
    denom = math.sqrt(2.0 * (var + var_L)) or 1.0
    pwin = 0.5 * math.erfc(-(mu_eff - mu_L) / denom)
    return config.REG_WEEKS * pwin


def league_baseline(players, teams=config.NUM_TEAMS, rounds=config.ROUNDS):
    """(μ_L, var_L): the average opponent, from snake-drafting the top ADP players into
    12 rosters and averaging their weekly moments."""
    order = sorted(players, key=lambda x: x["adp"])[: teams * rounds]
    rosters = [[] for _ in range(teams)]
    i = 0
    for r in range(rounds):
        seq = range(teams) if r % 2 == 0 else range(teams - 1, -1, -1)
        for t in seq:
            if i < len(order):
                rosters[t].append(order[i]); i += 1
    ms, vs = zip(*(weekly_moments(ro) for ro in rosters))
    return sum(ms) / len(ms), sum(vs) / len(vs)


def _leaf(roster, avail_by_vor, baseline):
    """Score a roster at a rollout leaf: variance-aware expected wins (completing the
    roster to 15 first), or the legacy sum-of-projections if USE_WIN_VALUE is off."""
    if config.USE_WIN_VALUE and baseline:
        return win_value(_complete(roster, avail_by_vor), *baseline)
    return start_value(roster)


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


def _opp_pick(avail_by_adp, pick_no, rng, eps=0.03):
    """Opponent pick via ADP pressure. spread grows with ADP (elites barely slide, mid/late
    players swing 1-2 rounds — matches real ADP dispersion), plus a small chaos floor eps so
    rare falls still surface. Players at/under the current pick are 'overdue' (max weight)."""
    cands = avail_by_adp[:45]
    if not cands:
        return None
    weights = []
    for p in cands:
        spread = min(22.0, max(1.5, 0.5 + 0.15 * p["adp"]))
        weights.append(math.exp(-max(0.0, p["adp"] - pick_no) / spread) + eps)
    r = rng.random() * sum(weights)
    for p, w in zip(cands, weights):
        r -= w
        if r <= 0:
            return p
    return cands[-1]


def _rollout(candidate, my_roster, universe, drafted, my_future, cur_pick, rng, baseline):
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
    avail.sort(key=lambda x: x["vor"], reverse=True)
    return _leaf(roster, avail, baseline)


def survival_probs(players, drafted, cur_pick, my_next, rollouts=200, seed=0, top_n=70):
    """P(player still available at my_next) for the top_n available by VOR — the turn
    drafter's core question ("will he survive my 22-pick wait?"). Simulates only the
    opponent picks strictly between cur_pick and my_next via the ADP-pressure model."""
    avail0 = sorted((p for p in players if p["pid"] not in drafted),
                    key=lambda x: x["vor"], reverse=True)
    cohort = {p["pid"] for p in avail0[:top_n]}
    n_opp = max(0, (my_next or cur_pick) - cur_pick - 1)
    if n_opp == 0:
        return {pid: 1.0 for pid in cohort}
    survive = {pid: 0 for pid in cohort}
    for i in range(rollouts):
        rng = random.Random(seed + i)
        avail = sorted(avail0, key=lambda x: x["adp"])  # adp order; removes keep it sorted
        taken = set()
        for k in range(n_opp):
            p = _opp_pick(avail, cur_pick + 1 + k, rng)
            if p:
                avail.remove(p)
                taken.add(p["pid"])
        for pid in cohort:
            if pid not in taken:
                survive[pid] += 1
    return {pid: survive[pid] / rollouts for pid in cohort}


def tiers(players, drafted, pos, gap=18.0):
    """Split the available players at a position into tiers, breaking where the adj_proj
    gap to the next player exceeds `gap`. Returns list of tiers (each a list of players),
    best first — so tier[0] is the elite bucket and its size = 'how many elites left'."""
    pool = sorted((p for p in players if p["pos"] == pos and p["pid"] not in drafted),
                  key=lambda x: -x["adj_proj"])
    out, cur = [], []
    for i, p in enumerate(pool):
        cur.append(p)
        if i + 1 < len(pool) and p["adj_proj"] - pool[i + 1]["adj_proj"] > gap:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


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

    baseline = league_baseline(players) if config.USE_WIN_VALUE else None
    base = _leaf(my_roster, avail_by_vor, baseline)
    results = []
    for c in cands:
        vals = [_rollout(c, my_roster, universe, drafted, my_future, cur_pick,
                         random.Random((seed or 0) + i), baseline) for i in range(rollouts)]
        exp = sum(vals) / len(vals)
        results.append({"player": c, "exp_value": exp, "delta": exp - base})
    # Rank by expected wins, but break near-ties (within ~0.1 win, i.e. rollout noise) by
    # VOR — when two picks are equal-equity, take the better value/scarcity play.
    results.sort(key=lambda x: (round(x["exp_value"], 1), x["player"]["vor"]), reverse=True)
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
        print(f"  {p['pos']:3} {p['name'][:22]:22} vor {p['vor']:6}  E[wins] {r['exp_value']:5.1f}")
    assert top["pos"] in ("RB", "WR"), f"expected elite RB/WR at 1.01, got {top['pos']}"
    print("OK: scarcity-aware (RB/WR over QB at 1.01)")
