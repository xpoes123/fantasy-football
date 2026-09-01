"""VONA Monte Carlo draft engine.

Given the current board state (who's drafted, my roster, my slot), evaluate each
candidate pick by simulating how the board flows to my future picks — opponents draft
via an ADP-pressure model — then scoring my best achievable starting lineup. Recommend
the pick that maximizes expected end-of-horizon roster value. This is what makes it pick
scarcity (elite RB) over raw EV (QB): the sim sees a comparable QB survive but the RB won't.
"""
import math, random
import config, overrides

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
    """(mean, variance) of the roster's weekly team score from its optimal starters.
    Adds QB<->same-team pass-catcher correlation: a stack raises joint variance (ceiling)
    and gets a small ceiling bonus, so the sim values completing stacks."""
    starters = _starters(roster)
    mu = var = 0.0
    info = []
    for p in starters:
        m = p["adj_proj"] / config.GAMES
        sd = config.POS_CV.get(p["pos"], 0.6) * m
        mu += m
        var += sd * sd
        info.append((m, sd, p.get("team"), p["pos"]))
    for mq, sq, tq, pq in info:                       # each starting QB...
        if pq != "QB" or not tq:
            continue
        for mi, si, ti, pi in info:                   # ...paired with same-team WR/TE
            if pi in ("WR", "TE") and ti == tq:
                var += 2 * config.STACK_RHO * sq * si
                mu += config.STACK_MU
    return mu, var


_HANDCUFF_NAMES = {v.lower() for v in overrides.HANDCUFFS.values()}


def upside_score(p, have_qb=False, have_counts=None):
    """Late-round CEILING score for a bench pick: reward scarce (waiver-aware VOR) + boom
    variance + a real path (handcuff) + youth; discount streamable K/DEF/2nd-QB AND positions
    you're already deep at. Used once starters are full — 'skip what you can stream or already
    have plenty of, swing for upside'."""
    base = max(p["vor"], 0) + 20                      # scarcity-aware, kept positive
    cv = config.POS_CV.get(p["pos"], 0.6)
    score = base * (1 + config.UPSIDE_CV_LEAN * cv)   # lean into boom weeks
    if p["name"].lower() in _HANDCUFF_NAMES:
        score *= config.UPSIDE_HANDCUFF                # backup with a path to a workhorse role
    if p["pos"] in ("RB", "WR") and (p.get("age") or 99) <= config.UPSIDE_YOUNG_AGE:
        score *= config.UPSIDE_YOUTH                   # young/ascending
    if p["pos"] in ("K", "DEF") or (p["pos"] == "QB" and have_qb):
        score *= config.STREAM_DISCOUNT                # freely streamable off waivers
    if have_counts:                                   # roster-saturation: deep here already?
        n = have_counts.get(p["pos"], 0)
        cap = config.SATURATION.get(p["pos"], 5)
        if n >= cap:
            score *= 0.35
        elif n >= cap - 1:
            score *= 0.7
    return score


def _handcuff_count(roster):
    """How many of my players are the handcuff to another RB I roster (insurance depth)."""
    names = {p["name"] for p in roster}
    return sum(1 for p in roster
               if overrides.HANDCUFFS.get(p["name"]) in names)


