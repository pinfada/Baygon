"""Baygon Shell — minimal web interface.

The third face of the Shell (EF-004): a single mobile-friendly page
served by the API server. It carries no project data and no business
logic — everything goes through the same authenticated endpoints, with
the token typed by the user and kept in the browser only.

The page answers, it does not dump: the model's analysis and the
outcome come first, in words; the raw JSON stays one fold away, never
gone — trust needs the source at hand. External data (logs, model
output) is always inserted as text, never as markup.
"""

# Raw string on purpose: the page carries JavaScript, and a backslash in
# it is meant for the browser. Without the `r`, Python eats the escape —
# `\'` reaches the browser as a bare quote, ends the string early and
# kills the whole script, taking every button with it.
PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Baygon</title>
<style>
  :root {
    color-scheme: light dark;
    --paper: #fafbf8; --card: #ffffff; --ink: #1b231e; --muted: #5d6862;
    --accent: #1e7a4f; --accent-ink: #ffffff; --line: #d8dfda;
    --good: #1e7a4f; --warn: #a85a12; --bad: #b3261e;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --paper: #141a16; --card: #1a211c; --ink: #e3eae5; --muted: #93a099;
      --accent: #2f9d6a; --accent-ink: #f2fff8; --line: #2a342e;
      --good: #55c08a; --warn: #e09553; --bad: #f2b8b5;
    }
  }
  body { background: var(--paper); color: var(--ink); line-height: 1.5;
         font-family: system-ui, sans-serif; max-width: 44rem;
         margin: 0 auto; padding: 1rem 1rem 3rem; }
  h1 { font-size: 1.3rem; margin: 0 0 .1rem; letter-spacing: -.01em; }
  .tagline { margin: 0 0 1rem; color: var(--muted); font-size: .9rem; }
  input, button, select { font: inherit; color: inherit; }
  input, select { width: 100%; box-sizing: border-box; margin-bottom: .5rem;
         background: var(--card); border: 1px solid var(--line);
         border-radius: .5rem; padding: .55rem .7rem; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .row { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .6rem; }
  .row select { width: auto; flex: 1 1 12rem; margin-bottom: 0; }
  .stale { color: var(--warn); font-size: .85rem; margin: -.15rem 0 .6rem; }
  button { cursor: pointer; background: var(--card); color: inherit;
           border: 1px solid var(--line); border-radius: .5rem;
           padding: .5rem .9rem; }
  button:disabled { opacity: .5; cursor: progress; }
  button.primary { background: var(--accent); color: var(--accent-ink);
                   border-color: var(--accent); font-weight: 600; }
  button.chip { padding: .3rem .7rem; font-size: .85rem; color: var(--muted); }
  #approve { display: none; background: var(--bad); color: #fff;
             border-color: var(--bad); font-weight: 600; }
  /* Une étape IA prend des dizaines de secondes : sans signe de vie,
     l'attente ressemble à une panne et invite à recliquer. */
  #status { display: none; align-items: center; gap: .6rem; font-size: .9rem;
            margin: 0 0 .75rem; color: var(--muted); }
  #status.on { display: flex; }
  .spinner { width: 1rem; height: 1rem; flex: none; border-radius: 50%;
             border: 2px solid var(--line); border-top-color: currentColor;
             animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  /* Le compteur porte l'information ; la rotation n'est que décor. */
  @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }

  #result { background: var(--card); border: 1px solid var(--line);
            border-radius: .6rem; padding: .9rem 1rem; }
  #verdict { margin: 0 0 .5rem; font-weight: 600; }
  #verdict.good { color: var(--good); }
  #verdict.warn { color: var(--warn); }
  #verdict.bad { color: var(--bad); }
  .block { margin: .9rem 0 0; }
  .block h2 { font-size: .72rem; letter-spacing: .12em; text-transform: uppercase;
              color: var(--muted); margin: 0 0 .35rem; font-weight: 600; }
  .prose { margin: 0; white-space: pre-wrap; word-break: break-word; }
  ul { margin: 0; padding-left: 1.1rem; }
  ul.steps { list-style: none; padding-left: 0; }
  ul.steps li { font-family: ui-monospace, monospace; font-size: .85rem;
                padding: .12rem 0; }
  ul.steps li.failed { color: var(--bad); }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; }
  th { text-align: left; color: var(--muted); font-weight: 600;
       border-bottom: 1px solid var(--line); padding: .3rem .5rem .3rem 0; }
  td { border-bottom: 1px solid var(--line); padding: .3rem .5rem .3rem 0;
       vertical-align: top; }
  details { margin-top: 1rem; }
  summary { cursor: pointer; color: var(--muted); font-size: .85rem; }
  pre { background: transparent; padding: .5rem 0 0; overflow-x: auto;
        white-space: pre-wrap; word-break: break-word; font-size: .8rem; }
