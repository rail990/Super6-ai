const byId = id => document.getElementById(id);
const percent = value => (100 * value).toFixed(1) + '%';
const rarePercent = value => (100 * value).toPrecision(3) + '%';
const score = value => value.join('–');
const date = value => new Date(value).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';

function add(parent, tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value;
  if (className) element.className = className;
  parent.append(element);
  return element;
}

function metric(parent, label, value) {
  const card = add(parent, 'div', '', 'metric');
  add(card, 'strong', value);
  add(card, 'span', label);
}

function source(parent, label, record) {
  const link = add(parent, 'a', label);
  try {
    const url = new URL(record.url);
    if (url.protocol === 'https:' && !url.username && !url.password && !url.port) link.href = url.href;
  } catch {
    link.replaceWith(document.createTextNode(label));
  }
  add(parent, 'p', date(record.available_at) + ' · ' + record.note);
}

const modelNames = {xg_market: 'xG and market model', venue_goals: 'Venue-goals benchmark',
  fixed_poisson: 'Fixed Poisson benchmark', recent_form: 'Recent results model'};

function showRound(row, model = row?.recommended_model ?? 'xg_market') {
  const container = byId('round-content');
  container.replaceChildren();
  if (!row) {
    add(container, 'p', 'No verified rounds are available.');
    return;
  }
  const { round } = row;
  captureSelection(round);
  const { prediction, evaluation } = model === 'xg_market' ? row : row.benchmarks[model];
  add(container, 'p', 'Entry deadline · ' + date(round.deadline));
  if (row.frozen_at) {
    add(container, 'p', 'Prospective forecast frozen · ' + date(row.frozen_at), 'status');
    add(container, 'p', 'Recommendation · ' + modelNames[row.recommended_model]);
    add(container, 'p', row.golden_goal_rule);
  }
  source(container, 'Official fixture evidence', round.official);
  if (round.official.confirmed_at) add(container, 'p', 'Sky slate confirmed · ' + date(round.official.confirmed_at));
  const modelLabel = add(container, 'label', 'Forecast ');
  const select = add(modelLabel, 'select', '');
  const models = [...Object.keys(row.benchmarks)];
  if (row.prediction || !row.frozen_at) models.unshift('xg_market');
  for (const name of models) {
    const option = add(select, 'option', modelNames[name]);
    option.value = name;
    option.selected = name === model;
  }
  select.addEventListener('change', () => {
    showRound(row, select.value);
    byId('round-content').querySelector('select').focus();
  });
  if (prediction) {
    add(container, 'p', model === 'xg_market' && row.recommended_model === 'xg_market' ?
      'Forecast based on verified pre-deadline evidence' : model === 'recent_form' ?
      'Provisional forecast · limited pre-match evidence' : 'Benchmark forecast', 'status');
    const metrics = add(container, 'div', '', 'metrics');
    metric(metrics, 'Expected points', prediction.expected_points.toFixed(2));
    metric(metrics, 'Chance of 13+ points', percent(prediction.probability_13_plus));
    metric(metrics, 'Chance of all six exact scores', rarePercent(prediction.probability_all_exact));
    const schedule = prediction.golden_goal.schedule;
    metric(metrics, 'Golden Goal · chronological estimate', 'Minute ' +
      (schedule?.recommended_minute ?? prediction.golden_goal.minute));
    if (schedule && schedule.kickoff_for_recommendation !== schedule.first_kickoff) {
      add(container, 'p', 'Chronological recommendation refers to the kickoff at ' +
        date(schedule.kickoff_for_recommendation) + '.');
    }
    if (schedule && schedule.recommended_minute !== prediction.golden_goal.minute) {
      add(container, 'p', 'If Sky uses the lowest match-clock minute across both days, the estimate is minute ' +
        prediction.golden_goal.minute + '.');
    }
    const alternative = add(container, 'details', '');
    add(alternative, 'summary', 'Compare the most likely exact-score combination');
    const modal = prediction.modal_combination;
    add(alternative, 'p', modal.scores.map(score).join(' · '));
    add(alternative, 'p', modal.expected_points.toFixed(2) + ' expected points · ' +
      percent(modal.probability_13_plus) + ' chance of 13+ · ' +
      rarePercent(modal.probability_all_exact) + ' chance of all six exact scores');
    if (evaluation) metric(metrics, 'Actual points', evaluation.points);
    add(container, 'p', prediction.trials.toLocaleString() + ' simulations · No-goal probability ' +
        percent(prediction.golden_goal.no_goal));
  } else {
    add(container, 'p', 'Insufficient data for this forecast.', 'status');
    add(container, 'p', row.missing_research.length ?
      'Model prediction pending complete pre-deadline evidence.' : 'Model prediction pending a frozen evidence snapshot.');
  }
  if (row.quality_flags.length && round.official.confirmed_at) {
    const flags = add(container, 'details', '');
    add(flags, 'summary', 'Research coverage and freshness');
    const list = add(flags, 'ul', '');
    row.quality_flags.forEach(flag => add(list, 'li', flag));
  }
  if (round.golden_goal) {
    const goal = round.golden_goal;
    source(container, 'Official Golden Goal · ' + (goal.minute ?? 'No goal'), goal);
  } else if (row.derived_goal != null) {
    add(container, 'p', 'First goal from Sky match reports · Minute ' + row.derived_goal);
  }
  round.fixtures.forEach((fixture, index) => {
    const card = add(container, 'article', '');
    add(card, 'h3', fixture.home + ' vs ' + fixture.away);
    add(card, 'p', 'Kickoff · ' + date(fixture.kickoff));
    if (fixture.kickoff_source) source(card, 'Kickoff source', {
      url: fixture.kickoff_source, available_at: round.official.available_at, note: 'Schedule cross-check'
    });
    const pick = prediction?.fixtures[index];
    if (pick) {
      add(card, 'p', 'Prediction ' + score(pick.score) + ' · Exact chance ' + percent(pick.exact_probability));
      add(card, 'p', 'Model home / draw / away · ' + pick.result_probabilities.map(percent).join(' / '));
      if (pick.market_probabilities) {
        add(card, 'p', 'Market home / draw / away · ' + pick.market_probabilities.map(percent).join(' / '));
      }
      const scores = add(card, 'details', '');
      add(scores, 'summary', 'Most likely scores');
      const list = add(scores, 'ul', '');
      pick.top_scores.forEach(([value, probability]) => add(list, 'li', score(value) + ' · ' + percent(probability)));
    }
    if (fixture.result) {
      source(card, 'Verified result · ' + score(fixture.result.score), fixture.result);
      if (fixture.result.first_goal) {
        source(card, 'First goal · Minute ' + fixture.result.first_goal.minute, fixture.result.first_goal);
      }
    }
    const missing = row.missing_research.find(entry => entry.fixture === fixture.home + ' vs ' + fixture.away);
    if (missing) add(card, 'p', 'Missing evidence · ' + missing.missing.join(', '));
    if (model === 'venue_goals' && fixture.venue_history) {
      const details = add(card, 'details', '');
      add(details, 'summary', 'Five previous results per venue');
      for (const [side, matches] of Object.entries(fixture.venue_history)) {
        add(details, 'h4', side === 'home' ? fixture.home + ' at home' : fixture.away + ' away');
        const list = add(details, 'ul', '');
        for (const match of matches) source(add(list, 'li', ''), score(match.score) + ' vs ' + match.opponent, match);
      }
    }
    if (fixture.stats) {
      const details = add(card, 'details', '');
      add(details, 'summary', 'Form and opposition evidence');
      for (const record of fixture.stats.sources ?? [fixture.stats]) {
        source(details, record.provider, record);
      }
      for (const side of ['home', 'away']) {
        const team = fixture.stats[side];
        add(details, 'h4', fixture[side]);
        for (const [label, form] of [['Recent games', team.recent], ['Relevant venue', team.venue]]) {
          add(details, 'p', form.matches ? label + ' · ' + form.matches + ' matches · ' +
            [form.won, form.drawn, form.lost].join('/') + ' W/D/L · ' + form.goals_for + ' scored · ' +
            form.goals_against + ' conceded · ' + form.clean_sheets + ' clean sheets' : label + ' · Unavailable');
        }
        if (team.opposition_ppg !== null) add(details, 'p', 'Opponents averaged ' +
          team.opposition_ppg.toFixed(2) + ' points per game in the source competition.');
      }
    }
    if (fixture.research) {
      const details = add(card, 'details', '');
      add(details, 'summary', 'Research evidence');
      const list = add(details, 'ul', '');
      for (const [category, record] of Object.entries(fixture.research)) {
        const entry = add(list, 'li', '');
        source(entry, category.replaceAll('_', ' '), record);
        if (category === 'xg' || category === 'xga') {
          add(entry, 'p', 'Per match · Home ' + record.home + ' · Away ' + record.away);
        }
        if (category === 'odds') add(entry, 'p', 'Home / draw / away · ' + record.decimal.join(' / '));
      }
    }
  });
}

