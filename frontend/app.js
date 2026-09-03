/* CLEARCUT front end.
   Streams agent events over SSE while the network runs, then renders the
   report as paper. No framework — the whole app is one state object and
   three render functions, which keeps the container a single artifact
   with no build step. */

const $ = (s) => document.querySelector(s);
const el = (t, c, txt) => { const n = document.createElement(t); if (c) n.className = c; if (txt != null) n.textContent = txt; return n; };

const DRAFT_HUE = { White:'#FBFAF7', Blue:'#8FB4DA', Pink:'#E8A6BC', Yellow:'#E3D26A', Green:'#7FC08D', Goldenrod:'#D9B44A' };

const VERDICTS = [
  ['must_change',        'Must change'],
  ['license_required',   'Licence required'],
  ['legal_review',       'Refer to counsel'],
  ['clear_with_caution', 'Clear with caution'],
  ['clear',              'Clear'],
];
const VLABEL = Object.fromEntries(VERDICTS);

const state = { drafts: [], selected: null, running: false, events: 0, report: null, project: 'demo' };

/* Drafts of the same picture share a ledger: the_long_odds_v2 -> the_long_odds.
   That is the whole point — a revision is measured against its predecessor. */
const projectOf = (id) => (id || 'demo').replace(/_v\d+$/, '');

/* ---------------- boot ---------------- */
async function boot() {
  try {
    const h = await (await fetch('/api/health')).json();
    $('#d-gem').classList.add(h.gemini_configured ? 'on' : 'off');
    $('#d-par').classList.add(h.parallel_configured ? 'on' : 'off');
  } catch { /* health is advisory */ }

  state.drafts = await (await fetch('/api/screenplays')).json();
  renderDrafts();
  if (state.drafts.length) select(state.drafts[state.drafts.length - 1].id);
  else loadLedger();
}

function renderDrafts() {
  const box = $('#drafts');
  box.innerHTML = '';
  state.drafts.forEach(d => {
    const b = el('button', 'draft' + (d.id === state.selected ? ' sel' : ''));
    const t = el('div', 't'); t.textContent = d.title;
    const m = el('div', 'm');
    const sw = el('span', 'swatch');
    sw.style.background = DRAFT_HUE[d.draft] || '#888';
    m.append(sw, document.createTextNode(`${d.draft || 'Draft'} · ${d.date || ''} · ${d.pages}pp`));
    b.append(t, m);
    b.onclick = () => select(d.id);
    box.append(b);
  });
}

function select(id) {
  state.selected = id;
  state.project = projectOf(id);
  $('#proj').textContent = state.project;
  renderDrafts();
  loadLedger();
}

/* ---------------- run ---------------- */
$('#go').onclick = run;

async function run() {
  if (state.running || !state.selected) return;
  state.running = true; state.events = 0; state.report = null;
  $('#go').disabled = true;
  $('#go').textContent = 'Clearing…';
  $('#ph').hidden = true;
  const trace = $('#trace');
  trace.hidden = false; trace.innerHTML = '';
  show('trace');

  const res = await fetch('/api/clear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      screenplay: state.selected,
      project_id: state.project,
      use_ledger: $('#o-ledger').checked,
      substitute: $('#o-sub').checked,
      deep_verify: $('#o-deep').checked,
    }),
  });

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop();
    for (const p of parts) {
      if (!p.startsWith('data: ')) continue;
      let m; try { m = JSON.parse(p.slice(6)); } catch { continue; }
      if (m.type === 'event') pushEvent(m.data);
      else if (m.type === 'report') { state.report = m.data; renderReport(); }
      else if (m.type === 'error') pushEvent({ agent: 'pipeline', phase: 'error', message: m.data.message });
    }
  }

  state.running = false;
  $('#go').disabled = false;
  $('#go').textContent = 'Run clearance';
  loadLedger();
}

function pushEvent(e) {
  state.events++;
  $('#n-ev').textContent = state.events;
  const row = el('div', `ev ${e.agent}` + (e.phase === 'error' ? ' err' : ''));
  row.append(el('div', 'who', e.agent));
  const msg = el('div', 'msg');
  // highlight quantities so a viewer's eye lands on the numbers
  msg.innerHTML = escapeHTML(e.message).replace(/\b(\d+)\b/g, '<em>$1</em>');
  row.append(msg);
  const t = $('#trace');
  t.append(row);
  t.parentElement.scrollTop = t.parentElement.scrollHeight;
}

