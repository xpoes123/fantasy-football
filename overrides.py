"""Hand-editable knobs. Edit before/during the draft for things the models can't see.

GAMES_MISSED: player name -> expected regular-season games missed (out of 17).
  The model haircuts adj_proj by (17 - games_missed)/17. Use for known IR/injury
  timetables the Sleeper injury_status can't quantify (e.g. a mid-season return), or
  suspensions. 17 = out for the year (drops off the board entirely).

BUMP: player name -> multiplier on adj_proj (1.10 = you like them 10% more than
  consensus, 0.90 = fade). For your own reads / news the feeds don't have yet.

Names are matched case-insensitively against the player's full name.
"""

# ponytail: precise availability needs a human — this dict is that knob. Populated from a
# current-NFL research sweep (2026-08-31); update as news breaks.
GAMES_MISSED = {
    "Josh Jacobs": 17,      # per David — out for the year (suspension situation)
    "Ashton Jeanty": 3,     # low-ankle sprain, back after a few weeks (not IR)
    "Jordyn Tyson": 6,      # hamstring — reported ~October return
}

BUMP = {
    # "Puka Nacua": 1.08,
}
