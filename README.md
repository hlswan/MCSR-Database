# MCSR Sub-10 Leaderboard Database

A SQLite database and Python import pipeline for Minecraft Java Edition 1.16.1 RSG Any%. Trying to get all sub10s but currently only have 552 or something. **Every sub8 should be on the sheet though**(as of 12 Mar, '26).

The leaderboard is trying to track every sub-10 minute speedrun but I don't have them all(yet). Stop being so cracked people. I estimate I probably have 30% of all sub10 runs. This database does include every sub8. The database is generated from a Google Sheets export maintained by hlswan(hiya!) and (hopefully) will eventually power a web frontend. Google sheet link:https://docs.google.com/spreadsheets/d/1zgmOYJBULyHLqs9lGB6-cO4QhRoJdgOpd9WpUWpILYo/edit?usp=sharing

## Data

Each run includes: in-game time, re-timed time, date, seed, and a link to the run video or Speedrun.com submission. The top ~28 runs additionally include split data covering ow type, nether split data, fort and bastion strats, nav, and end fight details. There's a lot. 