</style>
</head>
<body>
<h1>Baygon</h1>
<p class="tagline">une intention, une réponse, depuis n'importe où</p>
<input id="token" type="password" placeholder="Jeton d'accès (Authorization: Bearer …)"
       autocomplete="current-password" onchange="tokenChanged()">
<div class="row">
  <select id="mode" onchange="onMode()">
    <option value="ai">Mode IA — Baygon interprète les formulations libres</option>
    <option value="noai">Sans IA — règles déterministes uniquement</option>
  </select>
  <select id="model"><option value="">Modèle par défaut</option></select>
  <select id="project" onchange="loadModels()">
    <option value="">Projet : automatique</option>
  </select>
</div>
<p id="freshness" class="stale"></p>
<form onsubmit="submitRun(event)">
  <input id="intent" autocomplete="off"
         placeholder="Votre intention — ex. « pourquoi la production est lente ? »">
  <div class="row">
    <button type="submit" class="primary">Exécuter</button>
    <button type="button" onclick="call('/plan')">Plan</button>
    <button type="button" id="approve" onclick="call('/run', true)">Approuver l'action sensible</button>
  </div>
  <div class="row">
    <button type="button" class="chip" onclick="get('/history')">Historique</button>
    <button type="button" class="chip" onclick="get('/context')">Contexte</button>
    <button type="button" class="chip" onclick="get('/capabilities')">Capacités</button>
    <button type="button" class="chip" onclick="get('/doctor')">Diagnostic</button>
  </div>
</form>
<p id="status" aria-live="polite"><span class="spinner"></span><span id="statusText"></span></p>
<section id="result" aria-busy="false" aria-live="polite">
  <p id="verdict">Prêt. Saisissez votre jeton puis exprimez une intention.</p>
  <div id="answer"></div>
  <details id="rawfold"><summary>Réponse brute (JSON)</summary><pre id="raw"></pre></details>
</section>
<script>
const approveButton = document.getElementById('approve');
const statusBar = document.getElementById('status');
const statusText = document.getElementById('statusText');
const result = document.getElementById('result');
const verdict = document.getElementById('verdict');
const answer = document.getElementById('answer');
const raw = document.getElementById('raw');
const rawFold = document.getElementById('rawfold');
const tokenInput = document.getElementById('token');
let ticker = null;

// Une requête en cours désarme les boutons : un déploiement approuvé
// deux fois est un déploiement fait deux fois. Le compteur dit que
// l'attente est vivante — une étape IA dure des dizaines de secondes.
function busy(on, label) {
  for (const button of document.querySelectorAll('button')) button.disabled = on;
  statusBar.classList.toggle('on', on);
  result.setAttribute('aria-busy', on ? 'true' : 'false');
  if (ticker) { clearInterval(ticker); ticker = null; }
  if (!on) return;
  const started = Date.now();
  const tick = () => {
    const elapsed = Math.round((Date.now() - started) / 1000);
    statusText.textContent = label + ' — ' + elapsed + ' s';
  };
  tick();
  ticker = setInterval(tick, 1000);
}

