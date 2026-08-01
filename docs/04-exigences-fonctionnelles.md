# Chapitre 4 — Exigences Fonctionnelles

## Objectif

Ce document définit les fonctionnalités que Baygon devra fournir.

Toute fonctionnalité future devra être rattachée à l'une de ces exigences.

---

# EF-001 — Gestion des projets

Baygon doit permettre de gérer plusieurs projets.

Chaque projet est totalement indépendant.

Chaque projet possède :

- un nom ;
- une description ;
- un fournisseur Git ;
- un fournisseur Cloud ;
- un ou plusieurs environnements ;
- une configuration propre.

---

# EF-002 — Gestion des environnements

Baygon doit permettre de manipuler plusieurs environnements.

Minimum :

- Development
- Staging
- Production

Les commandes doivent fonctionner indépendamment de l'environnement.

---

# EF-003 — Compréhension du langage naturel

L'utilisateur doit pouvoir s'exprimer en langage naturel.

Exemples :

- Déploie JiyuFit.
- Pourquoi la production est lente ?
- Montre-moi les erreurs des dernières 24 heures.
- Ouvre une console Rails.
- Analyse le dernier incident.

---

# EF-004 — Shell

Baygon doit fournir un Shell unique.

Toutes les opérations passent par le Shell.

Le Shell peut être utilisé :

- en terminal ;
- via API ;
- via une interface graphique ;
- via une interface vocale (future).

---

# EF-005 — Gestion des fournisseurs

Baygon doit permettre d'ajouter, remplacer ou supprimer un fournisseur sans modifier le cœur du système.

---

# EF-006 — Exécution sécurisée

Toute action exécutée doit respecter les autorisations disponibles.

Baygon ne contourne jamais les mécanismes de sécurité des fournisseurs.

---

# EF-007 — Observabilité

Baygon doit être capable de consulter :

- les métriques ;
- les logs ;
- les traces ;
- les événements.

Baygon ne stocke pas ces données.

---

# EF-008 — Déploiement

Baygon doit permettre de lancer un déploiement.

Le déploiement est réalisé par le fournisseur.

Baygon ne déploie jamais directement.

---

# EF-009 — Diagnostic

Baygon doit être capable d'expliquer :

- une erreur ;
- un incident ;
- une dégradation de performances.

Le diagnostic est construit à partir des données disponibles.

---

# EF-010 — Connexion distante

Baygon doit permettre d'accéder aux ressources distantes autorisées.

Exemples :

- SSH
- Console Rails
- Base de données
- Terminal

---

# EF-011 — Gestion des secrets

Baygon doit utiliser un gestionnaire de secrets.

Aucun secret ne peut être stocké en clair.

---

# EF-012 — Historique

Toutes les actions exécutées doivent pouvoir être consultées.

L'historique contient :

- date ;
- utilisateur ;
- intention ;
- actions réalisées ;
- résultat.

---

# EF-013 — IA interchangeable

Le remplacement d'un modèle IA ne doit entraîner aucune modification du cœur.

---

# EF-014 — Mode hors assistance

Toutes les commandes essentielles doivent pouvoir être exécutées sans utiliser un modèle IA.

L'IA améliore l'expérience.

Elle n'est jamais une dépendance obligatoire.

---

# EF-015 — Configuration

Chaque projet est décrit par un unique fichier :

baygon.yaml

Ce fichier constitue la source de vérité du projet.

---

# EF-016 — Architecture sans état

Baygon ne conserve aucun état métier permanent.

Il utilise uniquement :

- les fournisseurs ;
- les fichiers de configuration ;
- les informations nécessaires à son fonctionnement.

---

# EF-017 — Extensibilité

L'ajout d'un nouveau fournisseur ne nécessite aucune modification du cœur.

---

# EF-018 — Portabilité

Baygon doit fonctionner sur :

- Linux
- macOS
- Windows
- Android (Shell)
- iOS (Shell)

---

# EF-019 — Faible maintenance

Le nombre de dépendances doit être limité.

Toute dépendance doit être justifiée.

---

# EF-020 — Temps de réponse

Une commande simple doit répondre en moins de 2 secondes.

Une commande nécessitant une IA doit afficher une progression et retourner une réponse dès que possible.

---

# Critères d'acceptation

Baygon est conforme si :

- un nouveau projet peut être ajouté sans modifier le code ;
- un fournisseur peut être remplacé en modifiant uniquement sa configuration ;
- un modèle IA peut être remplacé sans impact sur le reste du système ;
- toutes les fonctionnalités essentielles restent accessibles depuis un téléphone ;
- Baygon reste un orchestrateur et non un remplaçant des outils existants.
