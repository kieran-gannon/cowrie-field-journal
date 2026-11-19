'use strict';

const $ = id => document.getElementById(id);
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const fmt = number => new Intl.NumberFormat('en').format(number);
const labels = {
  connections: 'Connections',
  unique_source_ips: 'Unique source IPs',
  sessions_with_accepted_login: 'Sessions with accepted login',
  sessions_with_commands: 'Sessions with commands',
  host_verified_captures: 'Verified captures',
  backend_connection_errors: 'Backend errors',
};
const briefStates = {
  unavailable: 'AI brief unavailable for this day.',
  no_findings: 'The model selected no publishable finding.',
  no_observations: 'No observations were available for an AI brief.',
};

let currentRequest = 0;

function el(tag, text = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}

async function json(path) {
  const response = await fetch(path, {cache: 'no-cache'});
  if (!response.ok) throw new Error('Unable to read the report');
  return response.json();
}

function renderTrend(context) {
  const days = [...context.history, context.today].slice(-30);
  const maximum = Math.max(4, ...days.map(day => day.metrics?.connections ?? 0));
  const step = Math.ceil(maximum / 4);
  const bars = $('chart-bars');
  const table = $('chart-table');
  bars.replaceChildren();
  table.replaceChildren();
  $('chart-scale').replaceChildren(...[4, 3, 2, 1, 0].map(tick => el('span', fmt(tick * step))));
  for (const day of days) {
    const count = day.metrics?.connections;
    const observed = count != null;
    const bar = el('span');
    bar.className = observed ? 'bar' : 'bar missing';
    bar.style.setProperty('--height', observed && count ? `${100 * count / (4 * step)}%` : '0%');
    if (observed && count === 0) bar.style.minHeight = '0';
    bar.title = `${day.day_utc} · ${observed ? fmt(count) + ' connections' : 'No observations'}`;
    bars.append(bar);
    const row = el('tr');
    const date = el('th', day.day_utc);
    date.scope = 'row';
    row.append(date, el('td', observed ? fmt(count) : '—'), el('td', fmt(day.coverage.hours_with_cowrie_events)));
    table.append(row);
  }
  $('chart-start').textContent = days[0].day_utc;
  $('chart-end').textContent = days.at(-1).day_utc;
  $('trend-summary').textContent = 'Blank days have no retained observations. An event count does not measure uptime.';
}

function render(report, context, base) {
  const {stats, brief} = report;
  $('report-day').dateTime = report.day_utc;
  $('report-day').textContent = report.day_utc + ' UTC';
  $('coverage').textContent = stats.coverage.status === 'no_observations'
    ? 'No Cowrie events observed · coverage unverified'
    : `Events observed in ${stats.coverage.hours_with_cowrie_events} of 24 hourly bins · uptime unverified`;

  $('metrics').replaceChildren(...Object.entries(labels).map(([key, label]) => {
    const item = el('div');
    item.append(el('dt', label), el('dd', stats.metrics ? fmt(stats.metrics[key]) : '—'));
    return item;
  }));
  renderTrend(context);

  $('brief-status').textContent = briefStates[brief.state] || '';
  $('model').textContent = `${brief.model} · Prompt ${brief.prompt_version}`;
  $('findings').replaceChildren(...brief.findings.map(finding => {
    const item = el('li');
    item.append(el('p', finding.text));
    for (const ref of finding.evidence_ids) {
      const link = el('a', ref);
      link.href = base + '/context.json';
      item.append(link);
    }
    return item;
  }));
  $('report-json').href = base + '/report.json';
  $('context-json').href = base + '/context.json';
}

async function showDay(day) {
  const request = ++currentRequest;
  $('status').hidden = false;
  $('status').textContent = 'Loading report…';
  $('report').hidden = true;
  try {
    const base = './data/' + day;
    const [report, context] = await Promise.all([json(base + '/report.json'), json(base + '/context.json')]);
    if (request !== currentRequest) return;
    if (report.day_utc !== day || context.today.day_utc !== day) throw new Error('Report date mismatch');
    render(report, context, base);
    $('status').hidden = true;
    $('report').hidden = false;
  } catch {
    if (request === currentRequest) $('status').textContent = 'This report could not be loaded. Select another date or reload the page.';
  }
}

async function init() {
  try {
    const index = await json('./data/index.json');
    const days = [...new Set(index.days.filter(day => typeof day === 'string' && datePattern.test(day)))].sort().reverse();
    if (!days.length) {
      $('archive').replaceChildren(el('option', 'No dates published'));
      $('status').textContent = 'No daily briefs have been published yet.';
      return;
    }
    $('archive').replaceChildren(...days.map(day => new Option(day, day)));
    $('archive').disabled = false;
    const requested = new URLSearchParams(location.search).get('day');
    if (days.includes(requested)) $('archive').value = requested;
    $('archive').addEventListener('change', () => {
      const url = new URL(location.href);
      url.searchParams.set('day', $('archive').value);
      history.replaceState(null, '', url);
      showDay($('archive').value);
    });
    showDay($('archive').value);
  } catch {
    $('status').textContent = 'The archive could not be loaded. Reload the page to try again.';
  }
}

init();
