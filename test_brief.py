"""Offline checks for brief.py news->player matching. No network."""
import brief, config


def _pl(pid, name, team, pos="WR"):
    return {"pid": pid, "name": name, "team": team, "pos": pos}


BOARD = [_pl("ajb", "A.J. Brown", "PHI"), _pl("mqb", "Marquise Brown", "KC"),
         _pl("chb", "Chase Brown", "CIN", "RB"), _pl("arsb", "Amon-Ra St. Brown", "DET"),
         _pl("jbr", "Jake Browning", "CIN", "QB"), _pl("mh", "Marvin Harrison Jr.", "ARI"),
         _pl("puka", "Puka Nacua", "LAR")]


def _news(monkeypatch, roster, news):
    idx = {p["pid"]: p for p in BOARD}
    monkeypatch.setattr(brief, "drafted_leagues", lambda: [("L1", "League", "T")])
    monkeypatch.setattr(brief, "_api", lambda path: [{"owner_id": config.MY_USER_ID, "players": roster}])
    _, facts = brief.gather(idx, {}, news)
    return {pid: [b for b in f["bits"] if b.startswith("news:")] for pid, f in facts.items()}


def test_shared_last_name_doesnt_steal_news(monkeypatch):
    got = _news(monkeypatch, ["ajb"], [
        "Chiefs' Marquise Brown limited at practice — hamstring",
        "Chase Brown takes over Bengals backfield",
        "Amon-Ra St. Brown sets Lions record",
        "Browns sign kicker",
        "Jake Browning to start for Cincinnati"])
    assert got.get("ajb", []) == []


def test_full_name_matches(monkeypatch):
    got = _news(monkeypatch, ["ajb", "mh"], [
        "Eagles WR A.J. Brown (knee) questionable",
        "Marvin Harrison Jr. returns to practice"])
    assert got["ajb"] == ["news: Eagles WR A.J. Brown (knee) questionable"]
    assert got["mh"] == ["news: Marvin Harrison Jr. returns to practice"]


def test_last_name_only_when_unambiguous_or_team_named(monkeypatch):
    got = _news(monkeypatch, ["puka", "ajb"], [
        "Nacua dominates in Rams win",                 # unique surname -> ok
        "Eagles' Brown catches two TDs"])              # shared surname, but his team is named
    assert got["puka"] == ["news: Nacua dominates in Rams win"]
    assert got["ajb"] == ["news: Eagles' Brown catches two TDs"]
