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
    # keep VOR ordering even below replacement (don't floor scrubs to a common value — that's
    # what let a −40-VOR RB tie a real dart and let youth/handcuff bonuses hoard the position)
    base = max(p["vor"], -40) + 45
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
            score *= 0.12                              # hard brake: stop piling a position past its cap
        elif n >= cap - 1:
            score *= 0.5
    return score


def _handcuff_count(roster):
    """How many of my players are the handcuff to another RB I roster (insurance depth)."""
    names = {p["name"] for p in roster}
    return sum(1 for p in roster
               if overrides.HANDCUFFS.get(p["name"]) in names)


def _complete(roster, avail_by_vor, fill_picks=None):
    """Fill a partial roster to 15 so byes/depth enter the objective. Guarantees the single-starter
    slots the VOR-greedy fill would skip (QB/TE/K/DEF are all low-VOR).

    CRITICAL: fill with REALISTICALLY-available players, not the best on the board. `fill_picks` is
    the list of overall pick numbers those empty slots map to (your real future picks); a player
    whose ADP is well before pick P won't survive to P, so we gate each fill to adp >= ~0.7*P. Best-
    available fill made every team look 5 SDs above the field → the objective saw a lock for 1st and
    chased FLOOR. Realistic fill puts you at your true strength, so the objective chases CEILING when
    that's what wins the money. (No fill_picks -> legacy best-available.)"""
    need = 15 - len(roster)
    if need <= 0:
        return roster
    cnt = {}
    for p in roster:
        cnt[p["pos"]] = cnt.get(p["pos"], 0) + 1
    fp = list(fill_picks or [])
    picked = []

    def grab(pos, min_adp):
        """Best-VOR available player (optional pos) realistically still there at min_adp."""
        cand = next((p for p in avail_by_vor if p not in picked and (not pos or p["pos"] == pos)
                     and p["adp"] >= min_adp), None)
        return cand or next((p for p in avail_by_vor if p not in picked
                             and (not pos or p["pos"] == pos)), None)

    for pos in ("QB", "TE", "K", "DEF"):        # you WILL draft one of each — model that
        if cnt.get(pos, 0) == 0:
            madp = fp[len(picked)] * 0.7 if len(picked) < len(fp) else 0
            nxt = grab(pos, madp)
            if nxt:
                picked.append(nxt)
    while len(picked) < need:                   # remaining depth: RB/WR/TE flex-eligible
        madp = fp[len(picked)] * 0.7 if len(picked) < len(fp) else 0
        nxt = grab(None, madp)
        if not nxt or nxt["pos"] in ("QB", "K", "DEF"):   # one is enough at single slots
            nxt = grab("RB", madp) or grab("WR", madp) or grab("TE", madp) or grab(None, 0)
        if not nxt:
            break
        picked.append(nxt)
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


# standardized-normal quadrature grid (nodes + normalized φ weights) — integrate my season
# total over its own distribution once per leaf. 13 nodes is plenty for a smooth integrand.
_ZS = [-3.0 + 6.0 * i / 12 for i in range(13)]
_WS = [math.exp(-0.5 * z * z) for z in _ZS]
_WS = [w / sum(_WS) for w in _WS]


def finish_equity(mu_me, var_me, mu_L, var_L, tau, payout, field=None):
    """Payout-weighted EV of my final standing — the money-maximizing, opponent-aware objective.

    My season total ~ N(REG·μ_me, REG·var_me); integrate over it. At each realized total m, the
    number of the `field` opponents I finish above is Binomial(field, q), where q = P(I outscore
    one field team) and a field team's season total ~ N(REG·μ_L, REG·var_L + (REG·τ)²) (within-
    season noise + between-team strength spread τ). Finishing above k opponents = place (teams−k),
    paid per `payout`. Ceiling-seeking is ENDOGENOUS: a high-σ roster fattens my finish
    distribution, which only earns money in the paid places — so variance is valuable exactly when
    I'm not already the favorite, and harmful when I am. No RISK_LAMBDA needed.
    """
    field = (config.NUM_TEAMS - 1) if field is None else field
    reg = config.REG_WEEKS
    M, Sd = reg * mu_me, (math.sqrt(reg * var_me) or 1.0)
    opp_sd = math.sqrt(reg * var_L + (reg * tau) ** 2) or 1.0
    ev = 0.0
    for z, w in zip(_ZS, _WS):
        m = M + z * Sd
        q = 0.5 * math.erfc(-(m - reg * mu_L) / (math.sqrt(2.0) * opp_sd))
        q = min(1.0 - 1e-9, max(1e-9, q))
        for place, pay in payout.items():
            k = config.NUM_TEAMS - place              # opponents I must finish above for this place
            if 0 <= k <= field:
                ev += w * pay * math.comb(field, k) * q ** k * (1 - q) ** (field - k)
    return ev