// Les données qui arrivent (logs, sortie de modèle) sont du texte,
// jamais du balisage : tout passe par textContent, rien par innerHTML.
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function seconds(ms) {
  return (Number(ms || 0) / 1000).toFixed(1).replace('.', ',') + ' s';
}

function setVerdict(kind, text) {
  verdict.className = kind || '';
  verdict.textContent = text;
}

// Tout ce qui lit des données d'un projet doit dire lequel : avec
// plusieurs projets servis, une requête anonyme est refusée (400).
// Un seul endroit le fait, pour qu'aucun appel ne puisse l'oublier.
function withProject(path) {
  const project = document.getElementById('project').value;
  if (!project) return path;
  return path + (path.includes('?') ? '&' : '?')
       + 'project=' + encodeURIComponent(project);
}

// Retaper un long jeton à chaque visite est la friction qu'un téléphone
// ne pardonne pas ; un jeton qui survit au navigateur est le risque que
// cette page ne prend pas. sessionStorage est l'entre-deux : il survit
// au rechargement, il meurt avec l'onglet.
function tokenChanged() {
  sessionStorage.setItem('baygon-jeton', tokenInput.value);
  refresh();
}

// Les projets d'abord : la liste des modèles dépend du projet choisi.
async function refresh() {
  await loadProjects();
  await loadModels();
}

function headers() {
  return { 'Content-Type': 'application/json',
           'Authorization': 'Bearer ' + tokenInput.value };
}

function show(status, data, kind) {
  approveButton.style.display = (status === 428) ? 'inline-block' : 'none';
  raw.textContent = JSON.stringify(data, null, 2);
  rawFold.open = false;
  answer.replaceChildren();
  if (status === 0) {
    setVerdict('bad', (data && data.error) || 'Requête impossible.');
    return;
  }
  if (status === 401) {
    setVerdict('bad', 'Jeton refusé : vérifiez-le, puis réessayez.');
    return;
  }
  if (status === 428) {
    setVerdict('warn', 'Action sensible : relisez, puis approuvez explicitement.');
    if (data && data.error) answer.appendChild(el('p', 'prose', data.error));
    return;
  }
  if (status >= 400) {
    setVerdict('bad', (data && data.error) ? String(data.error) : 'Erreur ' + status);
    rawFold.open = true;
    return;
  }
  try {
    if (kind === 'run') renderRun(data);
    else if (kind === 'plan') renderPlan(data);
    else if (kind === 'history') renderHistory(data);
    else if (kind === 'doctor') renderDoctor(data);
    else {
      setVerdict('', 'Réponse reçue — le détail est dans la réponse brute.');
      rawFold.open = true;
    }
  } catch (e) {
    // Un rendu qui trébuche sur une forme inattendue ne doit jamais
    // cacher la réponse : le JSON brut reprend la main.
    setVerdict('', 'Réponse reçue — le détail est dans la réponse brute.');
    rawFold.open = true;
  }
}

function renderRun(data) {
  const ok = data.success === true;
  const failure = data.failure || null;
  setVerdict(ok ? 'good' : 'bad',
    ok ? 'Exécuté avec succès en ' + seconds(data.duration_ms)
       : 'Échec — ' + ((failure && failure.cause) || 'cause inconnue'));
  const steps = data.steps || [];
  for (const step of steps) {
    if (step.capability === 'ai' && step.success && step.output) {
      const block = el('div', 'block');
      block.appendChild(el('h2', '', 'Analyse du modèle'));
      block.appendChild(el('p', 'prose', String(step.output).trim()));
      answer.appendChild(block);
    }
  }
  if (steps.length) {
    const block = el('div', 'block');
    block.appendChild(el('h2', '', 'Étapes'));
    const list = el('ul', 'steps');
    for (const step of steps) {
      const mark = step.success ? '✓' : '✗';
      const timing = step.reused ? 'réutilisée' : seconds(step.duration_ms);
      list.appendChild(el('li', step.success ? '' : 'failed',
        mark + ' ' + step.capability + '.' + step.action + ' — ' + timing));
    }
    block.appendChild(list);
    answer.appendChild(block);
  }
}

