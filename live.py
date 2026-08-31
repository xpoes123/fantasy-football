"""Live draft loop. Polls the Sleeper draft, and after every pick reprints the board:
your recommendation, best available, your roster + needs, and recent picks (to spot runs).

Usage:
    python3 live.py                 # auto-detect your slot from draft_order once live
    python3 live.py --slot 7        # force your draft slot (use before order is set)
    python3 live.py --once          # print once and exit (for testing)
"""
import argparse, json, os, sys, time, urllib.request
import config, data, engine

C = {"hd": "\033[1;36m", "me": "\033[1;32m", "warn": "\033[1;33m",
     "dim": "\033[2m", "rb": "\033[38;5;209m", "wr": "\033[38;5;75m",
     "qb": "\033[38;5;213m", "te": "\033[38;5;150m", "k": "\033[2m",
     "def": "\033[2m", "r": "\033[0m", "hi": "\033[1;97;41m"}
POSC = {"RB": C["rb"], "WR": C["wr"], "QB": C["qb"], "TE": C["te"], "K": C["k"], "DEF": C["def"]}


def _api(path):
    with urllib.request.urlopen(f"https://api.sleeper.app/v1/{path}", timeout=15) as r:
        return json.load(r)


def users_map():
    return {u["user_id"]: (u.get("metadata", {}).get("team_name") or u.get("display_name"))
            for u in _api(f"league/{config.LEAGUE_ID}/users")}


def my_slot(draft, override):
    if override:
        return override
    order = draft.get("draft_order") or {}
    return order.get(config.MY_USER_ID)


def board_state(players):
    """Return (drafted_ids, pid->player)."""
    idx = {p["pid"]: p for p in players}
    return idx


def resolve_pick(p, idx):
    """A drafted pick -> a player dict. Uses our board if present, else a stub from the
    pick's own metadata so YOUR pick never vanishes from the roster (which would break needs)."""
    pl = idx.get(p["player_id"])
    if pl:
        return pl
    m = p.get("metadata", {})
    return {"pid": p["player_id"], "pos": m.get("position", "?"),
            "name": (m.get("first_name", "") + " " + m.get("last_name", "")).strip() or "(pick)",
            "team": m.get("team"), "adj_proj": 40.0, "vor": 0.0, "adp": 999.0, "inj": None}


def needs(roster, picks_left=99):
    """Which starter slots are still unfilled, given greedy assignment. K/DEF are hidden
    until the endgame (mirrors the engine's allow_kdef) so they don't clutter needs/cliffs."""
    cnt = {}
    for p in roster:
        cnt[p["pos"]] = cnt.get(p["pos"], 0) + 1
    endgame = picks_left <= (("K" not in cnt) + ("DEF" not in cnt) + 1)
    left = []
    for pos, n in config.SLOTS.items():
        if pos == "FLEX":
            continue
        if pos in ("K", "DEF") and not endgame:
            continue
        short = n - cnt.get(pos, 0)
        left += [pos] * max(0, short)
    flex_elig = sum(max(0, cnt.get(p, 0) - config.SLOTS[p]) for p in config.FLEX_POS)
    left += ["FLEX"] * max(0, config.SLOTS["FLEX"] - flex_elig)
    return left