function showHistoricalStudy(study, candidates = []) {
  const root = byId('strategy-history');
  add(root, 'h3', 'Historical strategy backtest');
  add(root, 'p', study.rounds.length + ' complete historical rounds · Reconstructed from pre-deadline venue results');
  const qualityCounts = new Map();
  for (const entry of study.rounds) {
    qualityCounts.set(entry.source_quality, (qualityCounts.get(entry.source_quality) || 0) + 1);
  }
  if (qualityCounts.size) {
    const quality = add(root, 'p', '');
    quality.textContent = [...qualityCounts].map(([key, count]) => study.quality_labels[key] + ' · ' + count).join(' / ');
  }
  if (candidates.length) {
    add(root, 'p', candidates.length + ' incomplete archive entries are excluded from performance.');
  }
  if (study.rounds.length < 50) {
    add(root, 'p', 'Small sample. These results are insufficient to establish calibration or a winning strategy.', 'status');
  }
  for (const [key, summary] of Object.entries(study.summary)) {
    if (!summary.rounds) continue;
    const panel = add(root, 'details', '', 'historical-card');
    add(panel, 'summary', study.labels[key] + ' · ' + summary.average_points.toFixed(2) + ' average points');
    const metrics = add(panel, 'div', '', 'metrics');
    metric(metrics, 'Exact-score accuracy', percent(summary.exact_score_accuracy));
    metric(metrics, 'Correct-result accuracy', percent(summary.correct_result_accuracy));
    metric(metrics, '13+ forecast vs observed', percent(summary.predicted_13_plus) + ' / ' +
      percent(summary.observed_13_plus));
    metric(metrics, '13+ Brier score', summary.brier_13_plus.toFixed(3));
    const bins = add(panel, 'ul', '');
    for (const bin of summary.calibration) {
      add(bins, 'li', percent(bin.lower) + '–' + percent(bin.upper) + ' forecast band · ' +
        bin.rounds + ' rounds · ' + percent(bin.predicted) + ' forecast · ' + percent(bin.observed) + ' observed');
    }
  }
  for (const [name, trend] of Object.entries(study.trends ?? {})) {
    showTrend(root, study.labels[name], trend);
  }
  for (const { round, strategies, source_quality } of study.rounds) {
    const panel = add(root, 'details', '', 'historical-card');
    add(panel, 'summary', round.id + ' · Historical results');
    source(panel, study.quality_labels[source_quality] + ' · ' + date(round.deadline), round.deadline_evidence);
    for (const [key, entry] of Object.entries(strategies)) {
      add(panel, 'h4', study.labels[key] + ' · ' + entry.points + ' actual points');
      const list = add(panel, 'ul', '');
      round.fixtures.forEach((fixture, index) => {
        add(list, 'li', fixture.home + ' vs ' + fixture.away + ' · Pick ' +
          score(entry.picks[index]) + ' · Actual ' + score(fixture.result.score));
      });
    }
  }
  if (study.excluded.length) {
    const excluded = add(root, 'details', '', 'historical-card');
    add(excluded, 'summary', 'Excluded rounds');
    const list = add(excluded, 'ul', '');
    study.excluded.forEach(entry => add(list, 'li', entry.round + ' · ' + entry.reason));
  }
  if (study.dixon_coles.length) {
    const panel = add(root, 'details', '', 'historical-card');
    add(panel, 'summary', 'Dixon–Coles experiment · ' + study.dixon_coles.length + (study.dixon_coles.length === 1 ? ' held-out round' : ' held-out rounds'));
    for (const fold of study.dixon_coles) {
      add(panel, 'p', fold.round + ' · Fit on ' + fold.training_matches + ' earlier matches · ' +
        'ρ ' + fold.rho.toFixed(3) + (fold.grid_boundary ? ' (grid boundary)' : ''));
      add(panel, 'p', 'Exact-score log loss · Poisson ' + fold.original_log_loss.toFixed(3) +
        ' · Dixon–Coles ' + fold.adjusted_log_loss.toFixed(3));
    }
  }
}

