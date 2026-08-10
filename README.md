# Baygon

> Une intention. Une réponse. Depuis n'importe où.

Baygon est une couche d'orchestration légère : l'utilisateur exprime une
**intention**, Baygon construit un **plan d'exécution** explicable et délègue
chaque action à des **capacités** dont les implémentations (providers) sont
interchangeables. Le noyau ne contient aucune logique métier et ne connaît
aucun fournisseur.

La documentation de référence se trouve dans [`docs/`](docs/) — le code
implémente la documentation, jamais l'inverse.

| Chapitre | Contenu |
|---|---|
| [01](docs/01-vision.md)–[02](docs/02-constitution.md) | Vision et Constitution : les principes immuables |
| [03](docs/03-architecture-globale.md)–[05](docs/05-exigences-non-fonctionnelles.md) | Architecture globale, exigences fonctionnelles et non fonctionnelles |
| [06](docs/06-specification-baygon-yaml.md) | Spécification de `baygon.yaml` |
| [07](docs/07-architecture-noyau.md)–[10](docs/10-capability-registry.md) | Noyau, capacités, Intent Engine, Capability Registry |
| [11](docs/11-deploiement.md) | Déploiement en production (systemd, reverse proxy TLS) |
| **[12](docs/12-mode-operatoire.md)** | **Mode opératoire : installer et utiliser, commande par commande** |
| [13](docs/13-capacites-etendues.md) | Capacités étendues : `developer`, `review` et la boucle Dev → QA → Revue |

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
être fait*, jamais *comment* : repository, deployment, logs, metrics, traces,
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

Côté stockage, trois adaptateurs **S3-compatibles** (`baygon_plugins/s3.py`,
AWS S3, MinIO…) couvrent les capacités `storage` (listing), `backup` (envoi
du dump produit par l'outil spécialisé) et `recovery` (restauration de la
sauvegarde la plus récente — action CRITICAL soumise à validation). Signature
AWS SigV4 en stdlib pure, identifiants lus dans l'environnement
(`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`).

Côté données, l'adaptateur **PostgreSQL** (capacité `database`) retourne les
informations de connexion et la commande console à partir d'un DSN lu dans
l'environnement — le mot de passe n'est jamais exposé, la commande référence
la variable (`psql "$STAGING_DATABASE_URL"`). Permission `database` requise.

