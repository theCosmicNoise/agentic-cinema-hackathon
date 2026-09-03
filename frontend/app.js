/* CLEARCUT — stage-gated review client.
   Every stage stops and waits for a human. The reviewer's decisions are
   state, not annotations: a dismissed item never reaches research, an
   overruled verdict is what the report prints. */

const $ = (s) => document.querySelector(s);
const el = (t, c, txt) => { const n = document.createElement(t); if (c) n.className = c; if (txt != null) n.textContent = txt; return n; };
const api = async (url, opts) => { const r = await fetch(url, opts); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r.json(); };
const post = (url, body) => api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

const DRAFT_HUE = { White:'#FBFAF7', Blue:'#8FB4DA', Pink:'#E8A6BC', Yellow:'#E3D26A', Green:'#7FC08D', Goldenrod:'#D9B44A' };
const VERDICTS = [['clear','Clear'],['clear_with_caution','Clear with caution'],['must_change','Must change'],['license_required','Licence required'],['legal_review','Refer to counsel']];
const VLABEL = Object.fromEntries(VERDICTS);
const VCLASS = { must_change:'blocking', license_required:'licensed', legal_review:'review', clear_with_caution:'caution', clear:'ok' };

const S = { drafts: [], draft: null, stages: [], sess: null, view: null, running: false, trace: [] };

/* ---------------- boot ---------------- */
async function boot() {
  try {
    const h = await api('/api/health');
    $('#d-gem').classList.add(h.gemini_configured ? 'on' : 'off');
    $('#d-par').classList.add(h.parallel_configured ? 'on' : 'off');
  } catch {}
  S.stages = await api('/api/stages');
  S.drafts = await api('/api/screenplays');
  renderDrafts();
  if (S.drafts.length) S.draft = S.drafts[S.drafts.length - 1].id, renderDrafts();
}

function renderDrafts() {
  const box = $('#drafts'); box.innerHTML = '';
  S.drafts.forEach(d => {
    const b = el('button', 'draft' + (d.id === S.draft ? ' sel' : ''));
    b.append(el('div', 't', d.title));
    const m = el('div', 'm');
    const sw = el('span', 'swatch'); sw.style.background = DRAFT_HUE[d.draft] || '#888';
    m.append(sw, document.createTextNode(`${d.draft || 'Draft'} · ${d.date || ''} · ${d.pages}pp`));
    b.append(m);
    b.onclick = () => { S.draft = d.id; renderDrafts(); };
    box.append(b);
  });
}

$('#start').onclick = async () => {
  if (!S.draft) return;
  S.sess = await post('/api/sessions', { screenplay: S.draft });
  $('#setup').hidden = true; $('#pipeline').hidden = false; $('#sessmeta').hidden = false;
  S.view = 'breakdown';
  renderAll();
};

$('#newsess').onclick = () => {
  S.sess = null; S.view = null; S.trace = [];
  $('#setup').hidden = false; $('#pipeline').hidden = true; $('#sessmeta').hidden = true;
  $('#stageview').innerHTML = '<div class="placeholder"><div class="big">Open a clearance session</div>'
    + '<div>Six agents run in sequence. You review and approve each one before the next begins.</div></div>';
};

/* ---------------- rail ---------------- */
function stageState(id) { return S.sess?.stages?.[id] || { status: 'pending' }; }

function unlocked(i) {
  if (!S.sess) return false;
  if (i === 0) return true;
  return stageState(S.stages[i - 1].id).status === 'approved';
}

function renderStages() {
  const box = $('#stages'); box.innerHTML = '';
  S.stages.forEach((st, i) => {
    const s = stageState(st.id);
    const open = unlocked(i);
    let cls = '', label = 'Locked';
    if (open) {
      if (s.status === 'approved') { cls = 'done'; label = 'Approved'; }
      else if (s.status === 'awaiting_review') { cls = 'review'; label = 'Needs your review'; }
      else if (s.status === 'running') { cls = 'busy'; label = 'Running…'; }
      else if (s.status === 'error') { cls = 'err'; label = 'Failed'; }
      else label = 'Ready to run';
    }
    const b = el('button', `stage ${cls}` + (open ? '' : ' locked') + (S.view === st.id ? ' sel' : ''));
    const ix = el('div', 'ix', s.status === 'approved' ? '✓' : String(i + 1));
    const body = el('div');
    body.append(el('div', 'nm', st.name), el('div', 'stat', label));
    b.append(ix, body);
    if (open) b.onclick = () => { S.view = st.id; renderAll(); };
    box.append(b);
  });

  const m = $('#meta'); m.innerHTML = '';
  const row = (k, v) => { const r = el('div', 'metarow'); r.append(el('span', null, k), el('b', null, String(v))); m.append(r); };
  row('Draft', S.sess.script.draft_label || '—');
  row('Pages', S.sess.script.page_count);
  row('Flagged', S.sess.items.length);
  const dismissed = Object.values(S.sess.decisions || {}).filter(d => d.dismissed).length;
  if (dismissed) row('Dismissed', dismissed);
  const ov = Object.values(S.sess.decisions || {}).filter(d => d.verdict_override).length;
  if (ov) row('Overrides', ov);
  if (S.sess.carried?.length) row('From ledger', S.sess.carried.length);
}