function showTrend(root, label, trend) {
  if (!trend.length) return;
  const panel = add(root, 'details', '', 'historical-card');
  const latest = trend[trend.length - 1];
  add(panel, 'summary', label + ' · ' + latest.points + ' cumulative points');
  const list = add(panel, 'ol', '');
  for (const row of trend) {
    add(list, 'li', row.round_id + ' · ' + row.points + ' actual / ' +
      row.expected_points.toFixed(2) + ' model-expected points');
  }
}

function showPerformance(root, stats) {
  const metrics = add(root, 'div', '', 'metrics');
  metric(metrics, 'Rounds', stats.rounds);
  metric(metrics, 'Average points', stats.average_points.toFixed(2));
  metric(metrics, 'Expected points', stats.mean_expected_points.toFixed(2));
  metric(metrics, 'Exact-score accuracy', percent(stats.exact_score_accuracy));
  metric(metrics, 'Correct-result accuracy', percent(stats.correct_result_accuracy));
  metric(metrics, '13+ forecast vs observed', percent(stats.predicted_13_plus) + ' / ' +
    percent(stats.observed_13_plus));
  metric(metrics, '13+ Brier', stats.brier_13_plus.toFixed(3));
  const list = add(root, 'ul', '');
  for (const bin of stats.calibration) {
    add(list, 'li', percent(bin.lower) + '–' + percent(bin.upper) + ' band · ' + bin.rounds +
      ' rounds · ' + percent(bin.predicted) + ' forecast · ' + percent(bin.observed) + ' observed');
  }
}