/* ---------------- report ---------------- */
function renderReport() {
  const r = state.report;
  const findings = r.findings || [];
  $('#n-find').textContent = findings.length;

  const counts = {};
  findings.forEach(f => { const v = f.adjudication?.verdict; if (v) counts[v] = (counts[v] || 0) + 1; });
  const blocking = (counts.must_change || 0) + (counts.license_required || 0) + (counts.legal_review || 0);

  const wrap = el('div', 'paper-wrap');
  const p = el('div', 'paper');

  p.append(el('h1', null, 'Script Clearance Report'));
  const sub = el('div', 'sub');
  const m = r.script || {};
  sub.textContent = [m.title, m.author, m.draft_label && `${m.draft_label} draft`, m.draft_date,
                     `${m.page_count} pages`, r.report_id].filter(Boolean).join(' · ');
  p.append(sub);

  const vl = el('div', 'verdictline ' + (blocking ? 'blocked' : 'ok'));
  vl.textContent = blocking
    ? `${blocking} item${blocking === 1 ? '' : 's'} must be resolved before an E&O policy can bind.`
    : 'No blocking items. This draft is clear for E&O submission.';
  p.append(vl);

  const tally = el('div', 'tally');
  VERDICTS.forEach(([k, lbl]) => {
    const d = el('div');
    d.append(el('b', null, String(counts[k] || 0)), document.createTextNode(lbl));
    tally.append(d);
  });
  const meta = el('div');
  meta.append(el('b', null, `${Math.round(r.elapsed_seconds || 0)}s`),
              document.createTextNode(`${r.parallel_calls || 0} web verifications`));
  tally.append(meta);
  p.append(tally);

  VERDICTS.forEach(([k, lbl]) => {
    const group = findings.filter(f => f.adjudication?.verdict === k);
    if (!group.length) return;
    group.sort((a, b) => (a.item.locations[0]?.page || 0) - (b.item.locations[0]?.page || 0));
    p.append(el('div', 'group', `${lbl} — ${group.length}`));
    group.forEach(f => p.append(finding(f, k)));
  });

  wrap.append(p);
  const v = $('#v-report');
  v.innerHTML = '';
  v.append(wrap);
}

function finding(f, verdict) {
  const it = f.item, adj = f.adjudication, sub = f.substitution;
  const n = el('div', `finding v-${verdict}`);

  const head = el('div', 'head');
  head.append(el('span', 'vdot'), el('span', 'val', it.value),
              el('span', 'cat', (it.category || '').replace(/_/g, ' ')));
  const pages = (it.locations || []).slice(0, 5)
    .map(l => 'p' + l.page + (l.scene_number ? ` sc.${l.scene_number}` : '')).join(', ');
  head.append(el('span', 'pages', pages));
  n.append(head);

  if (it.locations?.[0]?.quote) n.append(el('div', 'quote', it.locations[0].quote));
  if (adj?.rationale) n.append(el('div', 'why', adj.rationale));
  if (adj?.rule_applied) n.append(el('div', 'rule', adj.rule_applied));

  if (adj?.citations?.length) {
    const c = el('div', 'cites');
    adj.citations.slice(0, 3).forEach(ct => {
      const a = el('a', null, ct.title || ct.url);
      a.href = ct.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      c.append(a);
    });
    n.append(c);
  }

  if (sub?.verified_clear) {
    const fx = el('div', 'fix');
    fx.append(el('b', null, `Recommended replacement: ${sub.proposed}`),
              document.createTextNode(' — re-cleared and verified'));
    if (sub.rejected_candidates?.length)
      fx.append(el('div', 'rej', `Rejected: ${sub.rejected_candidates.join(', ')}`));
    n.append(fx);
  } else if (sub?.rejected_candidates?.length) {
    const fx = el('div', 'fix');
    fx.append(el('div', 'rej', `No verified replacement found. Tried: ${sub.rejected_candidates.join(', ')}`));
    n.append(fx);
  }
  return n;
}

/* ---------------- ledger ---------------- */
async function loadLedger() {
  let d;
  try { d = await (await fetch(`/api/ledger/${state.project}`)).json(); } catch { return; }
  $('#n-led').textContent = d.entries;

  const s = $('#ledger-stats');
  s.innerHTML = '';
  const add = (k, v) => { const r = el('div', 'ledger-stat'); r.append(el('span', null, k), el('b', null, String(v))); s.append(r); };
  add('Cleared subjects', d.entries);
  add('Drafts recorded', (d.history || []).length);
  if (d.history?.length) add('Latest draft', d.history[d.history.length - 1].draft);

  const v = $('#v-ledger');
  v.innerHTML = '';
  const box = el('div', 'ledger-view');
  const h = el('div', 'lrow h');
  ['Subject', 'Category', 'Verdict', 'Since'].forEach(x => h.append(el('div', null, x)));
  box.append(h);
  (d.items || []).forEach(i => {
    const r = el('div', 'lrow');
    r.append(el('div', null, i.value), el('div', 'c', i.category.replace(/_/g, ' ')));
    const pv = el('div'); pv.append(el('span', 'pill ' + i.verdict, VLABEL[i.verdict] || i.verdict));
    r.append(pv, el('div', 'c', i.first_cleared_draft || '—'));
    box.append(r);
  });
  if (!(d.items || []).length) box.append(el('div', 'lrow', 'No entries yet — run a clearance pass.'));
  v.append(box);
}

/* ---------------- tabs ---------------- */
document.querySelectorAll('.tab').forEach(t => t.onclick = () => show(t.dataset.v));
function show(v) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.v === v));
  ['trace', 'report', 'ledger'].forEach(x => { $('#v-' + x).hidden = (x !== v); });
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

boot();
