/* CLEARCUT — stage-gated clearance review.

   Every stage stops and waits for a person. Reviewer decisions are state,
   not annotations: a dismissed item never reaches research, an overruled
   verdict is what the report prints, a rejected fix is not offered. */

const $ = (s) => document.querySelector(s);
const el = (t, c, txt) => { const n = document.createElement(t); if (c) n.className = c; if (txt != null) n.textContent = txt; return n; };
const api = async (u, o) => { const r = await fetch(u, o); if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || r.statusText); return r.json(); };
const post = (u, b) => api(u, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(b||{}) });

const DRAFT_HUE = { White:'#FFFFFF', Blue:'#8FB4DA', Pink:'#E8A6BC', Yellow:'#E3D26A', Green:'#7FC08D', Goldenrod:'#D9B44A' };
const VERDICTS = [['must_change','Must change'],['license_required','Licence required'],['legal_review','Refer to counsel'],['clear_with_caution','Clear with caution'],['clear','Clear']];
const VLABEL = Object.fromEntries(VERDICTS);
const VCLASS = { must_change:'blocking', license_required:'licensed', legal_review:'review', clear_with_caution:'caution', clear:'ok' };

/* Plain-language guidance. A coordinator who has never seen this product
   should be able to work the whole pipeline from these three lines. */
const GUIDE = {
  breakdown: {
    what: 'Reads every page and flags each element that carries legal exposure — names, businesses, brands, addresses, phone numbers, plates, domains, songs, artwork, clips and real people.',
    why:  'Anything missed here is invisible for the rest of the process. A single uncleared element can hold up your <b>E&O policy</b>, and without E&O a distributor will not release the picture.',
    you:  'Skim the list and dismiss anything that is not genuinely a clearance subject. The agent deliberately over-flags — that is safer than under-flagging, but it means some noise reaches you.',
  },
  triage: {
    what: 'Sorts every flagged item into two piles: those settled by an industry rule, and those needing live verification against the web.',
    why:  'Rules are exact and free. Nobody researches whether 555-0142 is a real number — the block is reserved. Spending lookups only where evidence actually decides the outcome keeps a feature script affordable.',
    you:  'Check the research plan before it runs. Each objective is written around the legal theory for that category, not a generic keyword search.',
  },
  research: {
    what: 'Verifies each remaining subject against the live web through Parallel, returning citations you can open and read.',
    why:  'A ruling your insurer relies on has to be traceable to a source. A model cannot produce a USPTO registration number from memory — only a lookup can show it.',
    you:  'Open a few sources and confirm the evidence is on-point. If a subject came back thin, that is worth knowing before it is ruled on.',
  },
  adjudicate: {
    what: 'Issues one of five rulings on each subject, applying the standard that governs its category — tarnishment, defamation, public domain, sync-and-master, live referent.',
    why:  'Exposure is the product of two things: whether a real referent exists, <b>and how your script treats it</b>. A real company named in passing is usually fine. The same company shown committing fraud is not.',
    you:  'You are the adjudicator of record. Accept each ruling or overrule it — your verdict is what the report prints, and the report is what your carrier reads.',
  },
  substitute: {
    what: 'For everything you marked must-change, proposes a replacement and then re-clears that replacement through the same research and adjudication the original failed.',
    why:  'A clearance house tells you no. It does not tell you what to use instead, because vetting a replacement is another billable pass — so productions guess, and the next draft brings fresh problems.',
    you:  'Accept or reject each proposal. Rejected fixes do not appear in the report. Replacements preserve register, era and syllable count so dialogue still scans.',
  },
  report: {
    what: 'Assembles the page-cited clearance report, with every ruling carrying the sources behind it and every accepted replacement noted.',
    why:  'This is the document your E&O carrier requires before binding coverage, and the one production counsel signs off against.',
    you:  'Review the tally, then generate and download the PDF. Approving it commits these rulings to your clearance ledger, so the next draft only re-clears what actually changed.',
  },
};

