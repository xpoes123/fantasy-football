"""Backtest the draft ENGINE on 2024: draft a team using only preseason info (Sleeper season
projections + preseason ADP), then score every roster by what ACTUALLY happened in 2024.

Compares three drafters, each in a 12-team snake vs 11 ADP-bots:
  model : the tool (engine.recommend finish-EV/scarcity + late-round upside)
  adp   : always best-available by preseason ADP (what most people do)
  proj  : always best-available by projection
Metric = best-lineup ACTUAL 2024 points (season totals), averaged over draft slots/seeds, plus
the strategy team's finish (rank by actual points) among the 12 teams in its own draft.

Caveat: uses season-total actuals (not week-by-week H2H optimization) and Sleeper's own
projection (mild in-season revision baked in). It tests the DRAFT STRATEGY, not the 2025
projection pipeline. Run: python3 backtest.py
"""
import json, random, sys, urllib.request
import config, engine

REPL_RANK = {"QB": 13, "RB": 38, "WR": 44, "TE": 14, "K": 12, "DEF": 12}
LINEUP = [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("K", 1), ("DEF", 1)]  # + 2 FLEX(RB/WR/TE)


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_2024():
    """Board of draftable 2024 players: proj + preseason adp + ACTUAL season points, joined on
    player_id. adj_proj = proj (no 2025-specific vegas/SOS layers — this tests the engine, not
    those knobs); vor computed engine-style off replacement rank."""
    proj = _get("https://api.sleeper.com/projections/nfl/2024?season_type=regular")
    actual = _get("https://api.sleeper.app/v1/stats/nfl/regular/2024")
    meta = _get("https://api.sleeper.app/v1/players/nfl")
    board = []
    for r in proj:
        pid = r.get("player_id")
        st = r.get("stats") or {}
        pp, adp = st.get("pts_ppr"), st.get("adp_ppr")
        if not pid or pp is None or adp is None or adp >= 400:
            continue
        m = meta.get(pid) or {}
        pos = m.get("position")
        if pos not in ("QB", "RB", "WR", "TE", "K", "DEF"):
            continue
        act = (actual.get(pid) or {}).get("pts_ppr") or 0.0
        board.append({"pid": pid, "name": m.get("full_name") or pid, "pos": pos,
                      "team": m.get("team"), "age": m.get("age"),
                      "proj": round(pp, 1), "adj_proj": round(pp, 1),
                      "adp": adp, "actual": round(act, 1)})
    # engine-style VOR off replacement rank per position
    by_pos = {}
    for p in board:
        by_pos.setdefault(p["pos"], []).append(p)
    for pos, ps in by_pos.items():
        ps.sort(key=lambda x: -x["adj_proj"])
        rk = REPL_RANK.get(pos, 12)
        repl = ps[rk - 1]["adj_proj"] if len(ps) >= rk else (ps[-1]["adj_proj"] if ps else 0)
        for p in ps:
            p["vor"] = round(p["adj_proj"] - repl, 1)
    board.sort(key=lambda x: -x["vor"])
    return board


def lineup_pts(roster):
    """Best legal starting-lineup total by ACTUAL points (season totals)."""
    by = {pos: sorted((p["actual"] for p in roster if p["pos"] == pos), reverse=True)
          for pos in ("QB", "RB", "WR", "TE", "K", "DEF")}
    total, used = 0.0, {}
    for pos, n in LINEUP:
        total += sum(by[pos][:n]); used[pos] = n
    flex = []
    for pos in ("RB", "WR", "TE"):
        flex += by[pos][used[pos]:]
    flex.sort(reverse=True)
    return total + sum(flex[:config.SLOTS["FLEX"]])


