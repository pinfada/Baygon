# Chapitre 9 — Intent Engine

## Objectif

L'Intent Engine est le cerveau de Baygon.

Il transforme une intention utilisateur en plan d'exécution.

Il ne réalise jamais les actions lui-même.

---

# Responsabilités

L'Intent Engine est responsable de :

- comprendre une intention ;
- identifier les capacités nécessaires ;
- construire un plan d'exécution ;
- demander les validations si nécessaire ;
- retourner un plan au moteur d'exécution.

---

# Ce que l'Intent Engine ne fait jamais

Il ne :

- contacte pas GitHub ;
- contacte pas Render ;
- contacte pas PostgreSQL ;
- exécute pas SSH ;
- appelle pas directement un modèle IA.

Il produit uniquement un plan.

---

# Entrées

L'Intent Engine accepte plusieurs formes d'entrée.

- langage naturel ;
- commande Shell ;
- API REST ;
- évènement ;
- automatisation.

Toutes sont converties en une intention unique.

---

# Exemple

Entrée :

"Déploie JiyuFit."

↓

Intention

DeployProject

↓

Plan

1. Identifier le projet.
2. Identifier l'environnement.
3. Vérifier les permissions.
4. Identifier la capacité Deployment.
5. Construire le plan.

---

# Plan d'exécution

Un plan est une liste d'étapes.

Chaque étape possède :

- un identifiant ;
- une capacité ;
- une action ;
- des paramètres ;
- des dépendances ;
- un niveau de risque.

Exemple :

Step 1

Capability : Repository

Action : GetLatestCommit

↓

Step 2

Capability : Deployment

Action : Deploy

↓

Step 3

Capability : Notification

Action : NotifySuccess

---

# Validation

Certaines actions nécessitent une validation.

Exemples :

- suppression ;
- restauration ;
- production ;
- rotation des secrets.

Le plan est suspendu jusqu'à validation.

---

# Niveaux de risque

LOW

Lecture.

---

MEDIUM

Modification réversible.

---

HIGH

Modification de production.

---

CRITICAL

Action destructive.

---

# Optimisation

L'Intent Engine peut :

- fusionner des étapes ;
- supprimer des doublons ;
- exécuter des actions en parallèle ;
- réutiliser des résultats déjà disponibles.

---

# Gestion des erreurs

Si une étape échoue,

le plan est interrompu.

Le moteur reçoit :

- l'étape en erreur ;
- la cause ;
- les actions possibles.

---

# Explication

L'utilisateur peut toujours demander :

Pourquoi ?

L'Intent Engine doit être capable d'expliquer :

- son raisonnement ;
- les capacités choisies ;
- les actions prévues.

---

# Audit

Chaque plan est journalisé.

Les informations minimales sont :

- date ;
- utilisateur ;
- intention ;
- plan généré ;
- résultat.

---

# Interface

Entrée

↓

Intention

↓

Analyse

↓

Plan

↓

Validation

↓

Exécution

↓

Résultat

---

# Critères d'acceptation

L'Intent Engine est conforme si :

- il ne dépend d'aucun fournisseur ;
- il ne dépend d'aucun projet ;
- il produit toujours un plan explicable ;
- il permet la validation des actions sensibles ;
- il reste totalement déterministe à contexte identique.

---

# Règle fondamentale

L'Intent Engine pense.

Il n'agit jamais.
