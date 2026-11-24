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
- The historical report includes exact-score accuracy, observed 13+ rates, mean forecast probabilities, Brier scores, calibration buckets, and Golden Goal error. The like-for-like comparison uses only rounds with all three methods and confirmed results. The archive has two completed benchmark rounds and zero completed main-model rounds.
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

The dashboard compares the expected-points six-pick combination with the most likely exact-score combination and displays the independent probability of all six exact scores. The schedule-aware Golden Goal calculation uses only matches active at each elapsed time. The dashboard also shows the lowest-match-clock estimate across all six when it differs. The historical Golden Goal metric compares match-clock minutes. The archive preserves the Round 17 baseline and the two verified historical slates. Round 18 can enter a compatible historical cohort when its final results and the evidence required by that protocol are available.

## Stage 5 historical strategy backtest

Run the reproducible historical study independently or build the performance dashboard at the same cutoff.

```sh
python -m super6.backtest --as-of 2026-11-23T00:00:00Z
python -m super6.report --backtest-as-of 2026-11-23T00:00:00Z
```

The archive contains two complete **real historical reconstructions** for the venue-results model. Both have a dated official Sky slate and entry deadline, six final Sky results, and five earlier same-venue league scores per side. Those scores are reconstructed from match dates and assigned the next local midnight as a conservative availability bound. The archive records the source URL and file digest for each input. This establishes which match facts could be known by the cutoff. It does not recreate an archived provider response or prove that anyone submitted the model's picks at the time. Later odds, xG and team news are excluded. The benchmark forecasts are also retrospective. The full xG-and-market model has zero complete historical rounds. Round 17 stays outside the study because its official slate and season are unconfirmed. The live Round 18 record remains unchanged.

