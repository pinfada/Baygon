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
$ baygon run "pourquoi la production est lente ?"          # idem : diagnostic
$ baygon run "ouvre une console ssh en production"
$ baygon run "montre la base de données de production"
$ baygon run "liste les fichiers du stockage"
$ baygon run "sauvegarde la production"
$ baygon run "restaure la production" --yes  # CRITICAL : --yes obligatoire
$ baygon run "Résous le bug de paiement" --yes   # boucle Dev → QA → Revue (§6)
$ baygon run "propose les changements en revue" --yes
$ baygon resume                          # reprendre après une panne fournisseur
$ baygon history                         # tout est tracé
$ baygon context                         # ce que Baygon sait du projet
$ baygon capabilities                    # capacités et implémentations actives
$ baygon projects                        # projets gérés (voir §8)
```

Les quinze intentions reconnues : `DeployProject`, `RollbackDeployment`,
`FixBug`, `ProposeChanges`, `BackupProject`, `RestoreProject`, `OpenConsole`,
`RestartService`, `ShowDatabase`, `ShowStorage`, `Diagnose`, `ShowLogs`,
`ShowMetrics`, `ShowStatus`, `ShowHistory` — plus toute commande déclarée dans
la section `commands` de `baygon.yaml`, reconnue par son nom.

Vous n'avez pas à connaître ces noms : **décrivez le symptôme**, Baygon
reconnaît l'intention.

```console
$ baygon run "Les utilisateurs ne peuvent plus se connecter"   # → Diagnose
$ baygon run "Le paiement renvoie une 500, regarde ce qui se passe"
$ baygon run "La conso mémoire a doublé, tu peux voir d'où ça vient ?"
$ baygon run "Est-ce que la migration de cette nuit est bien passée ?"  # → ShowStatus
$ baygon run "Redémarre le worker"                             # → RestartService
```

Si aucune règle ne reconnaît la formulation **et** qu'une capacité `ai` est
configurée, le modèle classe la demande parmi ces intentions — il n'en invente
jamais d'autre, et le plan indique alors que l'intention a été identifiée par
l'IA. Sans IA, le comportement est inchangé : une erreur claire listant les
intentions connues (EF-014).

Règles à retenir :

- risque LOW/MEDIUM → exécution directe ;
- risque HIGH (production, publication) ou CRITICAL (restauration) →
  suspendu tant que `--yes` n'est pas donné ;
- une permission absente de `baygon.yaml` vaut **refus** (pas de défaut
  permissif). Permissions vérifiées : `deploy`, `production`,
  `database`, `ssh`, `publish`, `restart`.

---

## 5. Brancher les vrais fournisseurs

Remplacer un provider = éditer `baygon.yaml`, jamais le code. Les
secrets vont **toujours** dans l'environnement, jamais dans le fichier.

| Capacité    | Plugin                                              | Secret attendu |
|-------------|-----------------------------------------------------|----------------|
| repository  | `baygon_plugins.github_api:GitHubRepository`        | `GITHUB_TOKEN` |
| repository  | `baygon_plugins.gitlab_api:GitLabRepository`        | `GITLAB_TOKEN` |
| repository  | `baygon_plugins.local_git:LocalGitRepository`       | —              |
| deployment  | `baygon_plugins.render_deploy:RenderDeployment`     | `RENDER_API_KEY` |
| deployment  | `baygon_plugins.fly_deploy:FlyDeployment`           | auth flyctl    |
| logs        | `baygon_plugins.loki_logs:LokiLogs`                 | `LOKI_TOKEN` (option) |
| logs        | `baygon_plugins.file_logs:FileLogs`                 | —              |
| metrics     | `baygon_plugins.prometheus_metrics:PrometheusMetrics` | `PROMETHEUS_TOKEN` (option) |
| database    | `baygon_plugins.postgres_database:PostgresDatabase` | variable DSN (ex. `PROD_DATABASE_URL`) |
| storage/backup/recovery | `baygon_plugins.s3:S3Storage` / `S3Backup` / `S3Recovery` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| ssh         | `baygon_plugins.ssh_access:SSHAccess`               | clés ssh usuelles |
| ai          | `baygon_plugins.claude_ai:ClaudeAI`                 | `ANTHROPIC_API_KEY` |
| ai          | `baygon_plugins.openai_compat_ai:OpenAICompatibleAI` | selon `api_key_env` (aucun en local) |
| ai          | `baygon_plugins.offline_ai:OfflineAI`               | —              |
| workspace   | `baygon_plugins.local_shell:LocalShellWorkspace`    | —              |
| developer   | `baygon_plugins.coding_agent:CodingAgent`           | celui de l'agent choisi |
| review      | `baygon_plugins.github_review:GitHubReview`         | `GITHUB_TOKEN` |
| notification | `baygon_plugins.slack_notification:SlackNotification` | `SLACK_WEBHOOK_URL` |
| notification | `baygon_plugins.email_notification:EmailNotification` | `SMTP_PASSWORD` (option) |
| notification | `baygon_plugins.console_notification:ConsoleNotification` | — |
| service     | `baygon_plugins.command_service:CommandService`     | —              |
| secrets     | `baygon_plugins.env_secrets:EnvSecrets`             | —              |

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

Activer une IA pour le diagnostic — **n'importe laquelle**, propriétaire
ou open source (ENF-019 : aucun fournisseur n'est favorisé) :

```yaml
ai:
  default: claude          # ou deepseek, ou llama-local
  providers:
    claude:
      type: ai
      plugin: baygon_plugins.claude_ai:ClaudeAI
    deepseek:
      type: ai
      plugin: baygon_plugins.openai_compat_ai:OpenAICompatibleAI
      options:
        base_url: https://api.deepseek.com
        model: deepseek-chat
        api_key_env: DEEPSEEK_API_KEY
    llama-local:           # Ollama : aucune clé requise
      type: ai
      plugin: baygon_plugins.openai_compat_ai:OpenAICompatibleAI
      options: {base_url: "http://localhost:11434/v1", model: llama3}
