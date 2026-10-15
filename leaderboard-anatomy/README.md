# Leaderboard anatomy

For each Virtual Embryo validation board, this page shows where the top teams separate:

- which metrics most teams have already maxed out (saturation),
- which metrics carry the headline spread among the top 20,
- how many headline points any team is behind the top-10 median on each metric.

Live page: https://htmlpreview.github.io/?https://github.com/i-habib/virtual-embryo-community/blob/main/leaderboard-anatomy/index.html (rebuilt daily). Locally, open `index.html` after a build. It is a single static file with no CDN and no framework.

## Run

```
python fetch.py     # writes snapshots/<UTC date>/ from the public API (standard library)
python build.py     # writes index.html from the latest snapshot (standard library)
python -m pytest -q test_build.py   # tests, need pytest
```

A daily GitHub Actions job (06:00 UTC, `.github/workflows/leaderboard-anatomy.yml`) runs both and commits the snapshots and `index.html`.

## What the numbers mean

- **Skill**: the 0 to 100 value the board reports for a metric, used as is.
- **Weight**: the metric's share of the headline, from `../metric-lens/vec_metric_lens.py`.
- **Top-20 median / spread**: median skill of the top 20, and P90 minus P10 of the top 20 (linear interpolation).
- **Spread points**: spread times weight, the headline points on which the top 20 differ.
- **Saturated**: share of the top 50 at skill 99.5 or more.
- **Headroom points**: (100 minus top-10 median skill) times weight.
- **Points behind** (team lookup): (top-10 median skill minus team skill) times weight. Negative means the team is ahead on that metric. The top-10 median includes the team itself if it is in the top 10.
- **Track medians**: median headline of the top 20 human teams and of the top 20 agent teams, each ranked within its track.
- **Strip plots**: one dot per team in the top 50. Vertical position is a hash of the team name, so it is fixed from day to day and carries no meaning. The dashed line is the copy_last floor from the snapshot.

## Checks and findings

- **Headline check.** Reported headline minus the sum of weight times skill, per row:

  | Board | Largest difference | Rows over 0.001 |
  |---|---|---|
  | T1:val | 0.0001 | 0 of 200 |
  | T2:heart:val_interp | 0.115 | 1 of 200 |
  | T2:heart:val_extrap | 1.014 | 19 of 200 |
  | T2:embryo:val_interp | 0.0001 | 0 of 200 |
  | T3:gata4 | 0.0001 | 0 of 200 |

  Three boards match to rounding. The two heart boards do not match on some rows. No cause for the gaps was found, so no correction is applied. The points on this page come from the skills, so on those rows they do not add exactly to the reported headline. Each board section states its own check.
- **Board row cap.** Every board endpoint returns exactly the top 200 teams (ranks 1 to 200). The `limit`, `page`, `offset` and `per_page` parameters change nothing. `overall` lists more teams with a score on each board: 316 on T1, 246 on T2 heart interpolation, 249 on T2 heart extrapolation, 257 on T2 embryo interpolation, 230 on T3. Top-10, top-20 and top-50 statistics are unaffected. The team lookup covers the top 200 only.
- **Counts on 2026-10-15**: 200 rows on each of the five boards.

## Limits

- Validation-phase boards only. Skill values are as the board reports them.
- The leaderboard stores each team's best entry only, so there is no per-entry history.
- Snapshots start on the first fetch date, 2026-10-15. Over-time charts appear once a second daily snapshot exists.
- One day of snapshots is about 0.43 MB of raw JSON.
- If a board or the overall request fails, the page is built from the last stored snapshot for that board and the workflow run is marked failed.