function renderPlan(data) {
  const plan = data.plan || data;
  const intent = plan.intent || {};
  let line = 'Plan : ' + (intent.name || '?') + ' · risque ' + (plan.risk || '?');
  if (plan.requires_validation) line += ' · validation requise';
  setVerdict(plan.requires_validation ? 'warn' : '', line);
  const reasoning = plan.reasoning || [];
  if (reasoning.length) {
    const block = el('div', 'block');
    block.appendChild(el('h2', '', 'Raisonnement'));
    const list = el('ul', '');
    for (const reason of reasoning) list.appendChild(el('li', '', reason));
    block.appendChild(list);
    answer.appendChild(block);
  }
  const steps = plan.steps || [];
  if (steps.length) {
    const block = el('div', 'block');
    block.appendChild(el('h2', '', 'Étapes prévues'));
    const list = el('ul', 'steps');
    for (const step of steps) {
      const env = step.parameters && step.parameters.environment
        ? ' (' + step.parameters.environment + ')' : '';
      list.appendChild(el('li', '', step.capability + '.' + step.action + env));
    }
    block.appendChild(list);
    answer.appendChild(block);
  }
}

function renderHistory(entries) {
  if (!Array.isArray(entries) || !entries.length) {
    setVerdict('', 'Historique vide : rien n’a encore été exécuté ici.');
    return;
  }
  setVerdict('', 'Historique — ' + entries.length + ' exécution(s)');
  const table = el('table', '');
  const head = el('tr', '');
  for (const label of ['Date', 'Intention', 'Statut', 'Demande']) {
    head.appendChild(el('th', '', label));
  }
  table.appendChild(head);
  for (const entry of entries) {
    const row = el('tr', '');
    row.appendChild(el('td', '', String(entry.date || '').slice(0, 16)));
    row.appendChild(el('td', '', entry.intent || ''));
    row.appendChild(el('td', '', entry.status || ''));
    row.appendChild(el('td', '', entry.input || ''));
    table.appendChild(row);
  }
  const block = el('div', 'block');
  block.appendChild(table);
  answer.appendChild(block);
}

function renderDoctor(report) {
  setVerdict('', (report.project || 'Projet') + ' — ' + report.ready_count
    + '/' + report.total_count + ' intentions utilisables');
  const intents = report.intents || [];
  const ready = intents.filter((entry) => entry.ready);
  if (ready.length) {
    const block = el('div', 'block');
    block.appendChild(el('h2', '', 'Utilisables'));
    const list = el('ul', 'steps');
    for (const entry of ready) list.appendChild(el('li', '', '✓ ' + entry.intent));
    const commands = report.commands || [];
    if (commands.length) {
      list.appendChild(el('li', '', '✓ commandes déclarées : ' + commands.join(', ')));
    }
    block.appendChild(list);
    answer.appendChild(block);
  }
  const blocked = intents.filter((entry) => !entry.ready);
  if (blocked.length) {
    const block = el('div', 'block');
    block.appendChild(el('h2', '', 'Indisponibles'));
    const list = el('ul', 'steps');
    for (const entry of blocked) {
      const reasons = []
        .concat((entry.missing_capabilities || []).map((c) => 'capacité ' + c))
        .concat((entry.missing_permissions || []).map((p) => 'permission ' + p));
      list.appendChild(el('li', 'failed',
        '✗ ' + entry.intent + (reasons.length ? ' — ' + reasons.join(', ') : '')));
    }
    block.appendChild(list);
    answer.appendChild(block);
  }
}

// Deux choses ont leur mot à dire sur la ligne d'avertissement : le
// mode choisi et l'état des modèles. Un seul endroit la compose, sinon
// le dernier à écrire efface l'autre — et c'est l'avertissement
// « injoignable » qui disparaissait au moindre changement de mode.
let noteModeles = '';

