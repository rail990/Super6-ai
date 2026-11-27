const captureForm = document.getElementById('capture-form');
const draftKey = 'super6-round-draft-v1';
let loadedRound = null;
let selectedRound = null;
let manualRecords = Array.from({ length: 6 }, () => ({}));
let bindings = Array(6).fill(null);

function control(id) { return document.getElementById(id); }
function captureStatus(message) { control('capture-status').textContent = message; }

function inputField(parent, name, title) {
  const label = document.createElement('label');
  label.textContent = title;
  const input = document.createElement('input');
  input.name = name;
  input.required = true;
  label.append(input);
  parent.append(label);
}

for (let index = 0; index < 6; index++) {
  const group = document.createElement('fieldset');
  const legend = document.createElement('legend');
  legend.textContent = 'Fixture ' + (index + 1);
  group.append(legend);
  inputField(group, 'home' + index, 'Home team');
  inputField(group, 'away' + index, 'Away team');
  inputField(group, 'kickoff' + index, 'Kickoff (ISO 8601)');
  inputField(group, 'fixture-id' + index, 'Fixture identifier');
  control('capture-fixtures').append(group);
  control('manual-fixture').add(new Option(legend.textContent, index));
}

for (const [key, name] of Object.entries({
  injuries: 'Injuries', suspensions: 'Suspensions', lineups: 'Likely line-ups',
  team_news: 'Team news', odds: 'Bookmaker odds', xg: 'Expected goals', xga: 'Expected goals against'
})) control('manual-category').add(new Option(name, key));

function iso(value) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})$/.test(value)) {
    throw new Error('Use ISO 8601 with a timezone, for example 2026-11-24T20:00:00Z.');
  }
  const result = new Date(value);
  const calendar = new Date(value.slice(0, 10) + 'T00:00:00Z');
  if (!Number.isFinite(result.valueOf()) || !Number.isFinite(calendar.valueOf()) ||
      calendar.toISOString().slice(0, 10) !== value.slice(0, 10) ||
      Number(value.slice(11, 13)) > 23) {
    throw new Error('Enter a valid date and time.');
  }
  return result.toISOString();
}

function https(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.port) {
    throw new Error('Enter a public HTTPS source URL.');
  }
  return url;
}

function fixtureAt(index) {
  const fields = captureForm.elements;
  const value = key => fields[key + index].value.trim();
  const result = { id: value('fixture-id'), home: value('home'), away: value('away'),
    kickoff: iso(value('kickoff')) };
  if (!result.id || !result.home || !result.away) throw new Error('Complete the fixture before adding evidence.');
  return result;
}

function fixtureKey(fixture, deadline) {
  return JSON.stringify([fixture.id, fixture.home, fixture.away, fixture.kickoff, deadline]);
}

function valuesField() {
  const category = control('manual-category').value;
  const values = control('manual-values');
  control('manual-values-label').hidden = !['odds', 'xg', 'xga'].includes(category);
  values.placeholder = category === 'odds' ? 'Home, draw, away decimal odds' : 'Home, away per-match values';
}
control('manual-category').addEventListener('change', valuesField);

control('manual-save').addEventListener('click', () => {
  try {
    const index = Number(control('manual-fixture').value);
    const category = control('manual-category').value;
    const available = iso(control('manual-time').value.trim());
    const deadline = iso(captureForm.elements.deadline.value.trim());
    const captured = new Date().toISOString();
    if (available >= deadline || captured >= deadline || available > captured) {
      throw new Error('Manual evidence must be available and captured before the entry deadline.');
    }
    const note = control('manual-note').value.trim();
    if (!note) throw new Error('Add a research note.');
    const record = { url: https(control('manual-url').value).href, available_at: available,
      captured_at: captured, note };
    if (['odds', 'xg', 'xga'].includes(category)) {
      const values = control('manual-values').value.split(',').map(value => value.trim());
      const numeric = values.map(Number);
      const isOdds = category === 'odds';
      if (values.length !== (isOdds ? 3 : 2) || values.some(value => !value) ||
          numeric.some(value => !Number.isFinite(value) ||
            (isOdds ? value < 1.000001 || value > 10000 : value < 0 || value > 12))) {
        throw new Error('Enter valid comma-separated values in the indicated order.');
      }
      if (isOdds) record.decimal = numeric;
      else [record.home, record.away] = numeric;
    }
    const key = fixtureKey(fixtureAt(index), deadline);
    if (bindings[index] && bindings[index] !== key) {
      throw new Error('This fixture changed after evidence was attached.');
    }
    bindings[index] = key;
    manualRecords[index][category] = record;
    captureStatus('Evidence attached to fixture ' + (index + 1) + '. Save to keep it in the draft.');
  } catch (error) {
    captureStatus(error.message);
  }
});

