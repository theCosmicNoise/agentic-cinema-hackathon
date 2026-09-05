/* CLEARCUT: stage-gated clearance review.

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
    what: 'Reads every page and marks each element that carries legal exposure: character and company names, brands, addresses, phone numbers, plates, domains, songs, artwork, clips, and references to real people.',
    why:  'Whatever is missed here stays invisible for the rest of the process. One uncleared element can hold up your <b>E&O policy</b>, and no distributor will release a picture without one.',
    you:  'Read the list and dismiss anything that is not really a clearance subject. The agent flags generously on purpose. Missing an item is far more expensive than reading a few extra.',
  },
  triage: {
    what: 'Splits the list in two: items an industry rule already settles, and items that need checking against live sources.',
    why:  'Rules are exact and cost nothing. Nobody researches whether 555-0142 belongs to someone, because that block is reserved for fiction. Spending lookups only where evidence changes the answer is what keeps a feature-length script affordable.',
    you:  'Look at what is queued before it runs. Each question is framed around the legal test for that kind of item, not just the words on the page.',
  },
  research: {
    what: 'Checks each remaining subject against live sources through Parallel and brings back citations you can open.',
    why:  'Your insurer relies on these rulings, so each one has to trace back to something real. A model cannot produce a USPTO registration number from memory. Only a lookup can.',
    you:  'Open a few sources and check they are on point. If a subject came back thin, better to know that now than after the ruling.',
  },
  adjudicate: {
    what: 'Rules on each subject using the test that governs its category: tarnishment, defamation, public domain, sync and master rights, or whether a real referent exists.',
    why:  'Two things create exposure: a real referent, <b>and how your script treats it</b>. A real company mentioned in passing is usually fine. The same company shown committing fraud is not.',
    you:  'You are the adjudicator of record. Accept a ruling or overrule it. What you decide is what the report prints, and the report is what your carrier reads.',
  },
  substitute: {
    what: 'Takes everything you marked must-change, proposes a replacement, then puts that replacement through the same research and ruling the original just failed.',
    why:  'A clearance house tells you no. It rarely tells you what to use instead, because vetting a replacement is another billable pass. So productions guess, and the next draft arrives with new problems.',
    you:  'Accept or reject each proposal. Rejected ones stay out of the report. Replacements are built to keep the register, period and syllable count so dialogue still reads.',
  },
  report: {
    what: 'Builds the page-cited clearance report, with sources under every ruling and any replacement you accepted written in.',
    why:  'This is the document your E&O carrier asks for before binding coverage, and what production counsel signs against.',
    you:  'Check the tally, then generate the PDF. Approving it writes these rulings into your clearance ledger, so the next draft only re-checks what actually changed.',
  },
};

const S = { deep: false, buckets: [], open: {}, history: [], drafts: [], draft: null, stages: [], sess: null, view: null, running: false, runningStage: null, trace: [], error: null, uploading: false };

/* ---------------- boot ---------------- */
async function boot() {
  try {
    const h = await api('/api/health');
    $('#d-gem').classList.add(h.gemini_configured ? 'on' : 'off');
    $('#d-par').classList.add(h.parallel_configured ? 'on' : 'off');
  } catch {}
  S.stages = await api('/api/stages');
  S.buckets = await api('/api/buckets');
  await loadHistory();
  await loadDrafts();
  renderStart();
}

