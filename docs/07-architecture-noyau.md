# Chapitre 7 — Architecture du Noyau (Core)

## Objectif

Le Core est le seul composant obligatoire de Baygon.

Il ne contient aucune logique métier.

Il orchestre uniquement les différents composants.

---

# Responsabilités

Le Core est responsable de :

- charger la configuration ;
- charger les plugins ;
- résoudre les intentions ;
- sélectionner les providers ;
- exécuter les actions ;
- journaliser les opérations ;
- retourner le résultat.

---

# Ce que le Core ne fait jamais

Le Core ne :

- déploie pas ;
- ne collecte pas les métriques ;
- ne stocke pas les logs ;
- ne se connecte pas directement aux APIs ;
- ne connaît pas GitHub ;
- ne connaît pas Render ;
- ne connaît pas PostgreSQL ;
- ne connaît pas Docker ;
- ne connaît pas OpenAI ;
- ne connaît pas Claude ;
- ne connaît pas DeepSeek.

Le Core ne connaît que des interfaces.

---

# Architecture

```
                    Baygon Core
                           │
 ┌──────────────┬──────────┼──────────┬──────────────┐
 │              │          │          │              │
Config      Intent     Provider    Plugin       Event Bus
Loader      Engine     Manager     Manager        Manager
```

---

# Config Loader

Responsable de :

- lire baygon.yaml ;
- valider le schéma ;
- construire la configuration mémoire.

---

# Intent Engine

Responsable de :

- interpréter la demande utilisateur ;
- construire un plan d'exécution.

Il ne réalise aucune action.

---

# Provider Manager

Responsable de :

- découvrir les providers ;
- sélectionner le bon provider ;
- exécuter les appels.

---

# Plugin Manager

Responsable de :

- charger les plugins ;
- vérifier leur compatibilité ;
- enregistrer leurs commandes ;
- gérer leur cycle de vie.

---

# Event Manager

Responsable de :

- publier les événements ;
- distribuer les événements ;
- permettre aux plugins de réagir.

Exemples :

ProjectOpened

DeploymentStarted

DeploymentFinished

ProviderFailed

CommandExecuted

---

# Interfaces

Tous les composants communiquent uniquement par interfaces.

Aucun composant ne dépend d'une implémentation concrète.

---

# Cycle de vie

Démarrage

↓

Lecture de baygon.yaml

↓

Validation

↓

Chargement des plugins

↓

Chargement des providers

↓

Prêt

---

# Exécution

Utilisateur

↓

Intent

↓

Plan

↓

Providers

↓

Résultat

↓

Utilisateur

---

# Erreurs

Une erreur dans un provider ne doit jamais arrêter le Core.

Le Core capture :

- erreur ;
- origine ;
- gravité ;
- action proposée.

---

# Journalisation

Chaque action génère un événement.

Le Core n'analyse jamais les événements.

Il les publie.

---

# Dépendances

Le Core ne dépend que :

- du système de fichiers ;
- du parser YAML ;
- du moteur de plugins ;
- du moteur d'événements.

Toute autre dépendance est interdite.

---

# Taille

Le Core doit rester volontairement petit.

Objectif :

- moins de 5 000 lignes de code.

Objectif idéal :

- moins de 3 000 lignes.

---

# Critères d'acceptation

Le Core est conforme si :

- aucun provider n'est codé en dur ;
- aucun modèle IA n'est codé en dur ;
- aucun projet n'est codé en dur ;
- tous les composants sont remplaçables ;
- le Core peut démarrer sans connaître un projet particulier.

---

# Règle fondamentale

Le Core est stable.

Tout le reste est extensible.