Côté observabilité, trois adaptateurs réels couvrent les trois signaux du
chapitre 8 : **Loki** pour la capacité `logs` (requête LogQL par
environnement), **Prometheus** pour la capacité `metrics` (requêtes PromQL avec
substitution de l'environnement) et **Tempo** pour la capacité `traces`
(recherche par environnement, traces les plus lentes d'abord, seuil
`min_duration_ms` optionnel). Baygon consulte, il ne stocke jamais (EF-007).

Les logs disent *que* quelque chose ne va pas, les traces disent *où* le temps
passe : quand une capacité `traces` est déclarée, le diagnostic
(« Pourquoi la production est lente ? ») la collecte en plus des logs, des
métriques et du statut de déploiement. Sans elle, le diagnostic fonctionne à
l'identique (ENF-006).

**Durée de chaque action** (ENF-008) : chaque étape d'un plan rapporte son
début, sa fin et sa durée (`started_at`, `finished_at`, `duration_ms`), et
l'exécution rapporte la sienne. Les événements `StepFinished` et
`ExecutionFinished` portent la même mesure. Une étape reprise (`resume`) est
marquée `reused` et sa durée est nulle : elle n'a pas été exécutée.

**Progression** (EF-020) : sur un terminal interactif, `baygon run` et
`baygon resume` affichent l'avancement étape par étape — `[3/4] ai.complete …`
— sur la sortie d'erreur, pour que la sortie standard ne contienne rien
d'autre que le résultat exploitable par un programme.

C'est la règle générale des deux flux : **la sortie standard porte le
résultat, la sortie d'erreur porte ce qu'un humain lit**. Les notifications
console la suivent aussi, si bien que `baygon run … | jq` reste valide même
quand un plan notifie.

**Boucle Dev → QA → Revue** : « Résous le bug de paiement » déclenche
l'intention `FixBug` — l'agent codeur (capacité `developer`) produit la
correction, Baygon exécute la commande `test` déclarée comme contrôle qualité
indépendant, et en cas d'échec le rapport QA est réinjecté à l'agent pour une
nouvelle tentative (3 rondes maximum, chacune auditée). Si une capacité
`review` est configurée, la correction validée est **publiée pour revue
humaine** (branche + pull request) — ce qui rend le plan sensible : rien ne
quitte la machine sans validation explicite (`--yes`) et sans la permission
`publish`. La notification finale porte le lien de la revue.
Baygon ne modifie jamais le code lui-même et **ne favorise aucun agent**
(ENF-019) : il n'y a pas d'agent par défaut, la commande est déclarée dans
`baygon.yaml` — Claude Code, Aider, Codex CLI, Gemini CLI ou tout autre CLI,
au choix, via le même gabarit `{prompt}` :

```yaml
  dev:
    type: developer
    plugin: baygon_plugins.coding_agent:CodingAgent
    options:
      command: ["claude", "-p", "{prompt}"]              # ou :
      # command: ["aider", "--message", "{prompt}", "--yes"]
      # command: ["codex", "exec", "{prompt}"]
      # command: ["gemini", "-p", "{prompt}"]
```

Côté notifications, deux adaptateurs réels : **Slack** (webhook entrant, URL
lue dans `SLACK_WEBHOOK_URL`) et **e-mail** (SMTP, mot de passe dans
`SMTP_PASSWORD`). Et le noyau notifie automatiquement **tout échec
d'exécution** (plan, étape, cause) dès qu'une capacité `notification` est
configurée — sans jamais masquer le résultat structuré si le notificateur est
lui-même en panne.

L'interchangeabilité promise par les documents est démontrée par des paires
réelles : **GitHub ↔ GitLab** pour `repository`, **Render ↔ Fly.io** pour
`deployment` (l'exemple littéral du chapitre 8) — passer de l'un à l'autre est
un changement de `baygon.yaml`, jamais de code. Le déploiement en production
(systemd + reverse proxy TLS) est documenté dans
[`docs/11-deploiement.md`](docs/11-deploiement.md).

Pour la capacité `ai`, trois adaptateurs : **Claude** (SDK officiel
`anthropic`, `pip install baygon[claude]`, clé dans `ANTHROPIC_API_KEY`),
**compatible chat-completions** — un seul adaptateur pour **DeepSeek, Llama et
Qwen via Ollama, vLLM, Mistral, Groq et tout modèle local ou open source**
(`base_url` + `model` déclarés, clé optionnelle car les endpoints locaux n'en
demandent pas) — et l'**IA hors-ligne** (l'IA n'est jamais obligatoire).
Aucun défaut de fournisseur, nulle part.

Autre adaptateur réel : **Render** pour la capacité `deployment`
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
$ baygon run "montre-moi les traces de la production"
$ baygon run "analyse l'incident en production"
$ baygon doctor                         # ce qui marche ici, et ce qui manque
$ baygon run "corrige le dernier incident"   # confier l'incident à l'agent codeur
$ baygon history                        # historique des intentions exécutées
$ baygon context                        # contexte construit par le Context Engine
$ baygon resume [--plan ID] [--yes]     # reprendre la dernière exécution échouée
$ baygon run "ouvre une console ssh en production"   # commande de connexion (permission ssh)
```

**En mode IA, le modèle voit tout ce que Baygon sait faire** — les seize
intentions *et* les commandes déclarées par le projet (`RunCommand:test`), avec
une ligne disant à quoi chacune sert. Sans ça, « je voudrais lancer la suite de
tests » ne pouvait aboutir à aucune commande, faute d'en contenir le nom
littéral. Et sa réponse est lue telle que les modèles écrivent :
`**ShowMetrics**` est la même réponse que `ShowMetrics`. Seule la **forme** est
pardonnée — un libellé hors catalogue reste un refus, Baygon n'invente jamais
une action (Article 5).

Les règles déterministes passent toujours en premier : une formulation qu'elles
reconnaissent ne coûte aucun appel de modèle. La classification par un modèle
reste variable par nature — c'est précisément pourquoi elle n'arrive qu'en
dernier recours, et pourquoi `--no-ai` existe.

**Une erreur porte son remède.** Un adaptateur connaît presque toujours la
sortie au moment où il abandonne : la variable a un nom, l'endpoint une adresse,
les services déclarés une liste. `ActionableError` transporte cette
connaissance jusqu'au rapport d'échec, à côté de la cause. Rien ici ne demande
un modèle — ce que le code sait avec certitude n'a pas à être redeviné.

```console
$ baygon run "montre la base de données"
cause : environment variable 'JIYUFIT_DATABASE_URL' is not set
   → export JIYUFIT_DATABASE_URL=postgres://user:password@host:port/database
   → or hand it to the coding agent: run "corrige le dernier incident"
```

**Un état n'est jamais affirmé sans avoir été observé.** Un code de retour dit
qu'une commande a tourné ; il ne dit rien du système. `docker compose restart
web` réussit quand rien ne tourne — redémarrer zéro conteneur est un succès.
Baygon ne surveille pas les processus et ne peut pas observer seul : comme
tout le reste, l'observation se **déclare**, par une commande de statut par
service. Le contrat `service` a donc deux actions, agir et observer.

```yaml
  superviseur:
    options:
      services: {web: docker compose restart web}
      status:   {web: docker compose ps --status running web}
```

Trois réponses honnêtes, jamais « redémarré » sur la foi d'un code de retour :
`état observé` quand la commande de statut répond, `nothing-observed` quand
elle ne voit rien, `unknown` quand elle échoue — et `restart-requested`,
`verified: false`, quand aucune observation n'est déclarée. « Dans quel état
est le worker ? » interroge le superviseur sans rien redémarrer.

**Diagnostic** : `baygon doctor` répond à la question que ni `capabilities` ni
`context` ne traitaient — *qu'est-ce qui marche ici ?* Chaque intention est
confrontée à ce que le projet déclare et autorise, et ce qui manque est nommé
avec la ligne à ajouter. Déduit de la configuration seule : aucun fournisseur
n'est contacté, donc la réponse est immédiate et reste vraie même quand tout
est éteint. `GET /doctor` renvoie la même chose, sans paramètre `project` il
répond pour **tous** les projets à la fois — c'est là la vue d'ensemble.

**Prise en charge d'un incident** : « corrige le dernier incident » reprend la
trace journalisée — l'étape, la capacité, la cause, l'intention servie — et la
confie à l'agent codeur. Rien de nouveau derrière : la boucle Dev → QA
existante, la commande `test` déclarée comme contrôle indépendant, les rondes
bornées et la validation habituelle. L'offre n'apparaît que si une capacité
`developer` est déclarée : pas de promesse en l'air.

**Reprise** (ENF-017) : un plan interrompu par une panne fournisseur se reprend
avec `baygon resume` — les étapes déjà réussies ne sont jamais ré-exécutées,
leurs résultats enregistrés sont réutilisés et l'exécution redémarre à l'étape
en échec. La validation des plans sensibles s'applique aussi à la reprise.
La reprise rejoue **le plan approuvé, pas un autre** : les options de session
(`--no-ai`, `--model`) voyagent avec le plan, donc une exécution lancée en mode
déterministe ne se réveille jamais avec un appel de modèle (EF-014). Et un
résultat enregistré n'est réutilisé que si l'étape correspondante existe
toujours à l'identique — si `baygon.yaml` a changé entre l'échec et la reprise,
l'étape est simplement ré-exécutée.

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
| GET     | `/doctor`        | ce qui marche, ce qui manque — tous les projets sans `?project=` |
| POST    | `/plan`          | `{"intent": "…"}` → plan + explication           |
| POST    | `/run`           | `{"intent": "…", "approved": bool}` → résultat   |
| GET     | `/models`        | modèles IA sélectionnables et leur fraîcheur     |
| POST    | `/reload`        | recharge `baygon.yaml` à chaud (chapitre 10)     |

Un plan sensible renvoie `428` tant que `"approved": true` n'est pas fourni :
même règle que le terminal, Baygon propose, l'utilisateur décide.

Pendant qu'une requête est en vol, la page **désarme ses boutons** et affiche un
indicateur avec le temps écoulé — une étape IA dure des dizaines de secondes, et
sans signe de vie l'attente ressemble à une panne et invite à recliquer. Un
déploiement approuvé deux fois est un déploiement fait deux fois. Les boutons
sont réarmés quelle que soit l'issue, y compris sur panne réseau, qui s'affiche
au lieu de disparaître dans la console.

**Durcissement** : limitation de débit par client (120 req/min par défaut,
réglable via `--rate-limit`, `429` + `Retry-After` au-delà, `/health` exempté),
en-têtes de sécurité (`nosniff`, `no-store`, `X-Frame-Options: DENY` sur la
page), et chaque échec d'authentification est publié sur le bus d'événements
pour audit (ENF-009).

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

La suite est **hermétique** : aucun test ne sort de la machine, chaque
fournisseur est doublé, et elle tourne sur Linux, macOS et Windows (EF-018).

### Tests IA réels (opt-in)

Un modèle doublé prouve que Baygon appelle correctement l'adaptateur, jamais
que la réponse d'un vrai modèle survit au trajet — un modèle réel renvoie de la
prose, de la ponctuation, une première ligne vide, des blocs de raisonnement et
parfois un refus. `tests/test_live_ai.py` rejoue **les mêmes chemins de code
contre un endpoint qui répond vraiment**, et il est ignoré tant qu'aucun
endpoint n'est déclaré — la suite normale et la CI restent hermétiques.

```console
$ export BAYGON_LIVE_AI_BASE_URL=http://localhost:11434/v1   # Ollama, vLLM, DeepSeek, Groq…
$ export BAYGON_LIVE_AI_MODEL=deepseek-r1:8b
$ export BAYGON_LIVE_AI_KEY_ENV=DEEPSEEK_API_KEY             # optionnel
$ python -m unittest tests.test_live_ai -v
```

Ce qu'ils vérifient contre le vrai modèle : l'endpoint sert bien le modèle
déclaré, une complétion revient en texte exploitable, la classification ne
produit **jamais** autre chose qu'une intention connue ou un refus propre
(Article 5), `--no-ai` ne joint réellement pas le modèle (EF-014) et un
diagnostic complet passe de bout en bout. Les assertions portent sur les
**contrats, jamais sur une réponse particulière** : un modèle est libre de
classer une formulation comme il l'entend, ce qui doit tenir est que ce qui
revient soit exploitable.

La classe `UnreachableProviderTest` du même module tourne **toujours** : elle
n'a besoin d'aucun modèle, seulement d'un port fermé, et démontre sur un vrai
refus de connexion qu'un fournisseur injoignable dégrade au lieu de casser
(ENF-006).

## Licence

MIT — voir [LICENSE](LICENSE).