/* ---------------- stage detail ---------------- */
function renderAll() { renderStages(); renderDetail(); }

function renderDetail() {
  const v = $('#stageview'); v.innerHTML = '';
  const meta = S.stages.find(x => x.id === S.view);
  if (!meta) return;
  const st = stageState(S.view);
  const d = el('div', 'detail');

  const head = el('div', 'dhead');
  const h = el('h2'); h.append(document.createTextNode(meta.name));
  const badgeCls = { approved:'done', awaiting_review:'review', running:'busy', error:'err' }[st.status] || '';
  const badgeTxt = { approved:'Approved', awaiting_review:'Awaiting your review', running:'Running', error:'Failed' }[st.status] || 'Not run';
  h.append(el('span', 'badge ' + badgeCls, badgeTxt));
  head.append(h, el('div', 'does', meta.does));
  if (st.summary) head.append(el('div', 'sum', st.summary));
  if (st.error) head.append(el('div', 'sum', st.error.slice(0, 300)));
  d.append(head);

  if (S.running && S.view === S.runningStage) {
    const t = el('div', 'livetrace');
    S.trace.forEach(e => t.append(traceRow(e)));
    d.append(t);
  }

  if (st.status === 'pending' || st.status === 'error') {
    d.append(runPrompt(meta));
  } else {
    d.append(bodyFor(S.view));
    d.append(gate(meta, st));
  }
  v.append(d);
  const lt = d.querySelector('.livetrace'); if (lt) lt.scrollTop = lt.scrollHeight;
}

function traceRow(e) {
  const r = el('div', `ev ${e.agent}` + (e.phase === 'error' ? ' err' : ''));
  r.append(el('div', 'who', e.agent));
  const m = el('div', 'msg');
  m.innerHTML = esc(e.message).replace(/\b(\d+)\b/g, '<em>$1</em>');
  r.append(m);
  return r;
}

function runPrompt(meta) {
  const box = el('div', 'gate');
  box.append(el('div', 'ask', S.running ? 'Running…' : `This stage has not run yet. ${meta.does}`));
  const b = el('button', 'approve', S.running ? 'Running…' : `Run ${meta.name.toLowerCase()}`);
  b.disabled = S.running;
  b.onclick = () => runStage(meta.id);
  box.append(b);
  return box;
}

function gate(meta, st) {
  const box = el('div', 'gate');
  if (st.status === 'approved') {
    box.append(el('div', 'ask', 'Approved. ' + (nextName() ? `Next: ${nextName()}.` : 'Pipeline complete.')));
    const nx = nextStage();
    if (nx) { const b = el('button', 'approve', `Go to ${nx.name}`); b.onclick = () => { S.view = nx.id; renderAll(); }; box.append(b); }
  } else {
    box.append(el('div', 'ask', meta.gate));
    const b = el('button', 'approve', 'Approve & continue');
    b.disabled = S.running;
    b.onclick = async () => {
      S.sess = await post(`/api/sessions/${S.sess.id}/approve/${meta.id}`);
      const nx = nextStage(); if (nx) S.view = nx.id;
      renderAll();
    };
    box.append(b);
  }
  return box;
}

function nextStage() {
  const i = S.stages.findIndex(x => x.id === S.view);
  return i >= 0 && i + 1 < S.stages.length ? S.stages[i + 1] : null;
}
function nextName() { return nextStage()?.name; }

/* ---------------- running a stage ---------------- */
async function runStage(id) {
  S.running = true; S.runningStage = id; S.trace = [];
  renderAll();

  const res = await fetch(`/api/sessions/${S.sess.id}/stage/${id}`, { method: 'POST' });
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
  while (true) {
    const { done, value } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split('\n\n'); buf = parts.pop();
    for (const p of parts) {
      if (!p.startsWith('data: ')) continue;
      let m; try { m = JSON.parse(p.slice(6)); } catch { continue; }
      if (m.type === 'event') {
        S.trace.push(m.data);
        const lt = document.querySelector('.livetrace');
        if (lt) { lt.append(traceRow(m.data)); lt.scrollTop = lt.scrollHeight; }
      } else if (m.type === 'stage_done') {
        S.sess = m.data;
      }
    }
  }
  S.running = false;
  renderAll();
}

