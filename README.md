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
   Baygon Shell          baygon/shell/      point d'entrée unique, sans logique métier
        │
   Intent Engine         baygon/core/intent.py    intention → plan (pense, n'agit jamais)
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

Les contrats de capacités (`baygon/capabilities/`) définissent *ce qui peut
être fait*, jamais *comment* : repository, deployment, logs, metrics,
database, secrets, notification, ai.

Les implémentations de référence (`baygon_plugins/`) vivent **hors du noyau**
et ne sont chargées que si `baygon.yaml` les déclare : git local, déploiement
simulé, logs fichiers, métriques statiques, secrets d'environnement,
notifications console, IA hors-ligne (l'IA n'est jamais une dépendance
obligatoire).

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
```

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