async function loadHistory() {
  try { S.history = await api('/api/sessions'); } catch { S.history = []; }
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
  lede.innerHTML = 'No carrier will bind E&amp;O without a <b>script clearance report</b>, and no distributor will take the picture without E&amp;O. The traditional route means weeks of waiting, and a fresh invoice every time the pages change. CLEARCUT runs the same audit against live sources, and nothing lands in the report until you have signed off on it.';
  w.append(lede);

  const ex = el('div', 'explain');
  [['01','Send us the draft',
    "Final Draft exports, Fountain files or plain text. We read your scene numbers and pagination off the page, so every finding tells you exactly where to look."],
   ['02','Rule on it yourself',
    "You are the adjudicator of record. Clear a false flag, overrule anything you disagree with, turn down a replacement you don't want."],
   ['03','Hand it to your carrier',
    "A page-cited report with the sources behind every ruling. When the pink pages arrive, only what actually changed gets checked again."]]
   .forEach(([n,h,p]) => {
     const c = el('div','ex'); c.append(el('div','n',n), el('h4',null,h), el('p',null,p)); ex.append(c);
   });
  w.append(ex);

  if (S.error) w.append(el('div', 'err-inline', S.error));

  /* upload */
  const up = el('div', 'panel');
  up.append(el('h3', null, 'Upload your screenplay'));
  up.append(el('div', 'hint', "PDF, Fountain or plain text, up to 25 MB. Your script is read here and stays here. The only thing that ever leaves is a name we need to check, never a page of your screenplay."));
  const drop = el('label', 'drop');
  const inp = el('input'); inp.type = 'file'; inp.accept = '.pdf,.fountain,.txt';
  drop.append(inp,
    el('div', 'big', S.uploading ? 'Reading screenplay…' : 'Choose a file or drop it here'),
    el('div', 'sm', "Straight from Final Draft is fine. We'll pick up the revision colour and draft date ourselves."));
  inp.onchange = () => inp.files[0] && doUpload(inp.files[0]);
  ['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
  ['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', ev => { const f = ev.dataTransfer?.files?.[0]; if (f) doUpload(f); });
  up.append(drop);
  w.append(up);

  w.append(el('div', 'orbar', 'or try one of ours'));

  const pick = el('div', 'panel');
  pick.append(el('h3', null, 'Your scripts'));
  pick.append(el('div', 'hint', 'Drafts of the same picture share one ledger, so every revision is checked against the draft before it rather than from scratch.'));
  const list = el('div');
  S.drafts.forEach(d => list.append(draftCard(d)));
  pick.append(list);

  const go = el('button', 'btn wide', 'Start clearance');
  go.style.marginTop = '14px';
  go.disabled = !S.draft;
  go.onclick = openSession;
  pick.append(go);
  w.append(pick);

  if (S.history.length) w.append(historyPanel());

  m.append(w);
}

function draftCard(d) {
  // A row rather than a button, so the remove control can sit inside it
  // without nesting one interactive element in another.
  const row = el('div', 'draft' + (d.id === S.draft ? ' sel' : ''));
  row.setAttribute('role', 'button');
  row.tabIndex = 0;

  const sw = el('span', 'swatch'); sw.style.background = DRAFT_HUE[d.draft] || '#C9C5B8';
  const body = el('div');
  body.append(el('div', 't', d.title || d.original_name || d.id));
  const bits = [d.draft && `${d.draft} draft`, d.date, `${d.pages} page${d.pages === 1 ? '' : 's'}`, d.original_name].filter(Boolean);
  body.append(el('div', 'm', bits.join(' · ')));
  row.append(sw, body);

  // Chip and remove control share one trailing group. Previously the chip
  // claimed the free space with margin-left:auto and the button was appended
  // after it, so the two overlapped.
  const tail = el('div', 'dtail');
  tail.append(el('span', 'chip', d.sample ? 'Sample' : 'Uploaded'));

  const pick = () => { S.draft = d.id; renderStart(); };
  row.onclick = pick;
  row.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } };

  // Samples are read-only fixtures; only uploads can be removed.
  if (!d.sample) {
    const x = el('button', 'remove', '\u00d7');
    x.title = `Remove ${d.title || d.id}`;
    x.setAttribute('aria-label', `Remove ${d.title || d.id}`);
    x.onclick = (e) => { e.stopPropagation(); confirmRemove(d); };
    tail.append(x);
  }
  row.append(tail);
  return row;
}