/* ---------------- per-stage bodies ---------------- */
function bodyFor(stage) {
  const wrap = el('div');
  const items = S.sess.items;
  const dec = (id) => S.sess.decisions?.[id] || {};

  if (stage === 'breakdown') {
    wrap.append(note('Everything the agent flagged. Over-flagging is intentional — a missed item becomes an uninsurable film. Dismiss anything that is not a real clearance subject; dismissed items are excluded from research and never reach the report.'));
    items.forEach(it => wrap.append(itemCard(it, { dismiss: true })));
  }

  else if (stage === 'triage') {
    const ruled = items.filter(i => (S.sess.triage_notes?.[i.id] || '').startsWith('rule ·'));
    const researched = items.filter(i => S.sess.triage_notes?.[i.id] && !(S.sess.triage_notes[i.id]).startsWith('rule ·'));
    if (ruled.length) { wrap.append(group('Settled by rule — no lookup needed')); ruled.forEach(i => wrap.append(itemCard(i, { triage: true }))); }
    if (researched.length) { wrap.append(group(`Queued for live research — ${researched.length} lookups`)); researched.forEach(i => wrap.append(itemCard(i, { triage: true }))); }
    if (!ruled.length && !researched.length) wrap.append(note('Every item carried forward from the ledger — nothing needs re-clearing.'));
  }

  else if (stage === 'research') {
    const withEv = items.filter(i => S.sess.evidence?.[i.id]);
    if (!withEv.length) wrap.append(note('No new research was required for this draft.'));
    withEv.forEach(i => wrap.append(itemCard(i, { evidence: true })));
  }

  else if (stage === 'adjudicate') {
    wrap.append(note('Each ruling is made on the cited evidence. You are the adjudicator of record — overrule anything you disagree with, and your verdict is what the report prints.'));
    const order = ['must_change','license_required','legal_review','clear_with_caution','clear'];
    order.forEach(v => {
      const g = items.filter(i => effVerdict(i.id) === v);
      if (!g.length) return;
      wrap.append(group(`${VLABEL[v]} — ${g.length}`));
      g.forEach(i => wrap.append(itemCard(i, { verdict: true })));
    });
  }

  else if (stage === 'substitute') {
    const targets = items.filter(i => effVerdict(i.id) === 'must_change');
    if (!targets.length) wrap.append(note('Nothing is marked must-change, so no replacements are needed.'));
    else wrap.append(note('Each replacement was re-cleared through the same research and adjudication the original failed. Reject one and it will not appear in the report.'));
    targets.forEach(i => wrap.append(itemCard(i, { sub: true })));
  }

  else if (stage === 'report') {
    const counts = {};
    items.filter(i => !dec(i.id).dismissed).forEach(i => { const v = effVerdict(i.id); if (v) counts[v] = (counts[v] || 0) + 1; });
    const blocking = (counts.must_change||0)+(counts.license_required||0)+(counts.legal_review||0);
    const t = el('div', 'tally');
    VERDICTS.forEach(([k, l]) => { const dv = el('div'); dv.append(el('b', null, String(counts[k]||0)), document.createTextNode(l)); t.append(dv); });
    wrap.append(t);
    wrap.append(note(blocking
      ? `${blocking} item${blocking===1?'':'s'} must be resolved before an E&O policy can bind.`
      : 'No blocking items. This draft is clear for E&O submission.'));
    if (S.sess.report_id) {
      const a = el('a', 'dl', `Download ${S.sess.report_id}.pdf`);
      a.href = `/api/sessions/${S.sess.id}/report.pdf`; a.target = '_blank';
      wrap.append(a);
    }
  }
  return wrap;
}

function effVerdict(id) {
  const d = S.sess.decisions?.[id];
  if (d?.verdict_override) return d.verdict_override;
  return S.sess.rulings?.[id]?.verdict || null;
}

function note(text) { const n = el('div', 'rev'); n.append(el('div', 'why', text)); return n; }
function group(text) { return el('div', 'groupbar', text); }