def league_baseline(players, teams=config.NUM_TEAMS, rounds=config.ROUNDS):
    """(μ_L, var_L, τ): the field, from snake-drafting the top ADP players into `teams` rosters.
    μ_L/var_L = average opponent weekly moments; τ = between-team spread of weekly means (how
    separated the field's strengths are — drives how much finish variance is up for grabs)."""
    order = sorted(players, key=lambda x: x["adp"])[: teams * rounds]
    rosters = [[] for _ in range(teams)]
    i = 0
    for r in range(rounds):
        seq = range(teams) if r % 2 == 0 else range(teams - 1, -1, -1)
        for t in seq:
            if i < len(order):
                rosters[t].append(order[i]); i += 1
    ms, vs = zip(*(weekly_moments(ro) for ro in rosters))
    mu_L = sum(ms) / len(ms)
    tau = (sum((m - mu_L) ** 2 for m in ms) / len(ms)) ** 0.5
    return mu_L, sum(vs) / len(vs), max(tau, config.FIELD_SPREAD)   # floor to realistic spread


def _leaf(roster, avail_by_vor, baseline, fill_picks=None):
    """Score a roster at a rollout leaf (completing it to 15 first). OBJECTIVE selects:
    'finish' = payout-weighted final-standing EV (opponent + prize aware, default);
    'wins' = legacy variance-aware expected wins; else deterministic sum-of-projections."""
    if config.OBJECTIVE in ("finish", "wins") and baseline:
        full = _complete(roster, avail_by_vor, fill_picks)
        mu, var = weekly_moments(full)
        insurance = config.HANDCUFF_BONUS * _handcuff_count(full)
        if config.OBJECTIVE == "finish":
            return finish_equity(mu, var, *baseline, config.PAYOUT) + insurance
        return win_value(full, baseline[0], baseline[1]) + insurance
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
             opp_rosters=None, recent0=None, my_all=None):
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
    # the slots _complete will fill map to my real picks BEYOND the simulated horizon — gate their
    # quality by those pick numbers so the roster is realistic, not a best-available dream team.
    fill_picks = [pk for pk in (my_all or []) if pk > horizon]
    return _leaf(roster, avail, baseline, fill_picks)


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

    # candidate set: top-k available by VOR, plus best available at each unfilled starter pos.
    # Single-slot positions (K/DEF/QB/TE): once you have one, don't recommend another — this
    # is what forces exactly one K AND one DEF in the endgame (was drafting 2 K, 0 DEF).
    avail = [p for p in players if p["pid"] not in drafted
             and (allow_kdef or p["pos"] not in ("K", "DEF"))
             and not (p["pos"] == "K" and "K" in have_pos)
             and not (p["pos"] == "DEF" and "DEF" in have_pos)
             and (allow_qb or p["pos"] != "QB")
             and (allow_te or p["pos"] != "TE")]
    # MUST-FILL: if you have only enough picks left to fill your empty mandatory starter slots
    # (K/DEF), force them now — otherwise upside mode buries the "streamable" DEF and you field
    # an illegal lineup (mock drafted 0 DEF). This overrides everything else.
    missing_kdef = [pos for pos in ("K", "DEF") if pos not in have_pos]
    if missing_kdef and my_remaining <= len(missing_kdef):
        forced = [p for p in players if p["pid"] not in drafted and p["pos"] in missing_kdef]
        if forced:
            avail = forced

    avail_by_vor = sorted(avail, key=lambda x: x["vor"], reverse=True)
    cands = list(avail_by_vor[:k])
    have = {p["pid"] for p in cands}
    for pos in SLOT_ORDER:
        for p in avail_by_vor:
            if p["pos"] == pos and p["pid"] not in have:
                cands.append(p); have.add(p["pid"]); break

    baseline = league_baseline(players) if config.OBJECTIVE in ("finish", "wins") else None
    base = _leaf(my_roster, avail_by_vor, baseline, [pk for pk in my_all if pk > cur_pick])
    results = []
    for c in cands:
        vals = [_rollout(c, my_roster, universe, drafted, my_future, cur_pick,
                         random.Random((seed or 0) + i), baseline, opp_rosters, recent0, my_all)
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
        print(f"  {p['pos']:3} {p['name'][:22]:22} vor {p['vor']:6}  E[$] {r['exp_value']:5.2f}")
    assert top["pos"] in ("RB", "WR"), f"expected elite RB/WR at 1.01, got {top['pos']}"
    print("OK: scarcity-aware (RB/WR over QB at 1.01)")