async function confirmRemove(d) {
  const name = d.title || d.original_name || d.id;
  if (!window.confirm(
    `Remove "${name}"?\n\nThe screenplay file and any unfinished review sessions ` +
    `for it are deleted. Clearance rulings already committed to your ledger are kept.`
  )) return;
  try {
    const r = await fetch(`/api/screenplays/${d.id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Could not remove');
    if (S.draft === d.id) S.draft = null;
    await loadDrafts();
    S.error = null;
  } catch (e) { S.error = e.message; }
  renderStart();
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


/* ---------------- history ----------------
   A production comes back to answer "what did we decide about the blue pages".
   So a past run is reopenable at the step it stopped on, with every decision
   the reviewer made still attached and still editable. */
function historyPanel() {
  const box = el('div','panel');
  box.append(el('h3', null, 'Previous runs'));
  box.append(el('div','hint',
    'Reopen a run to see what was decided. Approved steps stay approved, and your dismissals and overrides can still be changed.'));

  S.history.forEach(h => box.append(historyRow(h)));
  return box;
}

function historyRow(h) {
  const row = el('div','hrow');

  const main = el('div','hmain');
  const t1 = el('div','ht');
  t1.append(document.createTextNode(h.title || h.screenplay_id));
  if (h.draft) t1.append(el('span','hdraft', h.draft));
  main.append(t1);

  const bits = [];
  bits.push(h.complete ? 'Complete' : `Stopped at ${cap(h.current_stage || 'start')}`);
  bits.push(`${h.stages_done}/${h.stages_total} steps`);
  bits.push(`${h.items} items`);
  if (h.blocking) bits.push(`${h.blocking} blocking`);
  if (h.overrides) bits.push(`${h.overrides} override${h.overrides===1?'':'s'}`);
  if (h.dismissed) bits.push(`${h.dismissed} dismissed`);
  bits.push(when(h.updated_at));
  main.append(el('div','hm', bits.join(' · ')));
  row.append(main);

  const acts = el('div','hacts');
  const open = el('button','act','Reopen');
  open.onclick = () => resume(h.id);
  acts.append(open);

  if (h.report_id) {
    const pdf = el('a','act', 'Report');
    pdf.href = `/api/sessions/${h.id}/report.pdf`;
    pdf.target = '_blank';
    acts.append(pdf);
  }

  const del = el('button','act danger-hover','Discard');
  del.onclick = async () => {
    if (!confirm(`Discard this run of ${h.title}? Decisions in it are lost. Your clearance ledger is not affected.`)) return;
    await fetch(`/api/sessions/${h.id}`, { method:'DELETE' });
    await loadHistory();
    renderStart();
  };
  acts.append(del);
  row.append(acts);
  return row;
}

async function resume(sid) {
  try {
    S.sess = await api('/api/sessions/' + sid);
    // Land on the step that still needs work, not back at the beginning.
    const pending = S.stages.find(st => stState(st.id).status !== 'approved');
    S.view = pending ? pending.id : S.stages[S.stages.length - 1].id;
    S.trace = []; S.error = null;
    document.querySelector('#rail').hidden = false;
    renderAll();
  } catch (e) { S.error = e.message; renderStart(); }
}

const cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);

function when(iso) {
  const d = new Date(iso), mins = (Date.now() - d) / 60000;
  if (mins < 1) return 'just now';
  if (mins < 60) return `${Math.round(mins)} min ago`;
  if (mins < 1440) return `${Math.round(mins/60)} h ago`;
  return d.toLocaleDateString(undefined, { month:'short', day:'numeric' });
}

async function openSession() {
  try {
    S.sess = await post('/api/sessions', { screenplay: S.draft });
    S.view = 'breakdown'; S.trace = []; S.error = null;
    $('#rail').hidden = false;
    renderAll();
  } catch (e) { S.error = e.message; renderStart(); }
}

function goHome() {
  S.sess = null; S.view = null; S.trace = []; S.error = null;
  renderStart();
}
$('#newsess').onclick = goHome;
$('#home').onclick = goHome;

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
      else if (s.status === 'error') { cls='err'; label='Failed, can retry'; }
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
  const wrap = el('div');

  // Research is the one step where the production chooses how much effort to
  // buy, so the trade-off is stated in full rather than hidden behind a toggle.
  if (meta.id === 'research') wrap.append(enginePicker());

  const box = el('div','gate');
  box.append(el('div','ask', S.running ? 'Working…' : 'Nothing has run for this step yet.'));
  const b = el('button','btn', S.running ? 'Working…' : `Run ${meta.name.toLowerCase()}`);
  b.disabled = S.running;
  b.onclick = () => runStage(meta.id, meta.id === 'research' ? S.deep : false);
  box.append(b);
  wrap.append(box);
  return wrap;
}

function enginePicker() {
  const n = Object.values(S.sess.triage_notes || {})
    .filter(x => !String(x).startsWith('rule ·')).length;
  const box = el('div','engine');
  box.append(el('div','label','How hard should it look?'));

  [['fast', 'One search per subject',
    `About ${Math.max(1, Math.round(n * 3 / 60))} to ${Math.max(2, Math.round(n * 8 / 60))} minutes for ${n} subjects. One web search each, framed on the category. Enough for most drafts.`],
   ['deep', 'Agent-directed investigation',
    `Roughly ${Math.max(2, Math.round(n * 60 / 60 / 5))} to ${Math.max(4, Math.round(n * 100 / 60 / 5))} minutes. The agent picks its own depth: one search for a common surname, multi-hop research for a music cue or a company your script shows doing something wrong. Use this on a draft going to your insurer.`]]
  .forEach(([k, title, blurb]) => {
    const on = (k === 'deep') === !!S.deep;
    const b = el('button','opt' + (on ? ' on' : ''));
    b.append(el('div','ot', title), el('div','ob', blurb));
    b.onclick = () => { S.deep = (k === 'deep'); renderAll(); };
    box.append(b);
  });
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
async function runStage(id, deep) {
  S.running = true; S.runningStage = id; S.trace = [];
  renderAll();
  try {
    const q = deep ? '?deep=true' : '';
    const res = await fetch(`/api/sessions/${S.sess.id}/stage/${id}${q}`, { method:'POST' });
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
  await loadHistory();
  renderAll();
}

/* ---------------- stage bodies ---------------- */
function bodyFor(stage) {
  const w = el('div');
  const items = S.sess.items;
  const dec = (id) => S.sess.decisions?.[id] || {};

  if (stage === 'breakdown') {
    w.append(grouped(items, { dismiss:true }, list => {
      const d = list.filter(i => dec(i.id).dismissed).length;
      return d ? `${list.length - d} kept · ${d} dismissed` : `${list.length}`;
    }));
  }

  else if (stage === 'triage') {
    const notes = S.sess.triage_notes || {};
    const ruled = items.filter(i => (notes[i.id]||'').startsWith('rule ·'));
    const res = items.filter(i => notes[i.id] && !notes[i.id].startsWith('rule ·'));
    if (ruled.length) { w.append(gbar(`Settled by rule (${ruled.length}), no lookup spent`)); ruled.forEach(i => w.append(card(i,{triage:true}))); }
    if (res.length) { w.append(gbar(`Queued for live verification (${res.length})`)); res.forEach(i => w.append(card(i,{triage:true}))); }
    if (!ruled.length && !res.length) w.append(msg('Every subject carried forward from your ledger. Nothing in this draft needs re-checking.'));
  }

  else if (stage === 'research') {
    const got = items.filter(i => S.sess.evidence?.[i.id]);
    if (!got.length) w.append(msg('No new verification was required for this draft.'));
    else w.append(grouped(got, { evidence:true }, list => {
      const src = list.reduce((n,i) => n + (S.sess.evidence?.[i.id]?.citations?.length || 0), 0);
      return `${list.length} · ${src} sources`;
    }));
  }

  else if (stage === 'adjudicate') {
    const live = items.filter(i => !dec(i.id).dismissed);

    // Two legitimate ways to work this list: by ruling, because the blockers
    // are what stop the picture, or by type, because that is how the work gets
    // handed to departments. Ruling is the default.
    const ax = el('div','axis');
    ax.append(el('span','lbl','Group by'));
    [['ruling','Ruling'],['type','Type']].forEach(([k,lbl]) => {
      const b = el('button','axopt' + ((S.axis||'ruling')===k ? ' on':''), lbl);
      b.onclick = () => { S.axis = k; renderAll(); };
      ax.append(b);
    });
    w.append(ax);

    if ((S.axis||'ruling') === 'type') {
      w.append(grouped(live, { verdict:true }, list => {
        const block = list.filter(i => ['must_change','license_required','legal_review'].includes(eff(i.id))).length;
        return block ? `${list.length} · ${block} blocking` : `${list.length} · all clear`;
      }));
    } else {
      VERDICTS.forEach(([v,l]) => {
        const g = live.filter(i => eff(i.id) === v);
        if (!g.length) return;
        w.append(gbar(`${l} (${g.length})`));
        g.forEach(i => w.append(card(i,{verdict:true})));
      });
    }
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


/* ---------------- buckets ----------------
   Seventeen categories is the right vocabulary for the legal theory and the
   wrong one for the person reviewing. Group by who has to act. */
function scrollToBucket(id, afterRender) {
  const go = () => {
    const node = document.getElementById(`bucket-${id}`);
    if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  // Two frames when the DOM was just replaced, so layout has settled first.
  if (afterRender) requestAnimationFrame(() => requestAnimationFrame(go));
  else go();
}

function bucketOf(cat) {
  const b = S.buckets.find(x => (x.categories || []).includes(cat));
  return b ? b.id : 'other';
}

function byBucket(items) {
  const m = new Map();
  items.forEach(i => {
    const k = bucketOf(i.category);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(i);
  });
  // Preserve the taxonomy's order rather than insertion order.
  return S.buckets.map(b => [b, m.get(b.id) || []]).filter(([, v]) => v.length);
}

/* Render items grouped into collapsible sections. `count` labels the badge,
   letting each stage say what its own numbers mean. */
function grouped(items, mode, count) {
  const wrap = el('div');
  const groups = byBucket(items);
  if (!groups.length) return wrap;

  // A 200-item script is unreadable without a fixed handle on it, so the
  // toolbar sticks and carries jump links. Scrolling back to the top to reach
  // another section is the thing that makes a long list feel unusable.
  const bar = el('div', 'bulk');

  const left = el('div', 'bleft');
  left.append(el('span', 'btotal', `${items.length} items`));
  left.append(el('span', 'bsep'));
  groups.forEach(([b, list]) => {
    const jump = el('button', 'bjump');
    jump.append(document.createTextNode(b.name), el('span', 'bjn', String(list.length)));
    jump.title = `Jump to ${b.name}`;
    jump.onclick = () => {
      // Only re-render when opening actually changes something. Rebuilding the
      // list and scrolling in the same frame raced: the scroll ran against the
      // old layout and landed nowhere.
      const needsRender = !S.open[b.id];
      S.open[b.id] = true;
      if (needsRender) renderAll();
      scrollToBucket(b.id, needsRender);
    };
    left.append(jump);
  });
  bar.append(left);

  const right = el('div', 'bright');
  const ea = el('button', 'act', 'Expand all');
  ea.onclick = () => { groups.forEach(([b]) => S.open[b.id] = true); renderAll(); };
  const ca = el('button', 'act', 'Collapse all');
  ca.onclick = () => { groups.forEach(([b]) => S.open[b.id] = false); renderAll(); };
  right.append(ea, ca);
  bar.append(right);
  wrap.append(bar);

  groups.forEach(([b, list]) => {
    // Default open on first sight so nothing is hidden from a first-time reviewer.
    if (S.open[b.id] === undefined) S.open[b.id] = true;
    const openNow = !!S.open[b.id];

    const sec = el('div', 'bucket' + (openNow ? ' open' : ''));
    sec.id = `bucket-${b.id}`;
    const head = el('button', 'bhead');
    head.append(el('span', 'caret', openNow ? '▾' : '▸'));
    head.append(el('span', 'bname', b.name));
    const badge = count ? count(list) : `${list.length}`;
    head.append(el('span', 'bcount', badge));
    head.onclick = () => { S.open[b.id] = !openNow; renderAll(); };
    sec.append(head);

    const body = el('div', 'bbody');
    body.append(el('div', 'bblurb', b.blurb));
    list.forEach(i => body.append(card(i, mode)));
    if (openNow) sec.append(body);
    wrap.append(sec);
  });
  return wrap;
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
      ? el('div','why',`Settled by rule: ${t.replace('rule · ','')}. No lookup needed.`)
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
      f.append(el('b',null,`Proposed: ${sub.proposed}`), document.createTextNode(`, re-checked and verified in ${sub.attempts} attempt${sub.attempts===1?'':'s'}`));
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
    const b = el('button','act danger'+(d.dismissed?' on':''), d.dismissed?'Dismissed, click to restore':'Not a clearance subject');
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
