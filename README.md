# Baygon

> Une intention. Une réponse. Depuis n'importe où.

Baygon est une couche d'orchestration légère : l'utilisateur exprime une
**intention**, Baygon construit un **plan d'exécution** explicable et délègue
chaque action à des **capacités** dont les implémentations (providers) sont
interchangeables. Le noyau ne contient aucune logique métier et ne connaît
aucun fournisseur.

La documentation de référence se trouve dans [`docs/`](docs/) — le code
implémente la documentation, jamais l'inverse.

## Architecture

```
Utilisateur (téléphone, tablette, ordinateur)
        │
   Baygon Shell          baygon/shell/      point d'entrée unique (terminal + API REST)
        │
   Intent Engine         baygon/core/intent.py    intention → plan (pense, n'agit jamais)
        │
   Context Engine        baygon/core/context.py   prépare le contexte, n'agit jamais
        │
   Execution Engine      baygon/core/executor.py  permissions, validation, exécution
        │
   Capability Registry   baygon/core/registry.py  catalogue capacités → implémentations
        │
   Plugins / Providers   baygon_plugins/    adaptateurs déclarés dans baygon.yaml
```

Composants du noyau (`baygon/core/`) :

- **Config Loader** (`config.py`) — lit et valide `baygon.yaml`, l'unique
  source de vérité d'un projet. Un fichier invalide interdit l'exécution.
- **Intent Engine** (`intent.py`) — résolution déterministe des intentions
  (règles, sans IA — EF-014), plans explicables (`plan.explain()`), niveaux de
  risque LOW/MEDIUM/HIGH/CRITICAL, validation exigée pour les actions sensibles.
- **Capability Registry** (`registry.py`) — enregistre les implémentations,
  vérifie les contrats, sélectionne : demandée → défaut → compatible → erreur.
- **Plugin Manager** (`plugins.py`) — charge les providers depuis
  `baygon.yaml` (`module:Classe`). Un plugin défaillant est isolé : la
  capacité est indisponible, le reste fonctionne.
- **Event Manager** (`events.py`) — le noyau publie des événements, il ne les
  analyse jamais.
- **Execution Engine** (`executor.py`) — exécute les plans, applique les
  permissions déclarées, interrompt en cas d'échec avec cause et actions
  possibles.
- **Audit** (`audit.py`) — chaque plan est journalisé : date, utilisateur,
  intention, plan, résultat (`.baygon/history.jsonl`).
- **Context Engine** (`context.py`) — construit le contexte du projet
  (fournisseurs, capacités, observabilité, permissions — jamais la valeur d'un
  secret). Il prépare, il n'agit pas.

Les contrats de capacités (`baygon/capabilities/`) définissent *ce qui peut
être fait*, jamais *comment* : repository, deployment, logs, metrics,
database, secrets, notification, ai.

Les implémentations de référence (`baygon_plugins/`) vivent **hors du noyau**
et ne sont chargées que si `baygon.yaml` les déclare : git local, **GitHub
(API REST)**, shell local (commandes déclarées), déploiement simulé, logs
fichiers, métriques statiques, secrets d'environnement, notifications
console, IA hors-ligne (l'IA n'est jamais une dépendance obligatoire).
L'adaptateur GitHub lit son jeton dans l'environnement (`GITHUB_TOKEN` par
défaut), jamais dans la configuration.

**Hot-reload** (chapitre 10) : `kernel.reload()` — ou `POST /reload` sur l'API —
relit `baygon.yaml` et reconstruit le catalogue de capacités **sans redémarrer
Baygon**. Un nouveau fichier invalide laisse l'état courant intact ; le journal
d'audit et les abonnements aux événements survivent au rechargement.

Côté données, l'adaptateur **PostgreSQL** (capacité `database`) retourne les
informations de connexion et la commande console à partir d'un DSN lu dans
l'environnement — le mot de passe n'est jamais exposé, la commande référence
la variable (`psql "$STAGING_DATABASE_URL"`). Permission `database` requise.

