const byId = id => document.getElementById(id);
const percent = value => (100 * value).toFixed(1) + '%';
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
  fixed_poisson: 'Fixed Poisson benchmark'};

function showRound(row, model = 'xg_market') {
  const container = byId('round-content');
  container.replaceChildren();
  if (!row) {
    add(container, 'p', 'No verified rounds are available.');
    return;
  }
  const { round } = row;
  const { prediction, evaluation } = model === 'xg_market' ? row : row.benchmarks[model];
  add(container, 'p', 'Entry deadline · ' + date(round.deadline));
  source(container, 'Official fixture evidence', round.official);
  const modelLabel = add(container, 'label', 'Forecast ');
  const select = add(modelLabel, 'select', '');
  for (const name of ['xg_market', ...Object.keys(row.benchmarks)]) {
    const option = add(select, 'option', modelNames[name]);
    option.value = name;
    option.selected = name === model;
  }
  select.addEventListener('change', () => {
    showRound(row, select.value);
    byId('round-content').querySelector('select').focus();
  });
  if (prediction) {
    const metrics = add(container, 'div', '', 'metrics');
    metric(metrics, 'Expected points', prediction.expected_points.toFixed(2));
    metric(metrics, 'Chance of 13+ points', percent(prediction.probability_13_plus));
    metric(metrics, 'Golden Goal estimate', 'Minute ' + prediction.golden_goal.minute);
    if (evaluation) metric(metrics, 'Actual points', evaluation.points);
    add(container, 'p', prediction.trials.toLocaleString() + ' simulations · No-goal probability ' +
        percent(prediction.golden_goal.no_goal));
  } else {
    add(container, 'p', row.missing_research.length ?
      'Model prediction pending complete pre-deadline evidence.' : 'Model prediction pending a frozen evidence snapshot.');
  }
  if (round.golden_goal) {
    const goal = round.golden_goal;
    source(container, 'Official Golden Goal · ' + (goal.minute ?? 'No goal'), goal);
  } else if (row.derived_goal !== null) {
    add(container, 'p', 'First goal from Sky match reports · Minute ' + row.derived_goal);
  }
  round.fixtures.forEach((fixture, index) => {
    const card = add(container, 'article', '');
    add(card, 'h3', fixture.home + ' vs ' + fixture.away);
    add(card, 'p', 'Kickoff · ' + date(fixture.kickoff));
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
    if (model === 'xg_market' && missing) add(card, 'p', 'Missing evidence · ' + missing.missing.join(', '));
    if (model === 'venue_goals' && fixture.venue_history) {
      const details = add(card, 'details', '');
      add(details, 'summary', 'Five previous results per venue');
      for (const [side, matches] of Object.entries(fixture.venue_history)) {
        add(details, 'h4', side === 'home' ? fixture.home + ' at home' : fixture.away + ' away');
        const list = add(details, 'ul', '');
        for (const match of matches) source(add(list, 'li', ''), score(match.score) + ' vs ' + match.opponent, match);
      }
    }
    if (fixture.research) {
      const details = add(card, 'details', '');
      add(details, 'summary', 'Research evidence');
      const list = add(details, 'ul', '');
      for (const [category, record] of Object.entries(fixture.research)) {
        source(add(list, 'li', ''), category.replaceAll('_', ' '), record);
      }
    }
  });
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
  const matched = data.matched_backtest.xg_market.rounds > 0;
  const comparison = byId('comparison');
  add(comparison, 'h3', matched ? 'Like-for-like backtest' : 'Historical benchmark runs');
  for (const [name, summary] of Object.entries(matched ? data.matched_backtest : data.historical)) {
    if (!summary.rounds) continue;
    const panel = add(comparison, 'article', '');
    add(panel, 'h4', modelNames[name]);
    const stats = add(panel, 'div', '', 'metrics');
    metric(stats, 'Historical rounds', summary.rounds);
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
  const select = byId('round');
  for (const row of data.rounds) add(select, 'option', row.round.id);
  select.disabled = !data.rounds.length;
  select.addEventListener('change', () => showRound(data.rounds[select.selectedIndex]));
  showRound(data.rounds[0]);
}
load().catch(() => { byId('round-content').textContent = 'Could not load the dashboard report.'; });