function loadCapture(record) {
  loadedRound = record;
  const fields = captureForm.elements;
  for (const [key, value] of Object.entries({
    id: record.id, deadline: record.deadline.replace('.000Z', 'Z'),
    url: record.official.url, note: record.official.note
  })) fields[key].value = value;
  record.fixtures.forEach((fixture, index) => {
    for (const key of ['home', 'away', 'kickoff']) {
      fields[key + index].value = fixture[key].replace('.000Z', 'Z');
    }
    fields['fixture-id' + index].value = fixture.id ?? '';
  });
  manualRecords = record.fixtures.map(fixture => ({ ...fixture.research }));
  bindings = record.fixtures.map(fixture => Object.keys(fixture.research ?? {}).length ?
    fixtureKey({ ...fixture, kickoff: new Date(fixture.kickoff).toISOString() },
      new Date(record.deadline).toISOString()) : null);
  fields.confirmed.checked = false;
}

function captureSelection(round) {
  selectedRound = round;
  control('capture-selected').disabled = !round;
}

control('capture-selected').addEventListener('click', () => {
  loadCapture(selectedRound);
  captureStatus('Review the selected six fixtures before saving a confirmation.');
});

let savedRound;
try {
  savedRound = JSON.parse(localStorage.getItem(draftKey));
  if (savedRound) {
    loadCapture(savedRound);
    control('capture-export').disabled = false;
  }
} catch {
  captureStatus('This browser could not load the saved draft.');
}

captureForm.addEventListener('submit', event => {
  event.preventDefault();
  try {
    const fields = captureForm.elements;
    const value = name => fields[name].value.trim();
    const deadline = iso(value('deadline'));
    const now = new Date().toISOString();
    const url = https(value('url'));
    if (!['super6.skysports.com', 'www.skysports.com', 'skysports.com'].includes(url.hostname)) {
      throw new Error('Use an official Sky Sports Super 6 source.');
    }
    if (now >= deadline) throw new Error('The entry deadline has passed. Historical rounds need archived evidence.');
    const fixtures = manualRecords.map((research, index) => {
      const fixture = fixtureAt(index);
      const previous = loadedRound?.fixtures[index];
      const same = previous && ['id', 'home', 'away'].every(key => previous[key] === fixture[key]) &&
        new Date(previous.kickoff).toISOString() === fixture.kickoff &&
        new Date(loadedRound.deadline).toISOString() === deadline;
      if (bindings[index] && bindings[index] !== fixtureKey(fixture, deadline)) {
        throw new Error('A fixture with attached research changed. Start a fresh draft for a changed slate.');
      }
      return { ...(same ? previous : {}), ...fixture, ...(Object.keys(research).length ? { research } : {}) };
    });
    const teams = fixtures.flatMap(fixture => [fixture.home, fixture.away]).map(team => team.toLowerCase());
    if (teams.includes('') || new Set(teams).size !== 12 ||
        new Set(fixtures.map(fixture => fixture.id)).size !== 6 || fixtures.some(f => !f.id || f.kickoff < deadline)) {
      throw new Error('Enter six distinct fixture identifiers and twelve distinct teams. Kickoffs must follow the deadline.');
    }
    const id = value('id');
    const note = value('note');
    if (!id || !note) throw new Error('Enter a round label and verification note.');
    const record = { id, deadline, deadline_basis: note,
      official: { url: url.href, available_at: now, confirmed_at: now, note }, fixtures };
    localStorage.setItem(draftKey, JSON.stringify(record));
    savedRound = record;
    loadedRound = record;
    control('capture-export').disabled = false;
    captureStatus('Six fixtures confirmed and saved on this device.');
  } catch (error) {
    captureStatus(error.message);
  }
});

control('capture-export').addEventListener('click', () => {
  const file = new Blob([JSON.stringify(savedRound, null, 2) + '\n'], { type: 'application/json' });
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'super6-round.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
