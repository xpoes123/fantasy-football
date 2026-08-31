"""Hand-editable knobs. Edit before/during the draft for things the models can't see.

GAMES_MISSED: player name -> expected regular-season games missed (out of 17).
  The model haircuts adj_proj by (17 - games_missed)/17. Use for known IR/injury
  timetables the Sleeper injury_status can't quantify (e.g. a mid-season return).

BUMP: player name -> multiplier on adj_proj (1.10 = you like them 10% more than
  consensus, 0.90 = fade). For your own reads / news the feeds don't have yet.

Names are matched case-insensitively against the player's full name.
"""

# ponytail: precise return weeks need a human — this dict is that knob. Fill as news breaks.
GAMES_MISSED = {
    # "Tucker Kraft": 6,      # example: out ~6 weeks, back midseason
}

BUMP = {
    # "Puka Nacua": 1.08,
}