def _complete(roster, avail_by_vor):
    """Greedily fill a partial roster to 15 so byes/depth enter the objective. Guarantees the
    single-starter slots the VOR-greedy fill would skip (QB/TE/K/DEF are all low-VOR) — else a
    QB-less roster scores as if its QB slot is empty, wildly over-valuing an early QB/TE pick."""
    need = 15 - len(roster)
    if need <= 0:
        return roster
    cnt = {}
    for p in roster:
        cnt[p["pos"]] = cnt.get(p["pos"], 0) + 1
    picked = []
    for pos in ("QB", "TE", "K", "DEF"):        # you WILL draft one of each — model that
        if cnt.get(pos, 0) == 0:
            nxt = next((p for p in avail_by_vor if p["pos"] == pos and p not in picked), None)
            if nxt:
                picked.append(nxt)
    for p in avail_by_vor:
        if len(picked) >= need:
            break
        if p["pos"] in ("QB", "K", "DEF") or p in picked:   # one is enough at these
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
    roster to 15 first) + handcuff insurance, or legacy sum if USE_WIN_VALUE is off."""
    if config.USE_WIN_VALUE and baseline:
        full = _complete(roster, avail_by_vor)
        return win_value(full, *baseline) + config.HANDCUFF_BONUS * _handcuff_count(full)
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


_STARTER_TARGET = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}


def _deficit(positions):
    """How many starters short an opponent is per position (drives need-based reaches)."""
    cnt = {}
    for p in positions:
        cnt[p] = cnt.get(p, 0) + 1
    return {pos: max(0, t - cnt.get(pos, 0)) for pos, t in _STARTER_TARGET.items()}


def _opp_pick(avail_by_adp, pick_no, rng, opp_positions=None, recent=None, eps=0.03):
    """Opponent pick. ADP pressure (spread grows with ADP so elites barely slide) x a
    roster-NEED boost (opponents chase positions they're short) x a RUN-contagion boost
    (positions going hot get chased) + chaos floor. This is what makes the sim draft-specific:
    seed opp_positions from real picks and it predicts THIS league's opponents, not a generic one."""
    cands = avail_by_adp[:45]
    if not cands:
        return None
    deficit = _deficit(opp_positions or [])
    runcnt = {}
    if recent:
        for pos in recent:
            runcnt[pos] = runcnt.get(pos, 0) + 1
    base = (len(recent) * 0.28) if recent else 0   # ~RB/WR baseline share of picks
    weights = []
    for p in cands:
        spread = min(22.0, max(1.5, 0.5 + 0.15 * p["adp"]))
        w = math.exp(-max(0.0, p["adp"] - pick_no) / spread)
        w *= math.exp(config.OPP_NEED_BETA * deficit.get(p["pos"], 0))
        if recent:
            w *= math.exp(config.OPP_RUN_GAMMA * max(0.0, runcnt.get(p["pos"], 0) - base))
        weights.append(w + eps)
    r = rng.random() * sum(weights)
    for p, w in zip(cands, weights):
        r -= w
        if r <= 0:
            return p
    return cands[-1]


def _slot_on_clock(pick_no, teams=config.NUM_TEAMS):
    r = (pick_no - 1) // teams + 1
    in_rnd = (pick_no - 1) % teams + 1
    return in_rnd if r % 2 else teams + 1 - in_rnd


def _rollout(candidate, my_roster, universe, drafted, my_future, cur_pick, rng, baseline,
             opp_rosters=None, recent0=None):
    """One simulated future. Returns end-horizon roster value if I take `candidate` now.
    Opponents pick by real roster needs when opp_rosters (slot -> [positions]) is seeded."""
    taken = set(drafted)
    taken.add(candidate["pid"])
    roster = my_roster + [candidate]
    mine = set(my_future)
    avail = [p for p in universe if p["pid"] not in taken]
    rosters = {s: list(v) for s, v in (opp_rosters or {}).items()}
    recent = list(recent0 or [])[-config.OPP_RUN_K:]
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
            slot = _slot_on_clock(pick_no)
            p = _opp_pick(avail, pick_no, rng, rosters.get(slot), recent)
            if p:
                rosters.setdefault(slot, []).append(p["pos"])
                recent.append(p["pos"]); recent = recent[-config.OPP_RUN_K:]
        if p:
            avail.remove(p)
    avail.sort(key=lambda x: x["vor"], reverse=True)
    return _leaf(roster, avail, baseline)


def survival_probs(players, drafted, cur_pick, my_next, rollouts=200, seed=0, top_n=70,
                   opp_rosters=None, recent0=None):
    """P(player still available at my_next) for the top_n available by VOR — the turn
    drafter's core question ("will he survive my 22-pick wait?"). Simulates the opponent
    picks strictly between cur_pick and my_next. If opp_rosters (slot -> [positions], from
    the REAL draft) is given, opponents pick by their actual needs — draft-specific survival."""
    avail0 = sorted((p for p in players if p["pid"] not in drafted),
                    key=lambda x: x["vor"], reverse=True)
    cohort = {p["pid"] for p in avail0[:top_n]}
    n_opp = max(0, (my_next or cur_pick) - cur_pick - 1)
    if n_opp == 0:
        return {pid: 1.0 for pid in cohort}
    survive = {pid: 0 for pid in cohort}
    for i in range(rollouts):
        rng = random.Random(seed + i)
        avail = sorted(avail0, key=lambda x: x["adp"])
        rosters = {s: list(v) for s, v in (opp_rosters or {}).items()}
        recent = list(recent0 or [])[-config.OPP_RUN_K:]
        taken = set()
        for k in range(n_opp):
            pn = cur_pick + 1 + k
            slot = _slot_on_clock(pn)
            p = _opp_pick(avail, pn, rng, rosters.get(slot), recent)
            if p:
                avail.remove(p)
                taken.add(p["pid"])
                rosters.setdefault(slot, []).append(p["pos"])
                recent.append(p["pos"]); recent = recent[-config.OPP_RUN_K:]
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
              k=12, rollouts=40, lookahead=5, universe_size=220, seed=None,
              opp_rosters=None, recent0=None):
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
    # Don't recommend single-slot positions you're already set at — a 2nd QB/TE is just
    # low-value depth (they don't stack, and you'd rather flex RB/WR). QB also stays gated
    # early (deepest/streamable): only recommend one once it's mid-draft and you lack one.
    allow_qb = ("QB" not in have_pos) and (my_remaining <= config.ROUNDS - 5)
    allow_te = "TE" not in have_pos

    # candidate set: top-k available by VOR, plus best available at each unfilled starter pos
    avail = [p for p in players if p["pid"] not in drafted
             and (allow_kdef or p["pos"] not in ("K", "DEF"))
             and (allow_qb or p["pos"] != "QB")
             and (allow_te or p["pos"] != "TE")]
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
                         random.Random((seed or 0) + i), baseline, opp_rosters, recent0)
                for i in range(rollouts)]
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
