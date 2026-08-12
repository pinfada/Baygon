# Chapitre 14 — Le workspace : une commande, un parc de projets

Baygon est né dépôt par dépôt : un `baygon.yaml`, un noyau, un journal.
La vraie question de l'opérateur est plus large — « est-ce que nous
avons des incidents ? » sur tout ce qu'il fait tourner. Le workspace
ajoute exactement deux choses au-dessus des noyaux existants :
l'éventail (interroger chaque projet en parallèle) et la synthèse
(répondre comme un briefing, pas comme un log).

Ce qu'il n'ajoute délibérément **pas** : du contexte partagé. Chaque
projet garde son noyau, ses fournisseurs, son journal et ses
permissions — l'isolation n'est pas une option, c'est la construction.
Un modèle interrogé sur un projet ne voit jamais les logs ni le code
d'un autre.

---

## 1. Le fichier `baygon-workspace.yaml`

```yaml
version: 1
workspace:
  name: parc-perso

projects:               # nom → chemin (relatif au fichier, ou absolu)
  paiement: {path: ../service-paiement}
  core:     {path: ../api-core}
  front:    {path: ../frontend}

policy:                 # tout est opt-in ; rien par défaut (Article 7)
  autonomous: true      # approuve les plans sensibles sans --yes
  self_heal: true       # un run qui échoue déclenche « corrige le dernier incident »

orchestrator:           # optionnel — le méta-agent qui rédige la synthèse
  plugin: baygon_plugins.claude_ai:ClaudeAI
  options: {model: claude-sonnet-5}
```

Validation stricte, comme un fichier projet : une section inconnue ou
une clé de politique mal orthographiée est refusée — une politique qui
retomberait silencieusement à `false` serait exactement le genre
d'échec discret que Baygon refuse. Un projet dont le chargement échoue
est isolé et signalé (`unavailable`), jamais fatal aux autres.

## 2. Les commandes

```console
$ baygon workspace validate
$ baygon workspace projects
$ baygon workspace run "est-ce que nous avons des incidents ?"
$ baygon workspace run "déploie en staging" --yes    # approbation ponctuelle
$ baygon workspace run "…" --json                    # les faits bruts, pour une machine
```

Le pipeline est silencieux : une ligne par événement sur la sortie
d'erreur (`Inspection de 4 projet(s)…`, `Auto-correction en cours sur
[paiement]…`), jamais le détail étape par étape d'un projet. La sortie
standard ne porte que le rapport.

## 3. La politique du seul opérateur

- **`autonomous: true`** — les plans sensibles (HIGH, CRITICAL) sont
  approuvés comme si `--yes` était passé. À déclarer en connaissance de
  cause : c'est l'équivalent permanent de l'approbation manuelle.
- **`self_heal: true`** — un run qui échoue est un incident : le
  workspace enchaîne « corrige le dernier incident » sur ce projet, en
  réutilisant la boucle Dev → QA existante, inchangée — mêmes rondes
  bornées (3), même porte QA indépendante. La guérison n'est tentée que
  si l'exécution était approuvée (politique ou `--yes`).

Sans politique déclarée, rien ne change : un plan sensible attend la
validation, un échec est rapporté tel quel.

## 4. Le rapport d'impact

Le contrat de sortie est une synthèse décisionnelle, pas un log :

```
----------------------------------------------------------------------
STATUT GLOBAL : 🟠 1 incident détecté et corrigé automatiquement
----------------------------------------------------------------------

[paiement]
• Incident : « déploie en staging » a échoué — provider exploded
• Action   : correctif appliqué par l'agent de code (1 ronde), QA repassée au vert
• Impact   : incident détecté et corrigé automatiquement en 3,2 s

[core, front]
🟢 Aucun incident à signaler.
```

Trois statuts globaux : 🟢 tout est opérationnel, 🟠 incident(s)
détecté(s) et corrigé(s) automatiquement, 🔴 intervention requise.
Le code de sortie suit : `0` pour 🟢/🟠, `1` pour 🔴.

Quand l'auto-correction échoue (3 rondes QA sans succès), le repli
est explicite :

```
[paiement]
• Incident : « déploie en staging » a échoué — provider exploded
• Auto-correction échouée après 3 rondes — 2 tests failed: test_refund, test_checkout
• Intervention requise.
```

Le rapport ne dit que ce que le journal sait : cause, action, rondes,
durées. Aucun chiffre inventé.

## 5. L'orchestrateur (méta-agent)

Le bloc `orchestrator` déclare le modèle qui **rédige** la synthèse —
n'importe quel adaptateur IA existant convient (neutralité de
fournisseur, ENF-019) : le rôle est défini par le prompt système que
le workspace lui donne, pas par un nouveau type de plugin. Ce prompt
lui interdit d'inventer un fait absent des données ; il reçoit les
faits du journal, et rien d'autre.

Sans orchestrateur — ou quand le modèle est injoignable — le rendu
déterministe ci-dessus répond à sa place : dégradé, jamais cassé
(EF-014). Le format est garanti par le repli, amélioré par le modèle.

## 6. Ce que le workspace garantit

| Garantie | Comment |
|---|---|
| Isolation des contextes | un noyau, un registre, un journal par projet |
| Panne isolée | un projet cassé est signalé, les autres répondent |
| Sécurité par défaut | `autonomous` et `self_heal` sont opt-in, jamais supposés |
| Boucles bornées | la guérison réutilise la boucle Dev → QA (3 rondes max) |
| Parallélisme borné | au plus 8 projets inspectés à la fois |
| Traçabilité | chaque run, chaque guérison : journalisés dans le projet concerné |
| Dégradé, jamais cassé | sans orchestrateur, le rapport déterministe répond |
