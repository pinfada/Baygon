# Chapitre 12 — Mode opératoire

Toutes les commandes de ce chapitre ont été vérifiées sur l'état actuel
du dépôt.

---

## 1. Prérequis

- Python ≥ 3.10 ;
- git ;
- les outils spécialisés que vous comptez orchestrer (psql, flyctl, …)
  restent installés séparément : Baygon les pilote, il ne les remplace
  pas.

---

## 2. Installation

```console
$ git clone https://github.com/pinfada/Baygon.git
$ cd Baygon
$ python3 -m venv .venv && source .venv/bin/activate   # recommandé
$ pip install -e .
$ baygon --version
baygon 0.1.0
```

Pour utiliser l'adaptateur Claude : `pip install -e ".[claude]"`.

---

## 3. Initialiser un projet

Un projet = un fichier `baygon.yaml` à la racine de son dépôt.
Point de départ minimal fonctionnel :

```yaml
version: 1
project:
  name: monapp
providers:
  git:
    type: repository
    plugin: baygon_plugins.local_git:LocalGitRepository
    default: true
    options: {path: .}
  cloud:
    type: deployment
    plugin: baygon_plugins.mock_deploy:MockDeployment   # à remplacer, voir §5
    default: true
environments:
  development: {}
  staging: {}
  production: {}
permissions:
  deploy: true
  production: true
```

Toujours valider avant d'utiliser :

```console
$ baygon validate
ok: baygon.yaml is valid (project 'monapp')
```

Un fichier invalide interdit toute exécution — c'est voulu.

---

## 4. Utilisation quotidienne

Toutes les commandes acceptent le langage naturel (français ou anglais).

```console
$ baygon plan "deploy to staging"        # voir le plan SANS exécuter
$ baygon explain "restaure la production"  # comprendre le raisonnement
$ baygon run "deploy to staging"         # exécuter
$ baygon run "Déploie en production" --yes   # action sensible : validation
$ baygon run "montre-moi les erreurs des dernières 24 heures en production"
$ baygon run "analyse le dernier incident en production"   # diagnostic complet
$ baygon run "ouvre une console ssh en production"
$ baygon run "sauvegarde la production"
$ baygon run "restaure la production" --yes  # CRITICAL : --yes obligatoire
$ baygon resume                          # reprendre après une panne fournisseur
$ baygon history                         # tout est tracé
$ baygon context                         # ce que Baygon sait du projet
$ baygon capabilities                    # capacités et implémentations actives
```

Règles à retenir :

- risque LOW/MEDIUM → exécution directe ;
- risque HIGH (production) ou CRITICAL (restauration) → suspendu tant
  que `--yes` n'est pas donné ;
- une permission absente de `baygon.yaml` vaut **refus** (pas de défaut
  permissif).

---

## 5. Brancher les vrais fournisseurs

Remplacer un provider = éditer `baygon.yaml`, jamais le code. Les
secrets vont **toujours** dans l'environnement, jamais dans le fichier.

| Capacité    | Plugin                                              | Secret attendu |
|-------------|-----------------------------------------------------|----------------|
| repository  | `baygon_plugins.github_api:GitHubRepository`        | `GITHUB_TOKEN` |
| repository  | `baygon_plugins.gitlab_api:GitLabRepository`        | `GITLAB_TOKEN` |
| deployment  | `baygon_plugins.render_deploy:RenderDeployment`     | `RENDER_API_KEY` |
| deployment  | `baygon_plugins.fly_deploy:FlyDeployment`           | auth flyctl    |
| logs        | `baygon_plugins.loki_logs:LokiLogs`                 | `LOKI_TOKEN` (option) |
| metrics     | `baygon_plugins.prometheus_metrics:PrometheusMetrics` | `PROMETHEUS_TOKEN` (option) |
| database    | `baygon_plugins.postgres_database:PostgresDatabase` | variable DSN (ex. `PROD_DATABASE_URL`) |
| storage/backup/recovery | `baygon_plugins.s3:S3Storage` / `S3Backup` / `S3Recovery` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| ssh         | `baygon_plugins.ssh_access:SSHAccess`               | clés ssh usuelles |
| ai          | `baygon_plugins.claude_ai:ClaudeAI`                 | `ANTHROPIC_API_KEY` |
| workspace   | `baygon_plugins.local_shell:LocalShellWorkspace`    | —              |

Exemple — passer au vrai GitHub et à Render :

```yaml
providers:
  git:
    type: repository
    plugin: baygon_plugins.github_api:GitHubRepository
    default: true
    options: {repository: mon-org/monapp}
  cloud:
    type: deployment
    plugin: baygon_plugins.render_deploy:RenderDeployment
    default: true
    options:
      services: {staging: srv-xxxx, production: srv-yyyy}
```

```console
$ export GITHUB_TOKEN=ghp_...  RENDER_API_KEY=rnd_...
$ baygon validate && baygon run "deploy to staging"
```

Activer Claude pour le diagnostic :

```yaml
ai:
  default: claude
  providers:
    claude:
      type: ai
      plugin: baygon_plugins.claude_ai:ClaudeAI
```

```console
$ export ANTHROPIC_API_KEY=sk-ant-...
```

Sans clé ni SDK, Baygon continue en mode dégradé : l'IA n'est jamais
obligatoire.

---

## 6. Accès depuis un téléphone

```console
$ export BAYGON_API_TOKEN=$(openssl rand -hex 32)
$ echo "$BAYGON_API_TOKEN"        # à conserver dans votre gestionnaire de mots de passe
$ baygon serve --host 0.0.0.0 --port 8787
baygon api listening on http://0.0.0.0:8787 [authenticated]
```

Puis, sur le téléphone (même réseau) : ouvrir `http://<ip>:8787/`,
saisir le jeton, exprimer une intention. Un plan sensible affiche le
bouton « Approuver l'action sensible ».

En développement local uniquement : `baygon serve --insecure`.

Pour Internet : **jamais en direct** — voir le chapitre 11
(systemd + reverse proxy TLS).

Recharger la configuration sans redémarrer :

```console
$ curl -X POST -H "Authorization: Bearer $BAYGON_API_TOKEN" localhost:8787/reload
```

---

## 7. Plusieurs projets

Chaque projet garde son `baygon.yaml`. Pour les piloter ensemble :

```console
$ baygon --projects ~/projets projects            # découverte
$ baygon --projects ~/projets run "Déploie MonApp en staging"   # routage par nom
$ baygon --projects ~/projets --project monapp history          # ciblage explicite
```

---

## 8. Récupération après sinistre (l'objectif fondateur)

Nouvel ordinateur, cinq minutes :

```console
$ git clone https://github.com/pinfada/Baygon.git && cd Baygon && pip install -e .
$ git clone <votre-projet> && cd <votre-projet>
$ export GITHUB_TOKEN=... RENDER_API_KEY=...      # depuis le gestionnaire de secrets
$ baygon validate && baygon context
```

Tout l'état vit dans les fournisseurs et dans `baygon.yaml` versionné :
il n'y a rien d'autre à restaurer.

---

## 9. Vérifier une installation

```console
$ python -m unittest discover -s tests     # depuis le dépôt Baygon
Ran 155 tests ... OK
```