/* ---------------- one reviewable item ---------------- */
function itemCard(it, mode) {
  const d = S.sess.decisions?.[it.id] || {};
  const adj = S.sess.rulings?.[it.id];
  const ev = S.sess.evidence?.[it.id];
  const sub = S.sess.substitutions?.[it.id];
  const v = effVerdict(it.id);

  const card = el('div', 'rev' + (d.dismissed ? ' dismissed' : '') + (v ? ' ' + VCLASS[v] : ''));

  const top = el('div', 'top');
  top.append(el('span', 'v', it.value), el('span', 'k', it.category.replace(/_/g, ' ')));
  const loc = (it.locations || []).slice(0, 4).map(l => 'p' + l.page + (l.scene_number ? ` sc.${l.scene_number}` : '')).join(', ');
  top.append(el('span', 'loc', loc));
  card.append(top);

  if (it.is_depicted_negatively) card.append(el('span', 'tag neg', 'depicted negatively'));
  if (S.sess.carried?.includes(it.id)) card.append(el('span', 'tag', 'carried from ledger'));

  if (it.locations?.[0]?.quote) card.append(el('div', 'q', it.locations[0].quote));

  if (mode.triage) {
    const t = S.sess.triage_notes?.[it.id] || '';
    card.append(el('div', t.startsWith('rule ·') ? 'why' : 'obj',
      t.startsWith('rule ·') ? `Settled deterministically — ${t.replace('rule · ','')}` : `Research objective: ${t}`));
  }

  if ((mode.evidence || mode.verdict) && ev) {
    if (mode.evidence) card.append(el('div', 'obj', `Objective: ${ev.objective.slice(0, 240)}`));
    if (ev.citations?.length) {
      const s = el('div', 'srcs');
      ev.citations.slice(0, mode.evidence ? 6 : 3).forEach(c => {
        const a = el('a', null, c.title || c.url);
        a.href = c.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        s.append(a);
      });
      card.append(s);
    }
  }

  if (mode.verdict && adj) {
    card.append(el('div', 'why', adj.rationale));
    if (adj.rule_applied) card.append(el('span', 'tag', adj.rule_applied));
    if (adj.requires_license_from) card.append(el('div', 'why', `Licence required from: ${adj.requires_license_from}`));
  }

  if (mode.sub) {
    if (sub?.verified_clear) {
      const f = el('div', 'fixbox');
      f.append(el('b', null, `Proposed: ${sub.proposed}`),
               document.createTextNode(` — re-cleared and verified (${sub.attempts} attempt${sub.attempts===1?'':'s'})`));
      if (sub.rejected_candidates?.length) f.append(el('div', 'rej', `Rejected on the way: ${sub.rejected_candidates.join(', ')}`));
      card.append(f);
    } else if (sub?.rejected_candidates?.length) {
      const f = el('div', 'fixbox none');
      f.append(el('div', 'rej', `No candidate verified clear. Tried: ${sub.rejected_candidates.join(', ')}`));
      card.append(f);
    } else if (sub) {
      const f = el('div', 'fixbox none');
      f.append(el('div', 'rej', 'No replacement could be proposed — this revision is the production’s call.'));
      card.append(f);
    }
  }

  /* ---- reviewer controls ---- */
  const acts = el('div', 'acts');

  if (mode.dismiss) {
    const b = el('button', 'act danger' + (d.dismissed ? ' on' : ''), d.dismissed ? 'Dismissed' : 'Not a clearance subject');
    b.onclick = () => decide(it.id, { dismissed: !d.dismissed });
    acts.append(b);
  }

  if (mode.verdict) {
    const keep = el('button', 'act good' + (!d.verdict_override ? ' on' : ''), 'Accept ruling');
    keep.onclick = () => decide(it.id, { verdict_override: '' });
    acts.append(keep);

    const sel = el('select', 'override');
    sel.append(el('option', null, 'Overrule to…'));
    VERDICTS.forEach(([k, l]) => {
      const o = el('option', null, l); o.value = k;
      if (d.verdict_override === k) o.selected = true;
      sel.append(o);
    });
    sel.onchange = () => { if (sel.value) decide(it.id, { verdict_override: sel.value }); };
    acts.append(sel);
  }

  if (mode.sub && sub) {
    const yes = el('button', 'act good' + (d.substitution_accepted === true ? ' on' : ''), 'Accept fix');
    yes.onclick = () => decide(it.id, { substitution_accepted: true });
    const no = el('button', 'act danger' + (d.substitution_accepted === false ? ' on' : ''), 'Reject fix');
    no.onclick = () => decide(it.id, { substitution_accepted: false });
    acts.append(yes, no);
  }

  if (acts.children.length) card.append(acts);
  if (d.verdict_override) card.append(el('div', 'overridden', `Overruled by reviewer → ${VLABEL[d.verdict_override]}`));

  return card;
}

async function decide(itemId, patch) {
  S.sess = await post(`/api/sessions/${S.sess.id}/items/${itemId}`, patch);
  renderAll();
}

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c])); }

boot();
