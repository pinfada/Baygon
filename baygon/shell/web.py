"""Baygon Shell — minimal web interface.

The third face of the Shell (EF-004): a single mobile-friendly page
served by the API server. It carries no project data and no business
logic — everything goes through the same authenticated endpoints, with
the token typed by the user and kept in the browser only.
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
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 42rem; margin: 0 auto;
         padding: 1rem; line-height: 1.4; }
  h1 { font-size: 1.3rem; } h1 small { font-weight: normal; opacity: .6; }
  input, button, textarea { font: inherit; padding: .5rem .7rem; border-radius: .4rem;
         border: 1px solid #8884; }
  input, select { width: 100%; box-sizing: border-box; margin-bottom: .5rem; }
  select { padding: .5rem .7rem; border-radius: .4rem; border: 1px solid #8884; }
  .row { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .75rem; }
  .row select { width: auto; flex: 1 1 12rem; margin-bottom: 0; }
  .stale { color: #b26a00; font-size: .85rem; margin: -.25rem 0 .6rem; }
  button { cursor: pointer; }
  button:disabled { opacity: .5; cursor: progress; }
  pre { background: #8881; padding: .75rem; border-radius: .4rem; overflow-x: auto;
        white-space: pre-wrap; word-break: break-word; font-size: .85rem; }
  #approve { display: none; background: #c62828; color: #fff; border: none; }
  /* Une étape IA prend des dizaines de secondes : sans signe de vie,
     l'attente ressemble à une panne et invite à recliquer. */
  #status { display: none; align-items: center; gap: .6rem; font-size: .9rem;
            margin: 0 0 .75rem; opacity: .8; }
  #status.on { display: flex; }
  .spinner { width: 1rem; height: 1rem; flex: none; border-radius: 50%;
             border: 2px solid #8884; border-top-color: currentColor;
             animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  /* Le compteur porte l'information ; la rotation n'est que décor. */
  @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
</style>
</head>
<body>
<h1>Baygon <small>— une intention, une réponse, depuis n'importe où</small></h1>
<input id="token" type="password" placeholder="Jeton d'accès (Authorization: Bearer …)"
       onchange="refresh()">
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
<input id="intent" placeholder="Votre intention — ex. « analyse l'incident en production »">
<div class="row">
  <button onclick="call('/plan')">Plan</button>
  <button onclick="call('/run')">Exécuter</button>
  <button id="approve" onclick="call('/run', true)">Approuver l'action sensible</button>
  <button onclick="get('/history')">Historique</button>
  <button onclick="get('/context')">Contexte</button>
  <button onclick="get('/capabilities')">Capacités</button>
</div>
<p id="status" aria-live="polite"><span class="spinner"></span><span id="statusText"></span></p>
<pre id="out" aria-busy="false">Prêt. Saisissez votre jeton puis exprimez une intention.</pre>
<script>
const out = document.getElementById('out');
const approve = document.getElementById('approve');
const statusBar = document.getElementById('status');
const statusText = document.getElementById('statusText');
let ticker = null;

// Une requête en cours désarme les boutons : un déploiement approuvé
// deux fois est un déploiement fait deux fois. Le compteur dit que
// l'attente est vivante — une étape IA dure des dizaines de secondes.
function busy(on, label) {
  for (const button of document.querySelectorAll('button')) button.disabled = on;
  statusBar.classList.toggle('on', on);
  out.setAttribute('aria-busy', on ? 'true' : 'false');
  if (ticker) { clearInterval(ticker); ticker = null; }
  if (!on) return;
  const started = Date.now();
  const tick = () => {
    const seconds = Math.round((Date.now() - started) / 1000);
    statusText.textContent = label + ' — ' + seconds + ' s';
  };
  tick();
  ticker = setInterval(tick, 1000);
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

// Les projets d'abord : la liste des modèles dépend du projet choisi.
async function refresh() {
  await loadProjects();
  await loadModels();
}

function headers() {
  return { 'Content-Type': 'application/json',
           'Authorization': 'Bearer ' + document.getElementById('token').value };
}
function show(status, data) {
  approve.style.display = (status === 428) ? 'inline-block' : 'none';
  out.textContent = JSON.stringify(data, null, 2);
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
async function loadProjects() {
  const select = document.getElementById('project');
  try {
    const r = await fetch('/projects', { headers: headers() });
    if (!r.ok) return;
    const names = await r.json();
    select.innerHTML = names.length > 1
      ? '<option value="">Projet : d\'après l\'intention</option>' : '';
    for (const name of names) {
      const option = document.createElement('option');
      option.value = name; option.textContent = name;
      select.appendChild(option);
    }
    if (names.length === 1) select.value = names[0];
  } catch (e) { /* le champ reste utilisable */ }
}
async function loadModels() {
  const select = document.getElementById('model');
  try {
    const r = await fetch(withProject('/models'), { headers: headers() });
    if (!r.ok) return;
    const models = await r.json();
    select.innerHTML = '<option value="">Modèle par défaut</option>';
    const stale = [], injoignables = [];
    for (const m of models) {
      const option = document.createElement('option');
      option.value = m.name;
      const etat = m.reachable === false ? ' (injoignable)' : '';
      option.textContent = (m.model ? m.name + ' — ' + m.model : m.name) + etat;
      select.appendChild(option);
      if (m.reachable === false) injoignables.push(m.model || m.name);
      else if (m.up_to_date === false) stale.push(m.model || m.name);
    }
    // Un modèle hors de portée doit se voir avant d'être choisi, pas
    // après avoir attendu sa réponse.
    noteModeles = injoignables.length
      ? 'Modèle(s) hors de portée depuis ce serveur : ' + injoignables.join(', ')
      : stale.length
      ? 'Modèle(s) qui ne figurent plus chez le fournisseur : ' + stale.join(', ')
      : '';
    renderNotes();
  } catch (e) { /* le choix reste possible même sans liste */ }
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
    show(r.status, await r.json());
  } catch (e) {
    // Une panne réseau doit se voir, pas disparaître dans la console.
    show(0, { error: 'Requête impossible : ' + e });
  } finally {
    busy(false);   // sans quoi une erreur laisserait la page figée
  }
}
async function get(path) {
  path = withProject(path);
  busy(true, 'Lecture en cours');
  try {
    const r = await fetch(path, { headers: headers() });
    show(r.status, await r.json());
  } catch (e) {
    show(0, { error: 'Requête impossible : ' + e });
  } finally {
    busy(false);
  }
}
</script>
</body>
</html>
"""