function renderNotes() {
  const ai = document.getElementById('mode').value === 'ai';
  document.getElementById('freshness').textContent = ai ? noteModeles
    : 'Sans IA : seules les formulations reconnues par les règles sont acceptées.';
}

function onMode() {
  const ai = document.getElementById('mode').value === 'ai';
  document.getElementById('model').disabled = !ai;
  renderNotes();
}

function option(value, label) {
  const node = document.createElement('option');
  node.value = value;
  node.textContent = label;
  return node;
}

async function loadProjects() {
  const select = document.getElementById('project');
  try {
    const r = await fetch('/projects', { headers: headers() });
    if (!r.ok) return;
    const names = await r.json();
    select.replaceChildren();
    if (names.length > 1) {
      select.appendChild(option('', 'Projet : d’après l’intention'));
    }
    for (const name of names) select.appendChild(option(name, name));
    if (names.length === 1) select.value = names[0];
  } catch (e) { /* le champ reste utilisable */ }
}

async function loadModels() {
  const select = document.getElementById('model');
  try {
    const r = await fetch(withProject('/models'), { headers: headers() });
    if (!r.ok) return;
    const models = await r.json();
    select.replaceChildren(option('', 'Modèle par défaut'));
    const stale = [], injoignables = [];
    for (const m of models) {
      const etat = m.reachable === false ? ' (injoignable)' : '';
      select.appendChild(option(m.name,
        (m.model ? m.name + ' — ' + m.model : m.name) + etat));
      if (m.reachable === false) injoignables.push(m.model || m.name);
      else if (m.up_to_date === false) stale.push(m.model || m.name);
    }
    // Un modèle hors de portée doit se voir avant d'être choisi, pas
    // après avoir attendu sa réponse. Et un projet sans modèle du tout
    // ne peut rien interpréter : le proposer serait une promesse en l'air.
    noteModeles = !models.length
      ? 'Aucun modèle déclaré pour ce projet : même en mode IA, seules les '
        + 'formulations reconnues par les règles sont acceptées.'
      : injoignables.length
      ? 'Modèle(s) hors de portée depuis ce serveur : ' + injoignables.join(', ')
      : stale.length
      ? 'Modèle(s) qui ne figurent plus chez le fournisseur : ' + stale.join(', ')
      : '';
    renderNotes();
  } catch (e) { /* le choix reste possible même sans liste */ }
}

// Sur un clavier de téléphone, Entrée est le bouton.
function submitRun(event) {
  event.preventDefault();
  call('/run');
}

async function call(path, approved = false) {
  const body = { intent: document.getElementById('intent').value };
  if (document.getElementById('mode').value !== 'ai') body.ai = false;
  const model = document.getElementById('model').value;
  if (model) body.model = model;
  const project = document.getElementById('project').value;
  if (project) body.project = project;
  if (approved) body.approved = true;
  const ai = document.getElementById('mode').value === 'ai';
  busy(true, approved ? 'Exécution approuvée en cours'
       : path === '/plan' ? 'Construction du plan'
       : ai ? 'Exécution en cours (une étape IA peut durer)' : 'Exécution en cours');
  try {
    const r = await fetch(path, { method: 'POST', headers: headers(),
                                  body: JSON.stringify(body) });
    show(r.status, await r.json(), path === '/plan' ? 'plan' : 'run');
  } catch (e) {
    // Une panne réseau doit se voir, pas disparaître dans la console.
    show(0, { error: 'Requête impossible : ' + e });
  } finally {
    busy(false);   // sans quoi une erreur laisserait la page figée
  }
}

async function get(path) {
  const kind = path.slice(1);
  path = withProject(path);
  busy(true, 'Lecture en cours');
  try {
    const r = await fetch(path, { headers: headers() });
    show(r.status, await r.json(), kind);
  } catch (e) {
    show(0, { error: 'Requête impossible : ' + e });
  } finally {
    busy(false);
  }
}

tokenInput.value = sessionStorage.getItem('baygon-jeton') || '';
if (tokenInput.value) refresh();
</script>
</body>
</html>
"""
