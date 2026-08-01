"""Baygon Shell — minimal web interface.

The third face of the Shell (EF-004): a single mobile-friendly page
served by the API server. It carries no project data and no business
logic — everything goes through the same authenticated endpoints, with
the token typed by the user and kept in the browser only.
"""

PAGE = """<!doctype html>
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
  input { width: 100%; box-sizing: border-box; margin-bottom: .5rem; }
  .row { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .75rem; }
  button { cursor: pointer; }
  pre { background: #8881; padding: .75rem; border-radius: .4rem; overflow-x: auto;
        white-space: pre-wrap; word-break: break-word; font-size: .85rem; }
  #approve { display: none; background: #c62828; color: #fff; border: none; }
</style>
</head>
<body>
<h1>Baygon <small>— une intention, une réponse, depuis n'importe où</small></h1>
<input id="token" type="password" placeholder="Jeton d'accès (Authorization: Bearer …)">
<input id="intent" placeholder="Votre intention — ex. « analyse l'incident en production »">
<div class="row">
  <button onclick="call('/plan')">Plan</button>
  <button onclick="call('/run')">Exécuter</button>
  <button id="approve" onclick="call('/run', true)">Approuver l'action sensible</button>
  <button onclick="get('/history')">Historique</button>
  <button onclick="get('/context')">Contexte</button>
  <button onclick="get('/capabilities')">Capacités</button>
</div>
<pre id="out">Prêt. Saisissez votre jeton puis exprimez une intention.</pre>
<script>
const out = document.getElementById('out');
const approve = document.getElementById('approve');
function headers() {
  return { 'Content-Type': 'application/json',
           'Authorization': 'Bearer ' + document.getElementById('token').value };
}
function show(status, data) {
  approve.style.display = (status === 428) ? 'inline-block' : 'none';
  out.textContent = JSON.stringify(data, null, 2);
}
async function call(path, approved = false) {
  const body = { intent: document.getElementById('intent').value };
  if (approved) body.approved = true;
  const r = await fetch(path, { method: 'POST', headers: headers(),
                                body: JSON.stringify(body) });
  show(r.status, await r.json());
}
async function get(path) {
  const r = await fetch(path, { headers: headers() });
  show(r.status, await r.json());
}
</script>
</body>
</html>
"""
