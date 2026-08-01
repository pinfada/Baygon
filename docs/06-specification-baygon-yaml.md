# Chapitre 6 — Spécification de `baygon.yaml`

## Objectif

`baygon.yaml` est le point d'entrée unique de Baygon.

Il décrit entièrement un projet.

Baygon ne fait aucune hypothèse.

Tout ce qu'il doit connaître est déclaré dans ce fichier.

---

# Principes

Un projet = un fichier.

Le fichier est lisible par un humain.

Le fichier est versionné avec le projet.

Le fichier constitue la source de vérité.

---

# Emplacement

À la racine du dépôt.

```
/
├── app/
├── config/
├── docker/
├── README.md
└── baygon.yaml
```

---

# Structure générale

```yaml
version:

project:

providers:

environments:

workspaces:

ai:

observability:

commands:

permissions:

metadata:
```

---

# version

Version du schéma.

Exemple :

```yaml
version: 1
```

---

# project

Informations générales.

```yaml
project:
  name:
  description:
  repository:
  language:
  framework:
```

---

# providers

Liste des fournisseurs.

Chaque fournisseur possède :

- un nom ;
- un type ;
- une configuration.

Exemple :

```yaml
providers:

  git:

  cloud:

  database:

  redis:

  monitoring:

  storage:

  secrets:
```

---

# environments

Déclaration des environnements.

Minimum :

```yaml
development

staging

production
```

Chaque environnement possède ses propres paramètres.

---

# workspaces

Décrit les environnements de développement.

Exemple :

```yaml
workspaces:

  default:

  mobile:

  ci:
```

---

# ai

Configuration des modèles.

Exemple :

```yaml
ai:

  default:

  fallback:

  local:

  providers:
```

Le changement de modèle ne nécessite qu'une modification de ce bloc.

---

# observability

Déclare où récupérer :

- les logs ;
- les métriques ;
- les traces.

Baygon ne stocke rien.

---

# commands

Permet de déclarer les commandes spécifiques au projet.

Exemple :

```yaml
commands:

  deploy:

  test:

  migrate:

  console:
```

Baygon connaît ainsi les commandes sans les coder.

---

# permissions

Déclare les opérations autorisées.

Exemple :

```yaml
permissions:

  deploy:

  production:

  database:

  ssh:
```

---

# metadata

Informations libres.

Exemple :

```yaml
metadata:

  owner:

  team:

  tags:

  documentation:
```

---

# Règles

Un seul fichier.

Un seul format.

Une seule source de vérité.

Les valeurs par défaut sont interdites lorsqu'elles peuvent entraîner une ambiguïté.

Les commentaires sont autorisés.

---

# Validation

Baygon valide automatiquement :

- la structure ;
- les types ;
- les références ;
- les fournisseurs ;
- les environnements.

Un fichier invalide interdit l'exécution.

---

# Évolution

Toute évolution du schéma entraîne une augmentation du numéro de version.

Baygon doit assurer la compatibilité ascendante autant que possible.

---

# Objectifs

Le fichier doit permettre à Baygon de comprendre immédiatement :

- ce qu'est le projet ;
- où il est hébergé ;
- comment il est développé ;
- comment il est déployé ;
- où récupérer les métriques ;
- où récupérer les logs ;
- quel modèle IA utiliser ;
- quelles commandes exécuter ;
- quelles permissions appliquer.

Aucune information nécessaire au fonctionnement ne doit être codée dans Baygon si elle peut être décrite dans `baygon.yaml`.