const S = { drafts: [], draft: null, stages: [], sess: null, view: null, running: false, runningStage: null, trace: [], error: null, uploading: false };

/* ---------------- boot ---------------- */
async function boot() {
  try {
    const h = await api('/api/health');
    $('#d-gem').classList.add(h.gemini_configured ? 'on' : 'off');
    $('#d-par').classList.add(h.parallel_configured ? 'on' : 'off');
  } catch {}
  S.stages = await api('/api/stages');
  await loadDrafts();
  renderStart();
}

async function loadDrafts() {
  S.drafts = await api('/api/screenplays');
  if (!S.draft && S.drafts.length) S.draft = S.drafts[0].id;
}

/* ---------------- start screen ---------------- */
function renderStart() {
  $('#rail').hidden = true;
  $('#crumb').textContent = '';
  const m = $('#main'); m.innerHTML = '';
  const w = el('div', 'start');

  w.append(el('h1', null, 'Clear a screenplay'));
  const lede = el('p', 'lede');
  lede.innerHTML = 'Every production must obtain a <b>script clearance report</b> before an Errors &amp; Omissions insurer will bind coverage — and without E&amp;O, no distributor will release the picture. CLEARCUT runs that audit as a reviewed pipeline: six agents do the work, you approve every step.';
  w.append(lede);

  const ex = el('div', 'explain');
  [['01','Upload a draft','Final Draft PDF, Fountain, or plain text. Scene and page numbers are read straight off the page.'],
   ['02','Approve each stage','Nothing advances without you. Dismiss false flags, overrule rulings, reject fixes you do not want.'],
   ['03','Deliver the report','A page-cited PDF with sources behind every ruling — and a ledger so the next draft only re-clears what changed.']]
   .forEach(([n,h,p]) => {
     const c = el('div','ex'); c.append(el('div','n',n), el('h4',null,h), el('p',null,p)); ex.append(c);
   });
  w.append(ex);

  if (S.error) w.append(el('div', 'err-inline', S.error));

  /* upload */
  const up = el('div', 'panel');
  up.append(el('h3', null, 'Upload your screenplay'));
  up.append(el('div', 'hint', 'PDF, .fountain or .txt, up to 25 MB. Your file stays on this deployment — it is parsed locally and only the flagged subjects are ever sent for verification.'));
  const drop = el('label', 'drop');
  const inp = el('input'); inp.type = 'file'; inp.accept = '.pdf,.fountain,.txt';
  drop.append(inp,
    el('div', 'big', S.uploading ? 'Reading screenplay…' : 'Choose a file or drop it here'),
    el('div', 'sm', 'Final Draft exports work as-is — revision colour and draft date are detected automatically.'));
  inp.onchange = () => inp.files[0] && doUpload(inp.files[0]);
  ['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
  ['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', ev => { const f = ev.dataTransfer?.files?.[0]; if (f) doUpload(f); });
  up.append(drop);
  w.append(up);

  w.append(el('div', 'orbar', 'or start from a sample'));

  const pick = el('div', 'panel');
  pick.append(el('h3', null, 'Your scripts'));
  pick.append(el('div', 'hint', 'Drafts of the same picture share a clearance ledger, so a revision is measured against the draft before it.'));
  const list = el('div');
  S.drafts.forEach(d => list.append(draftCard(d)));
  pick.append(list);

  const go = el('button', 'btn wide', 'Open clearance session');
  go.style.marginTop = '14px';
  go.disabled = !S.draft;
  go.onclick = openSession;
  pick.append(go);
  w.append(pick);

  m.append(w);
}

function draftCard(d) {
  const b = el('button', 'draft' + (d.id === S.draft ? ' sel' : ''));
  const sw = el('span', 'swatch'); sw.style.background = DRAFT_HUE[d.draft] || '#C9C5B8';
  const body = el('div');
  body.append(el('div', 't', d.title || d.original_name || d.id));
  const bits = [d.draft && `${d.draft} draft`, d.date, `${d.pages} page${d.pages === 1 ? '' : 's'}`, d.original_name].filter(Boolean);
  body.append(el('div', 'm', bits.join(' · ')));
  b.append(sw, body);
  b.append(el('span', 'chip', d.sample ? 'Sample' : 'Uploaded'));
  b.onclick = () => { S.draft = d.id; renderStart(); };
  return b;
}

async function doUpload(file) {
  S.uploading = true; S.error = null; renderStart();
  try {
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch('/api/upload', { method: 'POST', body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || 'Upload failed');
    await loadDrafts();
    S.draft = j.id;
  } catch (e) { S.error = e.message; }
  S.uploading = false;
  renderStart();
}

async function openSession() {
  try {
    S.sess = await post('/api/sessions', { screenplay: S.draft });
    S.view = 'breakdown'; S.trace = []; S.error = null;
    $('#rail').hidden = false;
    renderAll();
  } catch (e) { S.error = e.message; renderStart(); }
}

$('#newsess').onclick = () => { S.sess = null; S.view = null; S.trace = []; renderStart(); };

/* ---------------- rail ---------------- */
const stState = (id) => S.sess?.stages?.[id] || { status: 'pending' };
const unlocked = (i) => i === 0 || stState(S.stages[i-1].id).status === 'approved';

function renderRail() {
  const box = $('#steps'); box.innerHTML = '';
  S.stages.forEach((st, i) => {
    const s = stState(st.id), open = unlocked(i);
    let cls = '', label = 'Locked until the step above is approved';
    if (open) {
      if (s.status === 'approved') { cls='done'; label='Approved'; }
      else if (s.status === 'awaiting_review') { cls='review'; label='Needs your review'; }
      else if (s.status === 'running') { cls='busy'; label='Running…'; }
      else if (s.status === 'error') { cls='err'; label='Failed — can retry'; }
      else label = 'Ready to run';
    }
    const b = el('button', `step ${cls}` + (open?'':' locked') + (S.view===st.id?' sel':''));
    const body = el('div');
    body.append(el('div','nm',st.name), el('div','stat',label));
    b.append(el('div','ix', s.status==='approved' ? '✓' : String(i+1)), body);
    if (open) b.onclick = () => { S.view = st.id; renderAll(); };
    box.append(b);
  });

  const m = $('#meta'); m.innerHTML = '';
  const row = (k,v) => { const r = el('div','metarow'); r.append(el('span',null,k), el('b',null,String(v))); m.append(r); };
  const sc = S.sess.script;
  row('Title', sc.title);
  if (sc.draft_label) row('Draft', sc.draft_label);
  row('Pages', sc.page_count);
  row('Flagged', S.sess.items.length);
  const dec = Object.values(S.sess.decisions||{});
  const dism = dec.filter(d=>d.dismissed).length; if (dism) row('Dismissed', dism);
  const ov = dec.filter(d=>d.verdict_override).length; if (ov) row('Your overrides', ov);
  if (S.sess.carried?.length) row('From ledger', S.sess.carried.length);

  $('#crumb').innerHTML = `<b>${esc(sc.title)}</b>${sc.draft_label ? ' · ' + esc(sc.draft_label) + ' draft' : ''}`;
}

/* ---------------- detail ---------------- */
function renderAll() { renderRail(); renderDetail(); }

function renderDetail() {
  const meta = S.stages.find(x => x.id === S.view);
  const m = $('#main'); m.innerHTML = '';
  if (!meta) return;
  const st = stState(S.view);
  const d = el('div', 'detail');

  const head = el('div','dhead');
  head.append(el('div','kicker',`Step ${S.stages.findIndex(x=>x.id===meta.id)+1} of ${S.stages.length}`));
  const h = el('h2'); h.append(document.createTextNode(meta.name));
  const bc = {approved:'done',awaiting_review:'review',running:'busy',error:'err'}[st.status] || '';
  const bt = {approved:'Approved',awaiting_review:'Needs your review',running:'Running',error:'Failed'}[st.status] || 'Not run yet';
  h.append(el('span','badge '+bc, bt));
  head.append(h);
  d.append(head);

  const g = GUIDE[meta.id];
  if (g) {
    const box = el('div','guide'); const dl = el('dl');
    const pair = (k, html) => { dl.append(el('dt',null,k)); const dd = el('dd'); dd.innerHTML = html; dl.append(dd); };
    pair('What this does', g.what);
    pair('Why it matters', g.why);
    pair('Your job here', g.you);
    box.append(dl); d.append(box);
  }

  if (st.error) d.append(el('div','err-inline', st.error.slice(0,400)));
  if (st.summary) d.append(el('div','sumline', st.summary));

  if (S.running && S.runningStage === S.view) {
    const t = el('div','livetrace');
    S.trace.forEach(e => t.append(traceRow(e)));
    d.append(t);
  }

  if (st.status === 'pending' || st.status === 'error') d.append(runPrompt(meta));
  else { d.append(bodyFor(S.view)); d.append(gate(meta, st)); }

  m.append(d);
  const lt = d.querySelector('.livetrace'); if (lt) lt.scrollTop = lt.scrollHeight;
}

function traceRow(e) {
  const r = el('div', `ev ${e.agent}` + (e.phase==='error'?' err':''));
  r.append(el('div','who',e.agent));
  const msg = el('div','msg');
  msg.innerHTML = esc(e.message).replace(/\b(\d+)\b/g,'<em>$1</em>');
  r.append(msg);
  return r;
}

function runPrompt(meta) {
  const box = el('div','gate');
  box.append(el('div','ask', S.running ? 'Working…' : 'Nothing has run for this step yet.'));
  const b = el('button','btn', S.running ? 'Working…' : `Run ${meta.name.toLowerCase()}`);
  b.disabled = S.running;
  b.onclick = () => runStage(meta.id);
  box.append(b);
  return box;
}

function gate(meta, st) {
  const box = el('div','gate');
  if (st.status === 'approved') {
    const nx = nextStage();
    box.append(el('div','ask', nx ? `Approved. Next: ${nx.name}.` : 'Pipeline complete.'));
    if (nx) { const b = el('button','btn',`Continue to ${nx.name}`); b.onclick = () => { S.view = nx.id; renderAll(); }; box.append(b); }
  } else {
    const ask = el('div','ask');
    ask.innerHTML = `<b>Your approval is required.</b> ${esc(meta.gate)}`;
    box.append(ask);
    const b = el('button','btn gold','Approve & continue');
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
  return i >= 0 && i+1 < S.stages.length ? S.stages[i+1] : null;
}

/* ---------------- run a stage ---------------- */
async function runStage(id) {
  S.running = true; S.runningStage = id; S.trace = [];
  renderAll();
  try {
    const res = await fetch(`/api/sessions/${S.sess.id}/stage/${id}`, { method:'POST' });
    const rd = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { done, value } = await rd.read(); if (done) break;
      buf += dec.decode(value, { stream:true });
      const parts = buf.split('\n\n'); buf = parts.pop();
      for (const p of parts) {
        if (!p.startsWith('data: ')) continue;
        let msg; try { msg = JSON.parse(p.slice(6)); } catch { continue; }
        if (msg.type === 'event') {
          S.trace.push(msg.data);
          const lt = document.querySelector('.livetrace');
          if (lt) { lt.append(traceRow(msg.data)); lt.scrollTop = lt.scrollHeight; }
        } else if (msg.type === 'stage_done') S.sess = msg.data;
      }
    }
  } catch (e) { S.error = e.message; }
  S.running = false;
  renderAll();
}

/* ---------------- stage bodies ---------------- */
function bodyFor(stage) {
  const w = el('div');
  const items = S.sess.items;
  const dec = (id) => S.sess.decisions?.[id] || {};

  if (stage === 'breakdown') {
    items.forEach(i => w.append(card(i, { dismiss:true })));
  }

  else if (stage === 'triage') {
    const notes = S.sess.triage_notes || {};
    const ruled = items.filter(i => (notes[i.id]||'').startsWith('rule ·'));
    const res = items.filter(i => notes[i.id] && !notes[i.id].startsWith('rule ·'));
    if (ruled.length) { w.append(gbar(`Settled by rule — ${ruled.length}, no lookup spent`)); ruled.forEach(i => w.append(card(i,{triage:true}))); }
    if (res.length) { w.append(gbar(`Queued for live verification — ${res.length}`)); res.forEach(i => w.append(card(i,{triage:true}))); }
    if (!ruled.length && !res.length) w.append(msg('Every subject carried forward from your ledger — nothing in this draft needs re-clearing.'));
  }

  else if (stage === 'research') {
    const got = items.filter(i => S.sess.evidence?.[i.id]);
    if (!got.length) w.append(msg('No new verification was required for this draft.'));
    got.forEach(i => w.append(card(i,{evidence:true})));
  }

  else if (stage === 'adjudicate') {
    VERDICTS.forEach(([v,l]) => {
      const g = items.filter(i => !dec(i.id).dismissed && eff(i.id) === v);
      if (!g.length) return;
      w.append(gbar(`${l} — ${g.length}`));
      g.forEach(i => w.append(card(i,{verdict:true})));
    });
  }

  else if (stage === 'substitute') {
    const t = items.filter(i => !dec(i.id).dismissed && eff(i.id) === 'must_change');
    if (!t.length) w.append(msg('Nothing is marked must-change, so there is nothing to replace.'));
    t.forEach(i => w.append(card(i,{sub:true})));
  }

  else if (stage === 'report') {
    const counts = {};
    items.filter(i => !dec(i.id).dismissed).forEach(i => { const v = eff(i.id); if (v) counts[v] = (counts[v]||0)+1; });
    const blocking = (counts.must_change||0)+(counts.license_required||0)+(counts.legal_review||0);
    const t = el('div','tally');
    VERDICTS.forEach(([k,l]) => { const c = el('div', k==='must_change'?'must':k); c.append(el('b',null,String(counts[k]||0)), el('span',null,l)); t.append(c); });
    w.append(t);
    w.append(msg(blocking
      ? `${blocking} item${blocking===1?'':'s'} must be resolved before an E&O policy can bind on this draft.`
      : 'No blocking items. This draft is clear for E&O submission.'));
    if (S.sess.report_id) {
      const a = el('a','btn gold',`Download ${S.sess.report_id}.pdf`);
      a.href = `/api/sessions/${S.sess.id}/report.pdf`; a.target = '_blank';
      a.style.textDecoration = 'none'; a.style.display = 'inline-block';
      w.append(a);
    }
  }
  return w;
}

const eff = (id) => S.sess.decisions?.[id]?.verdict_override || S.sess.rulings?.[id]?.verdict || null;
const msg = (t) => { const n = el('div','rev'); n.append(el('div','why',t)); return n; };
const gbar = (t) => el('div','groupbar',t);

/* ---------------- a reviewable subject ---------------- */
function card(it, mode) {
  const d = S.sess.decisions?.[it.id] || {};
  const adj = S.sess.rulings?.[it.id], ev = S.sess.evidence?.[it.id], sub = S.sess.substitutions?.[it.id];
  const v = eff(it.id);
  const c = el('div','rev' + (d.dismissed?' dismissed':'') + (v?' '+VCLASS[v]:''));

  const top = el('div','top');
  top.append(el('span','v',it.value), el('span','k',it.category.replace(/_/g,' ')));
  top.append(el('span','loc',(it.locations||[]).slice(0,4).map(l=>'p'+l.page+(l.scene_number?` sc.${l.scene_number}`:'')).join(', ')));
  c.append(top);

  if (it.is_depicted_negatively) c.append(el('span','tag neg','depicted negatively'));
  if (S.sess.carried?.includes(it.id)) c.append(el('span','tag carried','carried from ledger'));

  if (it.locations?.[0]?.quote) c.append(el('div','q',it.locations[0].quote));

  if (mode.triage) {
    const t = S.sess.triage_notes?.[it.id] || '';
    c.append(t.startsWith('rule ·')
      ? el('div','why',`Settled deterministically — ${t.replace('rule · ','')}. No lookup needed.`)
      : el('div','obj',`Will ask: ${t.slice(0,300)}`));
  }

  if ((mode.evidence || mode.verdict) && ev) {
    if (mode.evidence) c.append(el('div','obj',`Objective: ${ev.objective.slice(0,260)}`));
    if (ev.citations?.length) {
      const s = el('div','srcs');
      ev.citations.slice(0, mode.evidence?6:3).forEach(ct => {
        const a = el('a',null,ct.title || ct.url);
        a.href = ct.url; a.target='_blank'; a.rel='noopener noreferrer';
        s.append(a);
      });
      c.append(s);
    }
  }

  if (mode.verdict && adj) {
    c.append(el('div','why',adj.rationale));
    if (adj.rule_applied) c.append(el('span','tag',adj.rule_applied));
    if (adj.requires_license_from) c.append(el('div','why',`Licence required from: ${adj.requires_license_from}`));
  }

  if (mode.sub) {
    if (sub?.verified_clear) {
      const f = el('div','fixbox');
      f.append(el('b',null,`Proposed: ${sub.proposed}`), document.createTextNode(` — re-cleared and verified in ${sub.attempts} attempt${sub.attempts===1?'':'s'}`));
      if (sub.rejected_candidates?.length) f.append(el('div','rej',`Rejected on the way: ${sub.rejected_candidates.join(', ')}`));
      c.append(f);
    } else if (sub?.rejected_candidates?.length) {
      const f = el('div','fixbox none');
      f.append(el('b',null,'No candidate verified clear.'), el('div','rej',`Tried: ${sub.rejected_candidates.join(', ')}`));
      c.append(f);
    } else if (sub) {
      const f = el('div','fixbox none');
      f.append(el('b',null,'No replacement proposed.'), el('div','rej','This revision is the production’s call.'));
      c.append(f);
    }
  }

  const acts = el('div','acts');
  if (mode.dismiss) {
    acts.append(el('span','prompt','Is this a real clearance subject?'));
    const b = el('button','act danger'+(d.dismissed?' on':''), d.dismissed?'Dismissed — click to restore':'Not a clearance subject');
    b.onclick = () => decide(it.id,{ dismissed: !d.dismissed });
    acts.append(b);
  }
  if (mode.verdict) {
    acts.append(el('span','prompt','Your ruling:'));
    const keep = el('button','act good'+(!d.verdict_override?' on':''),'Accept');
    keep.onclick = () => decide(it.id,{ verdict_override:'' });
    acts.append(keep);
    const sel = el('select','override');
    const ph = el('option',null,'Overrule to…'); ph.value = ''; sel.append(ph);
    VERDICTS.forEach(([k,l]) => { const o = el('option',null,l); o.value = k; if (d.verdict_override===k) o.selected = true; sel.append(o); });
    sel.onchange = () => { if (sel.value) decide(it.id,{ verdict_override: sel.value }); };
    acts.append(sel);
  }
  if (mode.sub && sub) {
    acts.append(el('span','prompt','Use this replacement?'));
    const y = el('button','act good'+(d.substitution_accepted===true?' on':''),'Accept fix');
    y.onclick = () => decide(it.id,{ substitution_accepted:true });
    const n = el('button','act danger'+(d.substitution_accepted===false?' on':''),'Reject fix');
    n.onclick = () => decide(it.id,{ substitution_accepted:false });
    acts.append(y,n);
  }
  if (acts.children.length) c.append(acts);
  if (d.verdict_override) c.append(el('div','overridden',`Overruled by you → ${VLABEL[d.verdict_override]}`));
  return c;
}

async function decide(id, patch) {
  S.sess = await post(`/api/sessions/${S.sess.id}/items/${id}`, patch);
  renderAll();
}

function esc(s){ return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

boot();
