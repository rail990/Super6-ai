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
  if (new URL(record.url).protocol === 'https:') link.href = record.url;
  add(parent, 'p', date(record.available_at) + ' · ' + record.note);
}

function showRound(row) {
  const container = byId('round-content');
  container.replaceChildren();
  if (!row) {
    add(container, 'p', 'No verified rounds are available.');
    return;
  }
  const { round, prediction, evaluation } = row;
  add(container, 'p', 'Entry deadline · ' + date(round.deadline));
  source(container, 'Official fixture evidence', round.official);
  if (prediction) {
    const metrics = add(container, 'div', '', 'metrics');
    metric(metrics, 'Expected points', prediction.expected_points.toFixed(2));
    metric(metrics, 'Chance of 13+ points', percent(prediction.probability_13_plus));
    metric(metrics, 'Golden Goal estimate', 'Minute ' + prediction.golden_goal.minute);
    if (evaluation) metric(metrics, 'Actual points', evaluation.points);
    add(container, 'p', prediction.trials.toLocaleString() + ' simulations · No-goal probability ' +
        percent(prediction.golden_goal.no_goal));
  } else {
    add(container, 'p', 'Predictions pending complete pre-deadline research for all six fixtures.');
  }
  if (round.golden_goal) {
    const goal = round.golden_goal;
    source(container, 'Official Golden Goal · ' + (goal.minute ?? 'No goal'), goal);
  }
  round.fixtures.forEach((fixture, index) => {
    const card = add(container, 'article', '');
    add(card, 'h3', fixture.home + ' vs ' + fixture.away);
    add(card, 'p', 'Kickoff · ' + date(fixture.kickoff));
    const pick = prediction?.fixtures[index];
    if (pick) {
      add(card, 'p', 'Prediction ' + score(pick.score) + ' · Exact chance ' + percent(pick.exact_probability));
      add(card, 'p', 'Model home / draw / away · ' + pick.result_probabilities.map(percent).join(' / '));
      add(card, 'p', 'Market home / draw / away · ' + pick.market_probabilities.map(percent).join(' / '));
      const scores = add(card, 'details', '');
      add(scores, 'summary', 'Most likely scores');
      const list = add(scores, 'ul', '');
      pick.top_scores.forEach(([value, probability]) => add(list, 'li', score(value) + ' · ' + percent(probability)));
    }
    if (fixture.result) source(card, 'Verified result · ' + score(fixture.result.score), fixture.result);
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
  const select = byId('round');
  for (const row of data.rounds) add(select, 'option', row.round.id);
  select.disabled = !data.rounds.length;
  select.addEventListener('change', () => showRound(data.rounds[select.selectedIndex]));
  showRound(data.rounds[0]);
}
load().catch(() => { byId('round-content').textContent = 'Could not load the dashboard report.'; });
