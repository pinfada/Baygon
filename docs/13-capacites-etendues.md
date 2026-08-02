# Chapitre 13 — Capacités étendues

## Objectif

Le chapitre 8 fixe la liste des **capacités minimales**. Ce chapitre
documente les capacités ajoutées ensuite, conformément à l'Article 11
(toute décision d'architecture importante est documentée) et à
l'Article 2 (chaque nouvelle fonctionnalité doit démontrer un bénéfice
concret).

Ces capacités respectent les mêmes règles que les autres : un contrat,
plusieurs implémentations possibles, aucune connaissance du fournisseur
dans le noyau.

---

## Developer

Modification du code source par un agent spécialisé.

### Contrat

```
fix(description, feedback=None)
```

`feedback` transporte le rapport de la tentative précédente lorsque le
contrôle qualité a échoué.

### Justification

Le chapitre 1 vise un développeur qui travaille depuis n'importe quel
appareil. Corriger un bug depuis un téléphone suppose que quelqu'un
écrive le code. Baygon ne l'écrit pas : il **orchestre un agent
spécialisé**, exactement comme il orchestre git, flyctl ou psql
(Article 3).

### Neutralité

Aucun agent par défaut (ENF-019). La commande est déclarée dans
`baygon.yaml` et n'importe quel CLI convient :

```yaml
command: ["claude", "-p", "{prompt}"]
command: ["aider", "--model", "deepseek", "--message", "{prompt}", "--yes"]
command: ["aider", "--model", "ollama/llama3", "--message", "{prompt}", "--yes"]
command: ["codex", "exec", "{prompt}"]
command: ["gemini", "-p", "{prompt}"]
```

L'authentification reste celle de l'agent, jamais celle de Baygon.

---

## Review

Publication du travail pour revue humaine.

### Contrat

```
publish(title, body="")
```

Retourne au minimum `state`, `branch` et `url`.

### Justification

Un travail validé qui reste sur la machine ne sert à rien. La capacité
`review` pousse une branche et ouvre une pull/merge request chez le
fournisseur Git. Baygon n'écrit pas le diff : l'agent l'a produit,
Baygon publie.

### Sensibilité

Publier fait sortir le travail de la machine. Les plans qui publient
sont donc **HIGH** et suspendus jusqu'à validation explicite
(Article 9), en plus de la permission `publish`.

---

## La boucle Dev → QA → Revue

Ces deux capacités, combinées à `workspace` et `notification`,
produisent l'intention `FixBug` :

```
developer.fix
      │
      ▼
workspace.execute (commande `test` déclarée — la QA appartient à Baygon)
      │
   ┌──┴───────────────┐
   ▼                  ▼
ÉCHEC              SUCCÈS
rapport réinjecté  review.publish  →  notification + lien
(3 rondes max)
```

Deux mécanismes génériques du noyau rendent cela possible, sans aucune
logique spécifique à une capacité :

- **rondes bornées** — un plan déclare `max_rounds` et `feedback_step` ;
  une ronde échouée est rejouée avec le rapport d'échec injecté dans
  l'étape désignée. Chaque ronde est journalisée.
- **références aux résultats** — `{{étape.champ}}` dans un paramètre
  chaîne est résolu depuis le résultat de l'étape référencée
  (chapitre 9 : « réutiliser des résultats déjà disponibles »). C'est
  ainsi que la notification porte l'URL de la revue.

Ces mécanismes sont réutilisables par toute intention future.

---

## Règle

Une capacité étendue ne devient légitime que si elle satisfait les
mêmes critères que les capacités minimales :

- elle décrit ce qui peut être fait, jamais comment ;
- elle admet plusieurs implémentations ;
- son absence dégrade proprement le système sans le casser ;
- le noyau ne connaît aucun de ses fournisseurs.