```

Le même adaptateur `OpenAICompatibleAI` couvre DeepSeek, Ollama (Llama,
Qwen…), vLLM, Mistral, Groq, LM Studio — tout endpoint
`/chat/completions`. Sans clé ni fournisseur configuré, Baygon continue
en mode dégradé : l'IA n'est jamais obligatoire.

---

## 6. Corriger un bug de bout en bout (Dev → QA → Revue)

Déclarez un agent codeur (au choix) et la commande de test qui servira
de contrôle qualité indépendant :

```yaml
providers:
  dev:
    type: developer
    plugin: baygon_plugins.coding_agent:CodingAgent
    options:
      command: ["claude", "-p", "{prompt}"]              # ou :
      # command: ["aider", "--model", "deepseek", "--message", "{prompt}", "--yes"]
      # command: ["aider", "--model", "ollama/llama3", "--message", "{prompt}", "--yes"]
      cwd: .
  review:
    type: review
    plugin: baygon_plugins.github_review:GitHubReview
    options: {repository: mon-org/monapp, base: main}
commands:
  test: "npm test"          # la QA de Baygon, indépendante de l'agent
permissions:
  publish: true
```

```console
$ baygon plan "Résous le bug de paiement"      # inspecter avant d'agir
$ baygon run  "Résous le bug de paiement" --yes
```

Ce qui se passe :

1. l'agent codeur modifie les sources ;
2. Baygon exécute la commande `test` — c'est **lui** qui valide, pas
   l'agent ;
3. si les tests échouent, le rapport est réinjecté à l'agent et une
   nouvelle ronde démarre (**3 rondes maximum**, chacune journalisée) ;
4. au vert, la correction est publiée : branche `baygon/<horodatage>` +
   pull request ;
5. la notification finale porte le lien de la revue.

La publication sort de votre machine : le plan est donc **suspendu sans
`--yes`** et exige la permission `publish`. Sans capacité `review`
configurée, la correction reste locale et le plan n'est pas sensible.

---

## 7. Accès depuis un téléphone

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

## 8. Plusieurs projets

Chaque projet garde son `baygon.yaml`. Pour les piloter ensemble :

```console
$ baygon --projects ~/projets projects            # découverte
$ baygon --projects ~/projets run "Déploie MonApp en staging"   # routage par nom
$ baygon --projects ~/projets --project monapp history          # ciblage explicite
```

---

## 9. Récupération après sinistre (l'objectif fondateur)

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

## 10. Vérifier une installation

```console
$ python -m unittest discover -s tests     # depuis le dépôt Baygon
Ran 184 tests ... OK
```