function showProspective(data) {
  const root = byId('prospective');
  const summaries = Object.entries(data.summary);
  if (!summaries.length) add(root, 'p', 'No settled prospective rounds.');
  for (const [name, stats] of summaries) {
    add(root, 'h4', modelNames[name]);
    showPerformance(root, stats);
    add(root, 'p', 'Match result Brier · ' + stats.result_brier.toFixed(3));
    showTrend(root, modelNames[name], stats.trend);
  }
}

const experimentNames = {
  reduced_home_advantage: 'Reduced home advantage',
  away_goal_lift: 'Away goal adjustment',
  opponent_adjusted_form: 'Opponent-adjusted form',
  competition_shrinkage: 'Competition-average shrinkage',
  dixon_coles: 'Fitted Dixon–Coles'
};

function showExperiments(data) {
  const root = byId('experiments');
  add(root, 'p', data.eligible_holdouts + ' of ' + data.protocol.minimum_holdout_rounds +
    ' paired evaluation rounds required · Holdout starts ' + date(data.protocol.holdout_deadline_from));
  if (data.excluded_holdouts.length) {
    add(root, 'p', data.excluded_holdouts.length + ' rounds lacked all required paired inputs.');
  }
  const models = Object.entries(data.summary);
  if (!models.length) {
    add(root, 'p', 'Comparative scores appear when the registered sample is complete.');
    const list = add(root, 'ul', '');
    Object.keys(data.protocol.candidates).forEach(name => add(list, 'li', experimentNames[name]));
  }
  for (const [name, stats] of models) {
    const panel = add(root, 'details', '', 'historical-card');
    add(panel, 'summary', (experimentNames[name] ?? modelNames[name]) + ' · ' +
      stats.mean_log_loss.toFixed(3) + ' exact-score log loss');
    showPerformance(panel, stats);
    for (const [metric, values] of Object.entries(stats.paired_intervals_vs_venue)) {
      add(panel, 'p', (metric === 'points' ? 'Points' : 'Log loss') +
        ' difference vs venue · ' + values.difference.toFixed(3) + ' · 95% interval ' +
        values.interval_95.map(value => value.toFixed(3)).join(' to '));
    }
  }
}

