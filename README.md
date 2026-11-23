# Super6-ai

Research and evaluation for Sky Sports Super 6. Round 17 is the user-provided baseline of **7 points**, with one exact score and one additional correct result. Its season and fixtures remain unconfirmed.

## Run locally

Python 3.11 or later. The research and report commands use the standard library.

```sh
python -m unittest discover -s tests -v
python -m super6.report
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

Open http://127.0.0.1:8000. Rebuild after changing the archive. Report output and the snapshot directory can be overridden with `--output` and `--snapshots`. For the 360 px browser regression test, install Playwright with `npm install --no-save --ignore-scripts playwright@1.62.1`, then run `npx playwright install chromium` and `node tests/dashboard.cjs`. The browser test uses an isolated synthetic round beside the sourced historical round.

## Capture an upcoming round

1. Open the official Super 6 round page or Sky Sports announcement before entries close. Copy the season and round identity, six official pairings and advertised entry deadline. Cross-check kickoff times and preserve the source. Record the deadline and its source in `deadline_basis`.
2. Use the [round archive](data/rounds.json) as the field reference. Prepare a single round object with `id`, `deadline`, `deadline_basis`, `official`, and six `fixtures` with `home`, `away`, `kickoff` and optional `research`. Use ISO 8601 timestamps with UTC offsets.
3. For each evidence item record `url`, `available_at`, `note`, `captured_at` and `source_sha256`. Retain the original source bytes privately under `evidence-local/<sha256>`. Use a timestamped provider export, dated article or readable round capture. Mark the capture time when it is saved. An historical reconstruction captured after the deadline also needs a separate `archive_url` and `archived_at` proving the exact source state existed before the deadline. If a value is derived, record the covered matches, provider, calculation window and cutoff.
4. Check coverage, freeze the inputs and import. The freeze command compares each retained source file against its hash. The report requires the matching frozen pre-match record before using the xG-and-market model. Keep snapshots in version control where permitted. Keep raw sources in a private evidence store if provider terms restrict redistribution.

```sh
python -m super6.capture /path/to/round.json
python -m super6.capture /path/to/round.json --freeze --evidence-directory evidence-local
python -m super6.import_round /path/to/round.json
python -m super6.report
```

Reviewers are responsible for confirming that each captured source actually supports the value, publication time and official slate. Hashes protect snapshot integrity after capture. A hash alone cannot establish what a publisher made public at a particular time. A freeze contains only pre-match inputs. Adding results leaves the existing pre-match snapshot valid.

### Evidence checklist

| Research key | Capture and suggested source |
| --- | --- |
| `form`, `venue_form` | Recent completed matches and home/away splits from league results or a dated data export. Document the competition and window. |
| `xg`, `xga` | Venue-specific per-match expected goals for and against. Add numeric `home` and `away` fields to each. Use one provider and consistent windows for the fixture. |
| `injuries`, `suspensions`, `team_news` | Club press conferences, club previews, competition disciplinary notices or dated Sky Sports team news. Distinguish confirmed absences from doubtful players. Leave unsupported entries absent. |
| `opposition`, `rest` | Opposition strength from a pre-deadline rating or table and rest calculated from time since the previous competitive match. |
| `odds` | Timestamped pre-deadline 1X2 prices. Record bookmaker and `decimal` in home/draw/away order. |

A result has final status, full-time `score` in home/away order, and a dated source. Add it with `--replace`. An optional `first_goal` per result has the first goal minute and Sky match-report evidence. Prefer an official round-level `golden_goal` when available. If all six results include enough goal timing evidence, the report can use the minimum elapsed match minute from the match reports as a labeled proxy. Stoppage time beyond minute 90 is outside this model. Keep results without reliable timing eligible for score evaluation and out of the Golden Goal evaluation.

## Benchmark with genuine match results

The venue benchmark takes the last five finished home or away league matches per team before the round deadline. For dated CSV rows it conservatively treats the result as available at the next midnight in London time. It reads the full-time score fields and ignores every odds column. It records the CSV URL and file hash alongside the selected rows. Review team aliases and competition coverage before reuse.

Download the relevant [Football-Data season files](https://www.football-data.co.uk/englandm/index.php) and run the command below against a single round record. The checked-in archive already contains the resulting records for 2020–21 Round 1.

```sh
python -m super6.venue /path/to/round.json \
  --source /path/to/E0.csv https://www.football-data.co.uk/mmz4281/1920/E0.csv \
  --source /path/to/E1.csv https://www.football-data.co.uk/mmz4281/1920/E1.csv \
  --aliases data/football-data-aliases.json > /tmp/round-with-venue-history.json
python -m super6.import_round /tmp/round-with-venue-history.json --replace
```

## Backtest and data availability

- The main model fits independent Poisson goal rates to venue xG/xGA and normalizes the bookmaker margin out of 1X2 odds. The other research categories provide review context. A round needs a matching frozen snapshot and all ten categories for all six fixtures.
- The fixed Poisson benchmark uses rates 1.5 at home and 1.1 away. The venue-goals benchmark pools goals scored and opponent goals conceded, shrinking toward those fixed rates by two prior matches. It does not adjust for changes in division, opponent strength or squad turnover.
- All methods select scores for expected Super 6 points using the 5/2/0 scoring rule. The report uses exact convolution for the model's 13+ probability and retains the 100,000-trial estimate as a check. These probabilities assume independent fixtures. Golden Goal uses the conditional median of the minimum of six constant-rate match clocks.
- The historical report includes exact-score accuracy, observed 13+ rates, mean forecast probabilities, Brier scores, calibration buckets, and Golden Goal error. The like-for-like comparison uses only rounds with all three methods and confirmed results. The 2020–21 sample has one completed benchmark round and zero completed main-model rounds.
- No documented public official Super 6 API was verified. Round and deadline collection still needs a human reviewer. [Hudl StatsBomb Open Data](https://github.com/hudl/open-data) covers selected competitions and seasons. Complete point-in-time xG for every Super 6 fixture remains unverified. [The Odds API](https://the-odds-api.com/liveapi/guides/v4/#historical-odds) requires a paid plan for timestamped historical snapshots. A bookmaker snapshot captured before entry closes can be used for an upcoming round where terms permit. Historical closing odds cannot substitute for deadline odds on staggered slates.
