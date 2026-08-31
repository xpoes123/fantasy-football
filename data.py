"""Build the unified player table: Sleeper meta + ESPN proj/ADP + Vegas/age/injury
adjustments + VOR. Cached to data/cache/ so we don't refetch every launch."""
import json, os, time, urllib.request, urllib.parse
import config, overrides

CACHE = config.CACHE_DIR
os.makedirs(CACHE, exist_ok=True)

# ESPN position ids we care about come via Sleeper instead; keep for DEF/K fallback.
NFL_ABBR = {  # Odds API full name -> Sleeper team abbrev
    "Arizona Cardinals":"ARI","Atlanta Falcons":"ATL","Baltimore Ravens":"BAL",
    "Buffalo Bills":"BUF","Carolina Panthers":"CAR","Chicago Bears":"CHI",
    "Cincinnati Bengals":"CIN","Cleveland Browns":"CLE","Dallas Cowboys":"DAL",
    "Denver Broncos":"DEN","Detroit Lions":"DET","Green Bay Packers":"GB",
    "Houston Texans":"HOU","Indianapolis Colts":"IND","Jacksonville Jaguars":"JAX",
    "Kansas City Chiefs":"KC","Las Vegas Raiders":"LV","Los Angeles Chargers":"LAC",
    "Los Angeles Rams":"LAR","Miami Dolphins":"MIA","Minnesota Vikings":"MIN",
    "New England Patriots":"NE","New Orleans Saints":"NO","New York Giants":"NYG",
    "New York Jets":"NYJ","Philadelphia Eagles":"PHI","Pittsburgh Steelers":"PIT",
    "San Francisco 49ers":"SF","Seattle Seahawks":"SEA","Tampa Bay Buccaneers":"TB",
    "Tennessee Titans":"TEN","Washington Commanders":"WAS",
}

# replacement rank per position given 12-team league demand (starters + flex share)
REPL_RANK = {"QB":12, "RB":36, "WR":35, "TE":13, "K":12, "DEF":12}


def _get(url, headers=None, ttl=86400):
    """GET with a simple on-disk cache keyed by url. ttl seconds."""
    key = os.path.join(CACHE, urllib.parse.quote(url, safe="")[:180] + ".json")
    if os.path.exists(key) and time.time() - os.path.getmtime(key) < ttl:
        with open(key) as f:
            return json.load(f)
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    with open(key, "w") as f:
        json.dump(data, f)
    return data


def sleeper_players(ttl=86400):
    """player_id -> meta. The dump is ~5MB; cache it hard."""
    return _get("https://api.sleeper.app/v1/players/nfl", ttl=ttl)


ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}


def _norm(name):
    """Normalize a player name for fuzzy joining: lowercase, drop punctuation/suffixes."""
    n = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    for suf in (" jr", " sr", " ii", " iii", " iv", " v"):
        if n.endswith(suf):
            n = n[: -len(suf)]
    return " ".join(n.split())