def _model_pick(board, drafted, roster, slot, cur, opp_rosters, recent, seed):
    opp_pos = {s: [p["pos"] for p in r] for s, r in opp_rosters.items()}
    recs = engine.recommend(board, drafted, roster, slot, cur, rollouts=12, seed=seed,
                            opp_rosters=opp_pos, recent0=recent)
    if not recs:
        return None
    rnd = (cur - 1) // config.NUM_TEAMS + 1
    import live
    need = live.needs(roster, len([pk for pk in engine.snake_picks(slot) if pk >= cur]))
    have_qb = any(p["pos"] == "QB" for p in roster)
    counts = {}
    for p in roster:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1
    cands = [r["player"] for r in recs]
    if rnd >= config.UPSIDE_ROUND or not [n for n in need if n not in ("K", "DEF")]:
        cands.sort(key=lambda p: engine.upside_score(p, have_qb, counts), reverse=True)
    return cands[0]


def draft(strategy, my_slot, board, seed=1):
    """One 12-team snake. `my_slot` uses `strategy`; the other 11 draft by ADP. Returns all
    rosters (slot -> roster)."""
    drafted, recent = set(), []
    rosters = {s: [] for s in range(1, config.NUM_TEAMS + 1)}
    rng = random.Random(seed)
    for pick_no in range(1, config.NUM_TEAMS * config.ROUNDS + 1):
        slot = engine._slot_on_clock(pick_no)
        avail = [p for p in board if p["pid"] not in drafted]
        if slot == my_slot:
            if strategy == "model":
                pick = _model_pick(board, drafted, rosters[slot], my_slot, pick_no, rosters, recent, seed)
            elif strategy == "proj":
                pick = _need_pick(rosters[slot], sorted(avail, key=lambda x: -x["adj_proj"]))
            else:  # adp
                pick = _need_pick(rosters[slot], sorted(avail, key=lambda x: x["adp"]))
        else:
            pick = engine._opp_pick(sorted(avail, key=lambda x: x["adp"]), pick_no, rng,
                                    [p["pos"] for p in rosters[slot]], recent)
        if pick:
            drafted.add(pick["pid"]); rosters[slot].append(pick)
            recent.append(pick["pos"]); recent = recent[-config.OPP_RUN_K:]
    return rosters


_CAP = {"QB": 2, "RB": 6, "WR": 6, "TE": 2, "K": 1, "DEF": 1}


def _need_pick(roster, ranked):
    """Best-available for the naive baselines, but respect roster caps so ADP/proj bots still
    field a legal lineup (else pure-proj drafts 8 WRs and no K/DEF — an unfair strawman)."""
    cnt = {}
    for p in roster:
        cnt[p["pos"]] = cnt.get(p["pos"], 0) + 1
    for p in ranked:
        if cnt.get(p["pos"], 0) < _CAP.get(p["pos"], 6):
            return p
    return ranked[0] if ranked else None


def run(slots=(1, 3, 6, 9, 11), seeds=(1, 2)):
    board = load_2024()
    print(f"loaded {len(board)} draftable 2024 players\n")
    agg = {s: {"pts": [], "finish": []} for s in ("model", "adp", "proj")}
    for slot in slots:
        for seed in seeds:
            for strat in ("model", "adp", "proj"):
                rosters = draft(strat, slot, board, seed)
                pts = {s: lineup_pts(r) for s, r in rosters.items()}
                mine = pts[slot]
                finish = 1 + sum(1 for s, v in pts.items() if v > mine)  # rank by actual points
                agg[strat]["pts"].append(mine)
                agg[strat]["finish"].append(finish)
            print(f"  slot {slot:2} seed {seed}:  "
                  + "  ".join(f"{s}={agg[s]['pts'][-1]:6.0f}pts/#{agg[s]['finish'][-1]}" for s in ("model", "adp", "proj")))
    print("\n=== 2024 BACKTEST — avg best-lineup ACTUAL points & finish (lower # = better) ===")
    for s in ("model", "adp", "proj"):
        p, f = agg[s]["pts"], agg[s]["finish"]
        print(f"  {s:5}:  {sum(p)/len(p):6.0f} actual pts   avg finish {sum(f)/len(f):.2f}   "
              f"(n={len(p)})")


if __name__ == "__main__":
    run()