def render(draft, picks, players, idx, slot, umap):
    print("\033[2J\033[H", end="")  # clear screen + home cursor (no shell)
    teams, rounds = config.NUM_TEAMS, config.ROUNDS
    n = len(picks)
    cur = n + 1
    rnd = (cur - 1) // teams + 1
    in_rnd = (cur - 1) % teams + 1
    on_slot = slot_on_clock(cur, teams) if cur <= teams * rounds else None
    drafted = {p["player_id"] for p in picks}
    my_picks_no = engine.snake_picks(slot) if slot else []
    my_next = next((pk for pk in my_picks_no if pk >= cur), None)
    my_roster = [resolve_pick(p, idx) for p in picks if p.get("draft_slot") == slot]

    order_rev = {v: k for k, v in (draft.get("draft_order") or {}).items()}
    on_team = umap.get(order_rev.get(on_slot), f"slot {on_slot}") if order_rev else f"slot {on_slot}"

    print(f"{C['hd']}{draft['metadata']['name']} — Pick {rnd}.{in_rnd:02d} (#{cur}/{teams*rounds}){C['r']}")
    if not slot:
        print(f"{C['warn']}Your slot unknown (draft_order not set). Re-run with --slot N.{C['r']}")
    else:
        mine_now = (on_slot == slot)
        tag = f"{C['hi']} YOUR PICK {C['r']}" if mine_now else f"on the clock: {C['me']}{on_team}{C['r']}"
        away = (my_next - cur) if my_next else None
        nxt = f"  your next: #{my_next} ({away} away)" if my_next else "  (roster full)"
        print(f"{tag}{nxt}\n")

    if slot and my_next:
        avail_ct = sum(1 for p in players if p["pid"] not in drafted)
        rolls = 60 if on_slot == slot else 30
        recs = engine.recommend(players, drafted, my_roster, slot, my_next,
                                rollouts=rolls, seed=7)
        print(f"{C['hd']}── RECOMMENDED (for your pick #{my_next}) ──{C['r']}")
        for i, rr in enumerate(recs[:6]):
            p = rr["player"]
            star = "➤ " if i == 0 else "  "
            print(f"{star}{POSC.get(p['pos'],'')}{p['pos']:3}{C['r']} {p['name'][:22]:22}"
                  f" {C['dim']}vor{C['r']}{p['vor']:6.0f} {C['dim']}adp{C['r']}{p['adp']:6.1f}"
                  f"  {C['dim']}E[wins]{C['r']}{rr['exp_value']:6.1f}")
        # scarcity note: cliff at your top need positions
        picks_left = len([pk for pk in my_picks_no if pk >= cur])
        cliff_note(players, drafted, needs(my_roster, picks_left))
        print()

    # best available
    avail = sorted((p for p in players if p["pid"] not in drafted),
                   key=lambda x: x["vor"], reverse=True)
    print(f"{C['hd']}── BEST AVAILABLE ──{C['r']}")
    for p in avail[:12]:
        inj = f" {C['warn']}{p['inj']}{C['r']}" if p.get("inj") else ""
        print(f"  {POSC.get(p['pos'],'')}{p['pos']:3}{C['r']} {p['name'][:22]:22}"
              f" {C['dim']}vor{C['r']}{p['vor']:6.0f} {C['dim']}adp{C['r']}{p['adp']:6.1f}"
              f" {C['dim']}{p['team'] or '':3}{C['r']}{inj}")

    # my roster + needs
    if slot:
        print(f"\n{C['hd']}── YOUR ROSTER ({len(my_roster)}) ──{C['r']}")
        for p in sorted(my_roster, key=lambda x: (x["pos"], -x["adj_proj"])):
            print(f"  {POSC.get(p['pos'],'')}{p['pos']:3}{C['r']} {p['name'][:22]:22} {C['dim']}{p['adj_proj']:.0f}{C['r']}")
        nd = needs(my_roster, len([pk for pk in my_picks_no if pk >= cur]))
        print(f"  {C['warn']}need: {' '.join(nd) if nd else 'starters full — best available'}{C['r']}")

    # recent picks (spot runs)
    if picks:
        print(f"\n{C['hd']}── RECENT ──{C['r']}")
        for p in picks[-6:]:
            m = p.get("metadata", {})
            who = umap.get(p.get("picked_by"), "")
            print(f"  {C['dim']}#{p['pick_no']:3} {m.get('position','?'):3} "
                  f"{(m.get('first_name','')+' '+m.get('last_name','')).strip()[:22]:22} → {who}{C['r']}")
    print(f"\n{C['dim']}polling every {config.POLL_SECONDS}s — Ctrl-C to quit{C['r']}")


def cliff_note(players, drafted, need_positions):
    """For each still-needed starter position, show the VOR drop from best to 3rd-best
    available — a big cliff means grab now."""
    seen = []
    for pos in need_positions:
        if pos == "FLEX" or pos in seen:
            continue
        seen.append(pos)
        pool = sorted((p for p in players if p["pos"] == pos and p["pid"] not in drafted),
                      key=lambda x: x["vor"], reverse=True)
        if len(pool) >= 3:
            cliff = pool[0]["vor"] - pool[2]["vor"]
            flag = f"{C['warn']}◀ steep cliff{C['r']}" if cliff > 30 else ""
            print(f"  {C['dim']}{pos} cliff: {pool[0]['name'][:16]} "
                  f"→ 3rd best drops {cliff:.0f} vor{C['r']} {flag}")


def slot_on_clock(pick_no, teams):
    r = (pick_no - 1) // teams + 1
    in_rnd = (pick_no - 1) % teams + 1
    return in_rnd if r % 2 else teams + 1 - in_rnd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=None)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    print("Loading board (Sleeper + ESPN + Vegas)...")
    players = data.build_players()
    idx = board_state(players)
    umap = users_map()
    print(f"{len(players)} players ranked. Watching draft {config.DRAFT_ID}\n")

    last = -1
    while True:
        try:
            draft = _api(f"draft/{config.DRAFT_ID}")
            picks = _api(f"draft/{config.DRAFT_ID}/picks")
            slot = my_slot(draft, args.slot)
            if len(picks) != last or args.once:
                render(draft, picks, players, idx, slot, umap)
                last = len(picks)
            if args.once:
                return
        except Exception as e:
            print(f"{C['warn']}poll error: {e}{C['r']}", file=sys.stderr)
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