def espn_proj_adp(ttl=21600):
    """Return (by_id, by_name) where each maps -> {proj, adp}.
    by_id keyed on str(espn athlete id); by_name keyed on '<norm name>|<POS>'."""
    url = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026"
           "/segments/0/leaguedefaults/3?view=kona_player_info")
    hdr = {"accept": "application/json",
           "x-fantasy-filter": json.dumps({"players": {"limit": 600,
               "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "PPR"}}})}
    d = _get(url, headers=hdr, ttl=ttl)
    by_id, by_name = {}, {}
    for entry in d.get("players", []):
        p = entry["player"]
        proj = next((s["appliedTotal"] for s in p.get("stats", [])
                     if s.get("seasonId") == 2026 and s.get("statSourceId") == 1
                     and s.get("statSplitTypeId") == 0 and s.get("scoringPeriodId") == 0), None)
        rec = {"proj": proj, "adp": (p.get("ownership") or {}).get("averageDraftPosition")}
        by_id[str(p["id"])] = rec
        pos = ESPN_POS.get(p.get("defaultPositionId"))
        if pos and p.get("fullName"):
            by_name[_norm(p["fullName"]) + "|" + pos] = rec
    return by_id, by_name


def team_env(ttl=21600):
    """team abbrev -> offensive-environment multiplier from Vegas season implied points."""
    url = ("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
           f"?apiKey={config.ODDS_API_KEY}&regions=us&markets=spreads,totals&oddsFormat=american")
    games = _get(url, ttl=ttl)
    pts = {}  # abbrev -> summed implied points
    for g in games:
        home, away = g["home_team"], g["away_team"]
        total = spread_home = None
        for bk in g.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk["key"] == "totals" and total is None:
                    total = mk["outcomes"][0].get("point")
                if mk["key"] == "spreads" and spread_home is None:
                    for o in mk["outcomes"]:
                        if o["name"] == home:
                            spread_home = o.get("point")
            if total is not None and spread_home is not None:
                break
        if total is None or spread_home is None:
            continue
        # implied points = total/2 - spread/2  (favorite: negative spread -> more points)
        ih = total / 2 - spread_home / 2
        ia = total / 2 + spread_home / 2
        for name, ip in ((home, ih), (away, ia)):
            ab = NFL_ABBR.get(name)
            if ab:
                pts[ab] = pts.get(ab, 0.0) + ip
    if not pts:
        return {}
    avg = sum(pts.values()) / len(pts)
    # multiplier: teams ±, damped so it nudges not dominates (0.5 weight)
    return {ab: 1.0 + 0.5 * (v - avg) / avg for ab, v in pts.items()}


def age_mult(pos, age):
    """Position age curve. Multiplier on projection. None age -> 1.0."""
    if not age:
        return 1.0
    if pos == "RB":
        if age >= 30: return 0.85
        if age >= 28: return 0.93
        return 1.0
    if pos == "WR":
        if age >= 32: return 0.88
        if age >= 30: return 0.95
        return 1.0
    if pos == "TE":
        if age >= 33: return 0.90
        return 1.0
    if pos == "QB":
        if age >= 39: return 0.92
        return 1.0
    return 1.0


def injury_mult(name, status):
    """Games-missed haircut. overrides.GAMES_MISSED wins; else map Sleeper status."""
    gm = overrides.GAMES_MISSED.get(name)
    if gm is None:
        gm = {"IR": 8, "Out": 2, "Doubtful": 1, "PUP": 6, "Sus": 3,
              "NA": 4}.get(status, 0)
    return max(0.0, (17 - gm) / 17)


def build_players():
    """Return list of player dicts with adj_proj and vor, sorted by vor desc.
    Only skill positions + K/DEF that have a projection or are draftable."""
    sl = sleeper_players()
    espn_id, espn_name = espn_proj_adp()
    env = team_env()

    # index espn by id already; join Sleeper -> espn via espn_id
    players = []
    for pid, m in sl.items():
        pos = m.get("position")
        if pos not in ("QB", "RB", "WR", "TE", "K", "DEF"):
            continue
        if not m.get("team"):  # free agents / not on a roster -> skip clutter
            if pos != "DEF":
                continue
        name = m.get("full_name") or (m.get("first_name", "") + " " + m.get("last_name", "")).strip()
        eid = str(m.get("espn_id")) if m.get("espn_id") else None
        e = espn_id.get(eid) if eid else None       # try id join first
        if not e:                                    # fall back to name+pos
            e = espn_name.get(_norm(name) + "|" + pos, {})
        proj = e.get("proj")
        adp = e.get("adp")
        if proj is None:
            # DEF/K or unprojected: give a tiny baseline so they're draftable late, no VOR edge
            if pos in ("K", "DEF"):
                proj = 110.0 if pos == "K" else 100.0
            else:
                continue  # skip skill players ESPN doesn't project (deep bench noise)
        adj = proj
        adj *= env.get(m.get("team"), 1.0)
        adj *= age_mult(pos, m.get("age"))
        adj *= injury_mult(name, m.get("injury_status"))
        adj *= overrides.BUMP.get(name, 1.0)
        players.append({
            "pid": pid, "name": name, "pos": pos, "team": m.get("team"),
            "age": m.get("age"), "inj": m.get("injury_status"),
            "proj": round(proj, 1), "adj_proj": round(adj, 1),
            "adp": adp if adp else 999.0,
        })

    # VOR = adj_proj - replacement-level adj_proj at position
    by_pos = {}
    for p in players:
        by_pos.setdefault(p["pos"], []).append(p)
    for pos, ps in by_pos.items():
        ps.sort(key=lambda x: x["adj_proj"], reverse=True)
        rank = REPL_RANK.get(pos, 12)
        repl = ps[rank - 1]["adj_proj"] if len(ps) >= rank else (ps[-1]["adj_proj"] if ps else 0)
        for p in ps:
            p["vor"] = round(p["adj_proj"] - repl, 1)

    players.sort(key=lambda x: x["vor"], reverse=True)
    return players


if __name__ == "__main__":
    ps = build_players()
    print(f"{len(ps)} players\n")
    print(f"{'POS':4}{'NAME':24}{'TM':4}{'AGE':4}{'PROJ':>7}{'ADJ':>7}{'VOR':>7}{'ADP':>7}")
    for p in ps[:40]:
        print(f"{p['pos']:4}{p['name'][:23]:24}{(p['team'] or '-'):4}"
              f"{str(p['age'] or '-'):4}{p['proj']:>7}{p['adj_proj']:>7}{p['vor']:>7}{p['adp']:>7}")
