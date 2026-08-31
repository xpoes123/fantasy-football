"""Fast, network-free checks for the load-bearing pure logic: snake-pick math and the
starting-lineup optimizer. Run: python3 test_engine.py"""
import config, engine, live


def p(pos, pts):
    return {"pid": f"{pos}{pts}", "name": pos, "pos": pos, "adj_proj": pts, "vor": pts}


def test_snake():
    # slot 1: picks 1, then 24 (round 2 reverses), then 25, ...
    assert engine.snake_picks(1)[:4] == [1, 24, 25, 48]
    # slot 12: 12, 13, 36, 37
    assert engine.snake_picks(12)[:4] == [12, 13, 36, 37]
    # every overall pick 1..180 is covered exactly once across all slots
    allp = sorted(pk for s in range(1, 13) for pk in engine.snake_picks(s))
    assert allp == list(range(1, 181))


def test_start_value():
    # one QB + three RB: starts QB + 2 RB (dedicated) + 1 RB (flex) = 3 highest RB + QB
    roster = [p("QB", 300), p("RB", 200), p("RB", 150), p("RB", 100), p("RB", 50)]
    # QB + 2 dedicated RB + 2 FLEX (both leftover RBs) — nothing left to bench
    assert abs(engine.start_value(roster) - (300 + 200 + 150 + 100 + 50)) < 1e-6
    # a 6th RB now goes to bench at 0.1 weight
    assert abs(engine.start_value(roster + [p("RB", 40)]) - (800 + 0.1 * 40)) < 1e-6


def test_needs():
    assert set(live.needs([])) == {"QB", "RB", "WR", "TE", "K", "DEF", "FLEX"}
    # two RBs fills both RB slots; still need everything else + flex
    nd = live.needs([p("RB", 200), p("RB", 100)])
    assert "RB" not in nd and nd.count("FLEX") == 2


if __name__ == "__main__":
    test_snake(); test_start_value(); test_needs()
    print("OK: snake math, lineup optimizer, roster needs")
