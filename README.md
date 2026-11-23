# Super6-ai

Research and evaluation for Sky Sports Super 6. Round 17 is the user-provided baseline of **7 points**, with one exact score and one additional correct result. Its season and fixtures remain unconfirmed.

## Run locally

Python 3.11 or later. The research and report commands use the standard library.

```sh
python -m unittest discover -s tests -v
python -m super6.report
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

Open http://127.0.0.1:8000. Rebuild after changing the archive. Report output and the snapshot directory can be overridden with `--output` and `--snapshots`. For the iPhone, iPad and Android viewport regression tests, install Playwright with `npm install --no-save --ignore-scripts playwright@1.62.1`, then run `npx playwright install chromium webkit` and `node tests/dashboard.cjs`. The browser tests use an isolated synthetic round beside the sourced historical and upcoming rounds.

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

## Free-data workflow and Round 18

The official Sky home card confirmed **2026–27 Round 18** and its entry deadline of **24 November 2026 at 20:00 GMT**. Its six pairings are stored in `data/rounds.json`. The three Tuesday matches and three Wednesday matches were cross-checked against [UEFA's fixtures and results](https://www.uefa.com/uefachampionsleague/news/02a8-2174c9e9019d-f909a77bd77a-1000--2026-27-champions-league-all-the-league-phase-fixtures-a/). IDs prefixed with `sky-2026-27-r18-` are local identifiers for the positions on the Sky card. The dashboard selects an upcoming round when available. Its **Capture** form can load the selected round or accept a new slate, attach timestamped manual evidence, save a draft in browser storage, and export one round as JSON for import. This browser-local save makes no server request. The API and CSV never select Sky fixtures.

| Source | Free coverage and use |
| --- | --- |
| [football-data.org terms](https://www.football-data.org/client/register), [coverage](https://www.football-data.org/coverage), [API v4 policy](https://docs.football-data.org/general/v4/policies.html) | Registered free key for this application. The free tier lists 12 competitions including Champions League, basic fixtures/results/tables and 10 requests a minute. The CLI makes one request per invocation. Use a private environment variable, throttle repeated calls and keep captures private. The terms require visible attribution and restrict reuse after account cancellation. An anonymous Champions League request returned 403. The authenticated adapter was tested against sample responses and needs the operator's key for a live run. |
| [open-matchday](https://github.com/oladeeayo/open-matchday), [data rights](https://github.com/oladeeayo/open-matchday/blob/master/DISCLAIMER.md), [dictionary](https://github.com/oladeeayo/open-matchday/blob/master/DATA_DICTIONARY.md) | Published CSV downloads worked for 2026–27 Champions League fixtures and results. Use the published files for non-commercial research, credit open-matchday and applicable upstream publishers, and review upstream rights before redistribution. The project keeps the capture hash, references and derived form summaries. Its bulk data is not included. Download the published CSV rather than running the upstream collectors. |
| [Understat](https://understat.com/league/EPL/2026) | The public page returned a maintenance message. Public xG tables and built-in exports have been reported for supported domestic leagues. An official API, permission for automated collection, and Champions League coverage were not verified. If an authorised export is available, capture it manually and document the dates, provider and calculation window before entering xG/xGA. |
| Dated team and market evidence | Manually capture club announcements, disciplinary notices, line-up previews and bookmaker pages. Round 18 has no verified pre-deadline evidence for injuries, suspensions, likely line-ups, xG/xGA or market odds in the repository. |

To prepare team form, capture a result feed before the Sky deadline and enrich the confirmed Sky record. Date-only CSV results count from the following local midnight. Store the raw source privately if allowed. Capture timestamps reflect actual retrieval, including any result delay in the provider feed. Do not backdate a new capture to evaluate an old round.

```sh
# A registered free key is needed for the official API option.
python -m super6.research api CL 2026-09-01 2026-11-23 > /tmp/cl-capture.json
# Add --fixtures for general match identifiers and scheduled kickoffs as a cross-check.
# Keyless option after downloading the published CSV.
python -m super6.research csv /path/to/results_2627.csv \
  https://raw.githubusercontent.com/oladeeayo/open-matchday/master/data/UEFA_1_champions-league/results_2627.csv \
  CL --observed-at ACTUAL_CAPTURE_TIMESTAMP > /tmp/cl-capture.json
python -m super6.research enrich /path/to/super6-round.json /tmp/cl-capture.json \
  --aliases data/open-matchday-aliases.json > /tmp/researched-round.json
python -m super6.import_round /tmp/researched-round.json
python -m super6.report
```

Pass extra capture paths from the same provider for a mixed slate. The research window uses up to six matches per team and reports W/D/L, goals, clean sheets, matching-venue splits, and opponent points per game in the captured competition. Empty samples are flagged and cross-competition PPG is descriptive. Forecasts use a recent-goals Poisson model when each side has at least three recent results and its latest result is under 45 days old at the cutoff. Matching-venue observations get an extra weight and six prior observations shrink the estimated rates toward 1.5 and 1.1. Validated xG/xGA can be used on this path when both are fresh and part of a frozen evidence snapshot. The goals-only estimate is **provisional**, including Round 18's four Champions League games per team. Outcomes and probability calibration are unverified for this model.

The dashboard compares the expected-points six-pick combination with the most likely exact-score combination and displays the independent probability of all six exact scores. The schedule-aware Golden Goal calculation uses only matches active at each elapsed time. The dashboard also shows the lowest-match-clock estimate across all six when it differs. The historical Golden Goal metric compares match-clock minutes. The archive preserves the Round 17 baseline and the one earlier verified historical slate. Round 18 will only enter backtesting once all six results have been recorded with final evidence.
