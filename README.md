# Super6-ai

Research and evaluation for Sky Sports Super 6. Round 17 is the user-provided baseline of **7 points** from one exact score and one additional correct result. The baseline has no confirmed season or fixture list.

## Run locally

Python 3.11 or later is required. There are no third-party Python dependencies.

```sh
python -m unittest discover -s tests -v
python -m super6.report
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

Open http://127.0.0.1:8000. The static dashboard loads its data from `dist/report.json`. Rebuild whenever the archive changes. Use `python -m super6.report --help` for alternative input and output paths.

## Add a round

1. Find an official Super 6 round page or a Sky Sports article explicitly naming all six selections. Cross-check team order, kickoff times, and the round entry deadline. Record the deadline's basis if it is inferred from the earliest scheduled kickoff.
2. Review the evidence for each fixture. Store source URLs, publication or snapshot timestamps with offsets, and concise notes. Use archived or dated sources for historical work. Live odds, dynamic form tables, and retrospective reports can change or include later information.
3. Add full-time results after the matches. Record an official Golden Goal when available.
4. Save the reviewed JSON and import it with `python -m super6.import_round /path/to/reviewed-round.json`. Use `--replace` when adding evidence to an existing round. Keep IDs unique across seasons.

The import checks structure, official source domains and timing. Reviewing the linked source and confirming that it supports each value is a manual step. The checked-in [round archive](data/rounds.json) shows actual input records. The 2020–21 Round 1 slate and all six results are sourced to Sky Sports. The research entered for that round is partial.

### Round record

| Field | Format |
| --- | --- |
| `id` | Unique season and round label |
| `deadline` | ISO 8601 timestamp with UTC offset |
| `official` | Evidence that identifies the official six fixtures |
| `fixtures` | Exactly six objects, each with `home`, `away`, `kickoff` and optional `research` and `result` |
| `golden_goal` | Optional official evidence with `minute` (1–90, or null if Sky records no goal) |

An evidence object has `url` (HTTPS), `available_at` (timezone-aware) and `note`. A result adds `score`, a two-item array in home/away order. For historic research, use the proven point at which the stated values were available. If a value is derived, document its input matches, window, and cutoff in the note and cite a snapshot or timestamped data that establishes those inputs.

| Research key | Capture |
| --- | --- |
| `form` | Recent results, competition and window |
| `venue_form` | Home record for the home side and away record for the away side |
| `xg`, `xga` | Home and away teams' venue-specific per-match expected goals for and against, respectively. Each record adds numeric `home` and `away` fields. Record the provider and window. |
| `injuries`, `suspensions` | Sourced availability and uncertainty for each side |
| `opposition` | Strength of the teams faced over the form window, measured using a rating or standings snapshot available at the cutoff |
| `rest` | Time since each team's previous competitive match, with source and calculation |
| `odds` | A timestamped bookmaker 1X2 snapshot. Add `decimal` in home/draw/away order and record the bookmaker. |

Evidence after the round deadline or at/after kickoff cannot be used. Incomplete evidence can be stored incrementally. All nine categories must be present for every fixture before the report generates predictions. Leave unverified fields absent. The baseline stays outside model performance.

## Model and backtest

- The model uses independent Poisson goal counts. It averages each team's venue-specific xG with the opposition's xGA, then adjusts both rates using margin-normalized 1X2 probabilities and a fixed penalty for moving away from the xG prior. The calibration penalty is a modeling choice that has yet to be validated. The other research categories provide review context.
- Each score pick maximizes expected Super 6 points, giving five points for an exact score and two for an additional correct result. This objective can differ from maximizing the chance of reaching 13 points.
- The seeded Monte Carlo simulation draws each fixture's 0, 2 or 5-point outcome from its modeled probabilities across 100,000 independent rounds. It returns mean points, the full points distribution and the share at 13 points or above. Match dependencies and parameter uncertainty are outside this model.
- Golden Goal uses the minimum elapsed match minute among six independent constant-rate goal processes over 90 minutes. The prediction is the conditional median when a goal occurs. The report includes the chance of a goalless round. Stoppage time is outside this approximation.
- The backtest uses the same fixed model on each round's pre-deadline evidence and scores picks against confirmed full-time results. It reports mean points, the 13+ hit rate and Brier score, and Golden Goal mean absolute error when verified outcomes are present. The included archive currently yields zero scored backtests. Automated tests exercise prediction, simulation and evaluation on isolated synthetic inputs.

[Sky Sports round announcement and Golden Goal description](https://www.skysports.com/football/news/18871/12061082/super-6-the-gbp1m-jackpot-returns-can-you-imagine)
