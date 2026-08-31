"""FastAPI app for fantasy.djiang.xyz — live draft board in the browser.

Serves static/index.html and a /api/state endpoint that returns the current draft
state + Monte Carlo recommendations as JSON. Recommendations are recomputed only when
a new pick lands (cached by pick count + slot), so polling every few seconds is cheap.
"""
import json, threading, urllib.request
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os

import config, data, engine, live

app = FastAPI()
_lock = threading.Lock()
_board = {"players": None, "idx": None, "umap": None}
_cache = {"key": None, "state": None}
HERE = os.path.dirname(__file__)


def board():
    """Build the ranked board once, hold in memory. Restart to pick up overrides.py edits."""
    if _board["players"] is None:
        with _lock:
            if _board["players"] is None:
                players = data.build_players()
                _board["players"] = players
                _board["idx"] = {p["pid"]: p for p in players}
                _board["umap"] = live.users_map()
    return _board


def _api(path):
    with urllib.request.urlopen(f"https://api.sleeper.app/v1/{path}", timeout=15) as r:
        return json.load(r)


def compute_state(slot_override):
    b = board()
    players, idx, umap = b["players"], b["idx"], b["umap"]
    draft = _api(f"draft/{config.DRAFT_ID}")
    picks = _api(f"draft/{config.DRAFT_ID}/picks")

    order = draft.get("draft_order") or {}
    slot = slot_override or order.get(config.MY_USER_ID)
    key = (len(picks), slot)
    if _cache["key"] == key and _cache["state"] is not None:
        return _cache["state"]

    teams, rounds = config.NUM_TEAMS, config.ROUNDS
    n = len(picks)
    cur = n + 1
    on_slot = live.slot_on_clock(cur, teams) if cur <= teams * rounds else None
    drafted = {p["player_id"] for p in picks}
    order_rev = {v: k for k, v in order.items()}
    on_team = umap.get(order_rev.get(on_slot)) if order_rev else None

    my_next = my_roster = recs = cliffs = need = None
    if slot:
        my_all = engine.snake_picks(slot)
        my_next = next((pk for pk in my_all if pk >= cur), None)
        my_roster = [idx[p["player_id"]] for p in picks
                     if p.get("draft_slot") == slot and p["player_id"] in idx]
        need = live.needs(my_roster)
        if my_next:
            rolls = 60 if on_slot == slot else 35
            r = engine.recommend(players, drafted, my_roster, slot, my_next,
                                 rollouts=rolls, seed=7)
            recs = [{"pos": x["player"]["pos"], "name": x["player"]["name"],
                     "team": x["player"]["team"], "inj": x["player"].get("inj"),
                     "vor": x["player"]["vor"], "adp": x["player"]["adp"],
                     "exp": round(x["exp_value"], 0)} for x in r[:6]]
            cliffs = _cliffs(players, drafted, need)

    avail = sorted((p for p in players if p["pid"] not in drafted),
                   key=lambda x: x["vor"], reverse=True)
    state = {
        "draft_name": draft["metadata"]["name"], "status": draft["status"],
        "overall": cur, "round": (cur - 1) // teams + 1, "in_round": (cur - 1) % teams + 1,
        "total": teams * rounds, "on_slot": on_slot, "on_team": on_team,
        "slot": slot, "my_next": my_next,
        "picks_away": (my_next - cur) if my_next else None,
        "is_mine": (slot is not None and on_slot == slot),
        "recommendations": recs, "cliffs": cliffs, "needs": need,
        "best_available": [{"pos": p["pos"], "name": p["name"], "team": p["team"],
                            "inj": p.get("inj"), "vor": p["vor"], "adp": p["adp"]}
                           for p in avail[:16]],
        "my_roster": [{"pos": p["pos"], "name": p["name"], "pts": round(p["adj_proj"])}
                      for p in sorted(my_roster or [], key=lambda x: (x["pos"], -x["adj_proj"]))],
        "recent": [{"pick": p["pick_no"], "pos": p.get("metadata", {}).get("position", "?"),
                    "name": (p.get("metadata", {}).get("first_name", "") + " " +
                             p.get("metadata", {}).get("last_name", "")).strip(),
                    "who": umap.get(p.get("picked_by"), "")} for p in picks[-8:]][::-1],
    }
    _cache["key"], _cache["state"] = key, state
    return state


def _cliffs(players, drafted, need_positions):
    out, seen = [], []
    for pos in (need_positions or []):
        if pos == "FLEX" or pos in seen:
            continue
        seen.append(pos)
        pool = sorted((p for p in players if p["pos"] == pos and p["pid"] not in drafted),
                      key=lambda x: x["vor"], reverse=True)
        if len(pool) >= 3:
            drop = round(pool[0]["vor"] - pool[2]["vor"])
            out.append({"pos": pos, "name": pool[0]["name"], "drop": drop, "steep": drop > 30})
    return out


@app.get("/api/state")
def state(slot: int = 0):
    try:
        return compute_state(slot or None)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