Côté observabilité, deux adaptateurs réels : **Loki** pour la capacité `logs`
(requête LogQL par environnement) et **Prometheus** pour la capacité `metrics`
(requêtes PromQL avec substitution de l'environnement). Baygon consulte, il ne
stocke jamais (EF-007).

Deux autres adaptateurs réels sont fournis : **Claude** pour la capacité `ai`
(SDK officiel `anthropic`, installable via `pip install baygon[claude]`, clé
lue dans `ANTHROPIC_API_KEY`) et **Render** pour la capacité `deployment`
(API REST, clé dans `RENDER_API_KEY`, services mappés par environnement dans
`baygon.yaml`). Passer de l'IA hors-ligne à Claude — ou de Render à un autre
cloud — ne demande qu'une modification de configuration : le noyau ne change
jamais.

## Utilisation

```console
$ pip install -e .

$ baygon validate                       # valider baygon.yaml
$ baygon capabilities                   # capacités et implémentations disponibles
$ baygon plan "Déploie en production"   # construire et expliquer le plan
$ baygon run "deploy to staging"        # exécuter
$ baygon run "Déploie en production" --yes   # action sensible : validation explicite
$ baygon run "montre-moi les erreurs des dernières 24 heures"
$ baygon run "analyse l'incident en production"
$ baygon history                        # historique des intentions exécutées
$ baygon context                        # contexte construit par le Context Engine
$ baygon resume [--plan ID] [--yes]     # reprendre la dernière exécution échouée
$ baygon run "ouvre une console ssh en production"   # commande de connexion (permission ssh)
```

**Reprise** (ENF-017) : un plan interrompu par une panne fournisseur se reprend
avec `baygon resume` — les étapes déjà réussies ne sont jamais ré-exécutées,
leurs résultats enregistrés sont réutilisés et l'exécution redémarre à l'étape
en échec. La validation des plans sensibles s'applique aussi à la reprise.

### Multi-projets

Baygon gère plusieurs projets totalement indépendants (EF-001) : chaque
sous-répertoire contenant un `baygon.yaml` est découvert, avec un noyau,
des providers, des permissions et un historique propres. Un projet cassé
est isolé, les autres continuent de fonctionner.

```console
$ baygon --projects ~/projets projects            # lister les projets découverts
$ baygon --projects ~/projets run "Déploie JiyuFit en staging"   # routé par le nom
$ baygon --projects ~/projets --project jiyufit history          # ciblage explicite
```

### API REST et interface web

Le même Shell est exposable en HTTP (stdlib uniquement) — utilisable depuis un
téléphone, une tablette ou une automatisation. `GET /` sert une **page web
mobile minimaliste** (aucune donnée projet, aucune logique métier : elle pilote
les mêmes endpoints authentifiés, jeton saisi dans la page, gestion du `428`
avec bouton d'approbation explicite) :

```console
$ baygon serve --host 127.0.0.1 --port 8787
```

| Méthode | Chemin           | Description                                      |
|---------|------------------|--------------------------------------------------|
| GET     | `/health`        | état du noyau                                    |
| GET     | `/capabilities`  | capacités et implémentations disponibles         |
| GET     | `/context`       | contexte du projet                               |
| GET     | `/history`       | intentions exécutées                             |
| POST    | `/plan`          | `{"intent": "…"}` → plan + explication           |
| POST    | `/run`           | `{"intent": "…", "approved": bool}` → résultat   |
| POST    | `/reload`        | recharge `baygon.yaml` à chaud (chapitre 10)     |

Un plan sensible renvoie `428` tant que `"approved": true` n'est pas fourni :
même règle que le terminal, Baygon propose, l'utilisateur décide.

**Authentification** (Article 7 — sécurité par défaut) : le serveur refuse de
démarrer sans jeton. Le jeton n'est jamais dans `baygon.yaml` : il vient de
`BAYGON_API_TOKEN` ou du gestionnaire de secrets (secret `API_TOKEN`). Chaque
requête (sauf `/health`) doit porter `Authorization: Bearer <jeton>` sous
peine de `401`. `--insecure` permet explicitement un démarrage sans
authentification (développement local uniquement).

Sans `--yes`, un plan à risque HIGH/CRITICAL est suspendu : Baygon propose,
l'utilisateur décide.

## Configuration

Chaque projet est décrit par un unique fichier `baygon.yaml` à la racine du
dépôt (voir [`docs/06-specification-baygon-yaml.md`](docs/06-specification-baygon-yaml.md)
et l'exemple à la racine de ce dépôt). Remplacer un fournisseur — ou un modèle
IA — ne demande qu'une modification de ce fichier, jamais du noyau.

```yaml
providers:
  cloud:
    type: deployment
    plugin: baygon_plugins.mock_deploy:MockDeployment   # demain : un adaptateur Render, Fly.io…
    default: true
```

## Tests

```console
$ python -m unittest discover -s tests
```

## Licence

MIT — voir [LICENSE](LICENSE).