- [2020–21 Round 1 preview and deadline](https://www.skysports.com/football/news/12040/12068960/super-6-lb1m-preview-one-day-to-go)
- [2021–22 Round 1 slate and deadline](https://www.skysports.com/football/news/12371699/super-6-championship-opening-day-lb1m-up-for-grabs-on-saturday) · [Final results](https://www.skysports.com/football/news/12375402/championship-highlights-and-round-up-hull-blackburn-luton-win)
- [Football-Data 2020–21 Championship](https://www.football-data.co.uk/mmz4281/2021/E1.csv) · [League One](https://www.football-data.co.uk/mmz4281/2021/E2.csv). These free files provide the new round's earlier matches, including the promoted sides. Recreate the venue-history rows with `super6.venue`, the linked files and the checked-in aliases. The importer reads score columns only. General schedules and tip sites cannot establish the Sky slate. Historical odds without a proven pre-deadline time are outside the study.

The study sorts by entry deadline and excludes rounds without six published final results, dated Sky deadline evidence or sufficient prior venue history. Correct-result accuracy includes exact scores. It convolves the six independent score distributions under 5/2/0 scoring. For the 13+ objective, the strongest exact score within each result category dominates all other scores of that category. Searching the 729 combinations gives an exact optimum under the model. The two benchmarks are a fixed-rate Poisson forecast and an always-1–1 policy. The draw policy's probability is evaluated with the same venue model as the three strategies. Calibration bands show sample sizes, mean probability and observed frequency. No production recalibration is fitted.

The Dixon–Coles experiment fits only the low-score dependence parameter by likelihood on prior eligible rounds whose six results were published strictly before the held-out round's deadline. Rates stay fixed. It searches a predeclared grid from −0.120 to +0.120 and compares out-of-sample exact-score log loss, points and 13+ Brier score with the original distribution on the same held-out rounds. A fit at the grid cap and just one held-out round make this exploratory. The live forecast does not use the fitted adjustment.

| Policy | Average points | Exact-score accuracy | Correct-result accuracy | Mean 13+ forecast | Observed 13+ |
| --- | ---: | ---: | ---: | ---: | ---: |
| Most likely exact scores | 2.5 | 8.3% | 8.3% | 7.2% | 0/2 |
| Max expected points | 6.5 | 8.3% | 41.7% | 12.0% | 0/2 |
| Max chance of 13+ | 6.5 | 8.3% | 41.7% | 12.0% | 0/2 |
| Fixed-rate Poisson | 6.5 | 8.3% | 41.7% | 11.3% | 0/2 |
| Always 1–1 | 7.5 | 25.0% | 25.0% | 3.6% | 1/2 |

These small-sample measurements do not establish a superior strategy. The checked-in historical rounds are real. Simulated probabilities, fabricated unit-test cases and the synthetic browser fixture do not add rounds to the performance sample.

## Stage 6 historical archive expansion

The goals-only study now includes **20 complete historical rounds**, with **18 additions**. The new rows cover 2018–19, 2019–20, 2020–21, 2022–23, 2023–24 and 2024–25. The two earlier records also contribute 2021–22. The main archive and frozen Round 18 record remain intact.

- [Reviewed Sky slates and source metadata](data/archive-review.json) contains links, publisher timestamps and hashes of the retrieved evidence. Match times come from Football-Data where available and from separately sourced kickoff records otherwise.
- [Compiled archive](data/archive-rounds.json) contains the six selected fixtures, verified cutoff, final scores, and five earlier same-venue league results per side. Football-Data CSVs have retrieval times and checksums in the review manifest. Their result availability is bounded by the next UK midnight. The goals-only model reads score data and never reads the odds or xG columns.
- [Incomplete leads](data/archive-candidates.json) records 82 listings from the [independent results index](https://super6predictor.co.uk/scores-archive) and 13 partial primary-source leads. These entries cannot enter the backtest. The official [Super 6 results route](https://super6.skysports.com/schedule) redirected to sign-in during review.

### Source quality

| Class | Rounds | Evidence |
| --- | ---: | --- |
| Sky advertised deadline | 9 | Sky named the slate and gave the round deadline in dated evidence. |
| Sky first-kickoff rule | 8 | Dated Sky slate, [Sky’s published first-kickoff rule](https://www.skysports.com/football/news/11095/11158298/250k-jackpot-landed-in-super-6), and verified match kickoff times. |
| Sky revised preview | 3 | Sky’s original publisher timestamp precedes the cutoff. The captured preview explicitly states the historical slate and deadline, and its publisher modification time is later. The exact text available before the deadline cannot be reproduced. Form uses independently sourced earlier scores. |
| Incomplete archive lead | 95 | One or more required facts remain unverified. |

To regenerate the compiled archive, place the published [Football-Data score files](https://www.football-data.co.uk/englandm/index.php) under a local directory using the season and division keys in the review manifest, for example `1819/E0.csv`. Regeneration checks the recorded hashes and fails when an upstream file has changed. The public article captures and bulk football CSVs are kept out of the repository. The build itself needs no network access.

```sh
python -m super6.archive /path/to/football-data-files > /tmp/archive-rounds.json
cmp data/archive-rounds.json /tmp/archive-rounds.json
python -m super6.backtest --as-of 2026-11-23T00:00:00Z
python -m super6.backtest --as-of 2026-11-23T00:00:00Z --exclude-revised
```

| Strategy | Average points | Exact-score accuracy | Correct-result accuracy | Mean 13+ forecast | Observed 13+ |
| --- | ---: | ---: | ---: | ---: | ---: |
| Most likely exact scores | 5.80 | 10.0% | 33.3% | 9.1% | 1/20 |
| Max expected points | 6.80 | 8.3% | 44.2% | 14.5% | 2/20 |
| Max chance of 13+ | 6.80 | 8.3% | 44.2% | 14.5% | 2/20 |
| Fixed-rate Poisson | 7.10 | 10.0% | 44.2% | 11.3% | 2/20 |
| Always 1–1 | 3.95 | 9.2% | 19.2% | 3.4% | 1/20 |

Excluding the three revised previews leaves 17 rounds. The venue strategies average 6.76 points and fixed Poisson averages 7.65 in that subset. Across 19 chronological Dixon–Coles holdouts, mean exact-score log loss changes from 3.120 to 3.114, and mean scored points stay at 6.68. No production parameter changes follow from these results. The sample has zero complete historical rounds for the xG-and-market model.

## Stage 7 model performance investigation

```bash
python -m super6.performance --as-of 2026-11-23T00:00:00Z > /tmp/super6-performance.json
```

The audit emits all six actual scores and all three picks with fixture points for every round. It includes each model's goal rates and home/draw/away probabilities, the age and points per game of each side's venue history, and summaries for the full archive and the sensitivity sample excluding the three revised previews. It reuses the Stage 6 chronological forecasts without fitting any adjustment to these rounds. The optimized strategies chose identical scores in all 120 fixtures. The venue picks differed from fixed-rate Poisson on 68 of 120 fixtures and 56 of 102 in the sensitivity sample.

| Rounds | Entry | Actual points | Model-expected points | Exact | Correct result incl. exact | Predicted 13+ | Observed 13+ | 13+ Brier |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20 | Either optimized strategy | 6.80 | 8.20 | 8.3% | 44.2% | 14.5% | 10.0% | 0.0916 |
| 20 | Fixed-rate Poisson | 7.10 | 7.58 | 10.0% | 44.2% | 11.3% | 10.0% | 0.0902 |
| 17 | Either optimized strategy | 6.76 | 8.21 | 8.8% | 43.1% | 14.6% | 11.8% | 0.1043 |
| 17 | Fixed-rate Poisson | 7.65 | 7.58 | 11.8% | 46.1% | 11.3% | 11.8% | 0.1038 |

The optimized strategies finished ahead, tied and behind on 7, 3 and 10 rounds in the full sample and 4, 3 and 10 in the sensitivity sample. Paired differences below are optimized minus fixed. The 95% percentile intervals use 10,000 seeded resamples of entire rounds, keeping the strategies and all six matches paired. They describe sampling variability under exchangeable rounds and do not account for the archive's selection or potential dependence across slates involving the same teams.

| Metric | 20 rounds | 17 rounds |
| --- | ---: | ---: |
| Actual points per round | −0.30 [−1.70, +1.15] | −0.88 [−2.29, +0.71] |
| Exact-score accuracy, percentage points | −1.7 [−6.7, +3.3] | −2.9 [−7.8, +2.0] |
| Correct-result accuracy, percentage points | 0.0 [−7.5, +7.5] | −2.9 [−10.8, +4.9] |
| 13+ Brier score | +0.0014 [−0.0113, +0.0103] | +0.0005 [−0.0144, +0.0109] |

Both models cleared 13 on the same two Sky rounds (3 November 2018 and 4 May 2019). Resampling those slates gives a zero-width interval for the hit-rate difference because there are no discordant hits to resample. There is too little information to establish comparative hit rates in future rounds. The venue model forecast roughly three percentage points more 13+ risk in both samples.

- **Home and away wins.** The venue model gained 32 points on away wins and lost 38 on home wins, with corresponding gains of 21 and losses of 36 in the sensitivity sample. It nailed West Ham 0–1 Tottenham, gaining five points on the fixed 1–0 pick. Its 0–1 picks for Birmingham–Leeds and Crystal Palace–Southampton and its 1–2 pick for Tottenham–Man United each cost five points when the home team won 1–0. Everton 0–1 Fulham added five points to the venue side in the revised-preview group. The five-match away points-per-game bands offered no consistent net advantage over the fixed model, and they do not adjust for strength of opposition.
- **Goals and draws.** In 20 rounds the observed home and away means were 1.46 and 1.39 goals. The venue model forecast 1.54 and 1.21, and the fixed model used 1.50 and 1.10. In the 17-round sample the corresponding pairs were 1.44 and 1.35 observed, 1.55 and 1.20 venue, and 1.50 and 1.10 fixed. Average total goals were 2.85 and 2.79 in the two samples. The venue model forecast about 2.75 in both, and the fixed model forecast 2.60. Both forecast too few away goals and more draws than observed. The full-sample draw probabilities averaged 24.3% venue and 25.8% fixed, with 19.2% observed. In the sensitivity sample those figures were 24.3%, 25.8% and 19.6%. Neither entry strategy picked a draw, so draws contributed zero to the scoring difference.
- **Availability and recency.** All eligible fixtures had five pre-deadline venue results per side. There is no scored cohort for missing form. At least one side's newest venue result was over 45 days old in 42 of 120 fixtures and 24 of 102 sensitivity fixtures. The venue strategy's point difference on those fixtures flipped from +7 to −2 after excluding the revised previews. This provides no basis for a new recency cutoff.

Keep the fixed-rate benchmark and current forecasts. The points and Brier intervals span zero. Any candidate change to rates, opponent adjustment or form weighting needs rules set before evaluation and a separate, later chronological test cohort.

## Stage 8 prospective workflow

Use the official Sky Super 6 round card or a dated Sky preview that explicitly identifies all six selected fixtures and the entry deadline. Review the captured page and enter its excerpt, availability time and confirmation time in the round manifest. Use the dashboard capture form as a starting point. Add a kickoff source for each fixture. This review is required for league and Champions League rounds alike.

```sh
python -m super6.live collect 'https://super6.skysports.com/' --sources evidence-local
python -m super6.live freeze reviewed-round.json --sources evidence-local
python -m super6.live settle reviewed-results.json --round-id ROUND_ID --sources evidence-local
```

Collect each available free research source with the same command. Record the returned capture time and digest alongside the verified publication time, notes and any structured input. For form feeds, use the existing `super6.research` normalizer to derive profiles from the saved bytes using the returned capture time. Leave unavailable or unverified categories absent. If the market model lacks its required fresh research, the recommendation uses recent form when available or the fixed-rate benchmark. The ledger records which model was used. Collection has a bounded timeout and one retry per source. Captured pages require review because a successful download alone does not establish the slate, published odds, availability, or a final score.

Freeze writes one complete forecast per round identifier and checks the cutoff again at publication. Commit the ledger promptly to retain an independent record of when it was published. Settlement requires six final Sky score records keyed by the frozen fixture IDs, each with a captured source digest. It scores the stored picks and links the settlement to the exact forecast bytes. Use the same stable round ID throughout. The workflow has no entry submission step.

### Registered experiments

The [experiment protocol](data/experiment-protocol.json) reserves rounds with deadlines from 25 November 2026 onward. The Stage 7 archive can seed the Dixon–Coles fit. It contributes zero evaluation rounds. The five candidates are scored against the venue and fixed-rate baselines on the same eligible rounds. Before the registered minimum of 20 paired holdouts, the report shows enrollment counts and withholds comparative scores.

```sh
python -m super6.experiments --as-of 2026-11-24T12:00:00Z
```

For future evaluation, pass the verified archive feeds and review manifest with `--feeds` and `--review`. The `--competitions` JSON maps each round ID to its home-team names and each name to the reviewed result-feed URL for that fixture's competition and season. Earlier matches in those feeds establish competition goal rates and opponents’ points per game. Results whose availability is at or after the deadline are excluded before computing either feature. A round without full context stays outside the paired cohort. These candidates use reconstructable venue scores. Evaluating them against the market-blended model requires a separate protocol and comparable evidence.