function prospectiveRow(record) {
  const { predictions, settlement } = record;
  const evaluations = settlement?.evaluations ?? {};
  const round = {
    ...record.round, golden_goal: settlement?.golden_goal,
    fixtures: record.round.fixtures.map(fixture => settlement ?
      { ...fixture, result: settlement.results[fixture.id] } : fixture)
  };
  const benchmarks = Object.fromEntries(Object.entries(predictions)
    .filter(([name]) => name !== 'xg_market')
    .map(([name, prediction]) => [name, { prediction, evaluation: evaluations[name] }]));
  return { ...record, round, benchmarks, prediction: predictions.xg_market,
    evaluation: evaluations.xg_market };
}

async function load() {
  const response = await fetch('report.json');
  if (!response.ok) throw new Error('Could not load report');
  const data = await response.json();
  const metrics = byId('metrics');
  const base = data.baseline;
  metric(metrics, 'Round ' + base.round + ' baseline', base.points + ' points');
  metric(metrics, 'Baseline exact scores', base.exact_scores);
  metric(metrics, 'Baseline additional correct results', base.additional_correct_results);
  const backtest = data.backtest;
  metric(metrics, 'Scored historical rounds', backtest.rounds);
  if (backtest.rounds) {
    metric(metrics, 'Mean actual points', backtest.mean_points.toFixed(2));
    metric(metrics, 'Mean expected points', backtest.mean_expected_points.toFixed(2));
    metric(metrics, 'Actual 13+ hit rate', percent(backtest.hit_rate_13_plus));
    metric(metrics, '13+ Brier score', backtest.brier_13_plus.toFixed(3));
    if (backtest.golden_goal_mae !== null) {
      metric(metrics, 'Golden Goal mean absolute error', backtest.golden_goal_mae.toFixed(1) + ' min');
    }
  }
  byId('evaluation-status').textContent = base.source + (backtest.rounds ? '.' :
    ' · A backtest needs complete pre-deadline research and all six verified results.');
  showHistoricalStudy(data.strategy_backtest, data.archive_candidates);
  const matched = data.matched_backtest.xg_market.rounds > 0;
  const comparison = byId('comparison');
  add(comparison, 'h3', matched ? 'Like-for-like backtest' : 'Historical benchmark runs');
  for (const [name, summary] of Object.entries(matched ? data.matched_backtest : data.historical)) {
    if (!summary.rounds) continue;
    const panel = add(comparison, 'article', '');
    add(panel, 'h4', modelNames[name]);
    const stats = add(panel, 'div', '', 'metrics');
    metric(stats, 'Historical rounds', summary.rounds);
    metric(stats, 'Average points', summary.mean_points.toFixed(2));
    metric(stats, 'Exact-score accuracy', percent(summary.exact_score_accuracy));
    metric(stats, 'Mean forecast for 13+', percent(summary.mean_probability_13_plus));
    metric(stats, 'Observed 13+ hit rate', percent(summary.hit_rate_13_plus));
    metric(stats, '13+ Brier score', summary.brier_13_plus.toFixed(3));
    if (summary.golden_goal_mae !== null) {
      metric(stats, 'Golden Goal error (' + summary.golden_goal_minute_rounds + ' rounds)',
        summary.golden_goal_mae.toFixed(1) + ' min');
    }
  }
  if (!matched) {
    add(comparison, 'p', 'No completed round has all three forecasts for a like-for-like comparison.');
  }
  const prospective = data.prospective ?? { rounds: [], summary: {} };
  showProspective(prospective);
  if (data.experiments) showExperiments(data.experiments);
  const rows = [...data.rounds, ...prospective.rounds.map(prospectiveRow)].sort(
    (first, second) => new Date(first.round.deadline) - new Date(second.round.deadline));
  const select = byId('round');
  for (const row of rows) add(select, 'option', row.round.id);
  select.disabled = !rows.length;
  select.addEventListener('change', () => showRound(rows[select.selectedIndex]));
  const active = rows.findIndex(row => new Date(row.round.deadline) > new Date());
  if (active < 0) add(byId('upcoming-status'), 'p', 'No verified upcoming round is published.');
  select.selectedIndex = active >= 0 ? active : rows.length - 1;
  showRound(rows[select.selectedIndex]);
}
load().catch(() => { byId('round-content').textContent = 'Could not load the dashboard report.'; });
