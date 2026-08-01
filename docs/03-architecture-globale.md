# Chapitre 3 — Architecture Globale

## Objectif

Baygon est une couche d'orchestration entre l'utilisateur, les fournisseurs de services et les modèles d'intelligence artificielle.

Le cœur de Baygon ne contient aucune logique métier.

Il fournit un contexte, sélectionne les outils appropriés et exécute les actions demandées.

---

# Architecture logique

```
                    Utilisateur
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
     Téléphone        Tablette        Ordinateur
                          │
                          ▼
                  Baygon Shell
                          │
              Intent Engine (IA)
                          │
                  Context Engine
                          │
                 Provider Manager
                          │
 ┌──────────────┬──────────────┬──────────────┬──────────────┐
 │              │              │              │              │
GitHub      Render      PostgreSQL      Grafana      SSH
 │              │              │              │              │
 └──────────────┴──────────────┴──────────────┴──────────────┘
```

---

# Les composants

## Baygon Shell

Point d'entrée unique.

Il reçoit les intentions de l'utilisateur.

Interfaces possibles :

- Terminal
- API
- Interface Web
- Voix (future)
- Applications mobiles (future)

Le Shell ne contient aucune logique métier.

---

## Intent Engine

Traduit une intention humaine en plan d'exécution.

Exemple :

> Analyse les performances de JiyuFit.

↓

Plan :

- récupérer les métriques ;
- récupérer les logs ;
- récupérer les derniers déploiements ;
- envoyer le contexte au modèle IA.

---

## Context Engine

Construit le contexte nécessaire.

Il sait :

- quels projets existent ;
- quels fournisseurs sont utilisés ;
- où sont les métriques ;
- où sont les logs ;
- où sont les secrets ;
- quelles autorisations sont disponibles.

Le Context Engine ne réalise aucune action.

Il prépare uniquement le contexte.

---

## Provider Manager

Point d'entrée unique vers les fournisseurs.

Il expose une interface commune.

Exemple :

```
deploy()

logs()

metrics()

ssh()

secrets()

database()

storage()
```

Chaque fournisseur implémente cette interface.

---

## Providers

Chaque fournisseur est indépendant.

Exemples :

- GitHub
- Render
- Docker
- PostgreSQL
- Redis
- Grafana
- Loki
- Cloudflare
- Stripe

Aucun provider ne dépend d'un autre.

---

## AI Provider

Baygon ne dépend jamais d'un modèle unique.

Chaque fournisseur IA implémente la même interface.

Exemples :

- OpenAI
- Claude
- DeepSeek
- Gemini
- Qwen
- Modèle local

Le remplacement d'un modèle ne nécessite aucune modification du cœur.

---

# Flux d'exécution

Une demande suit toujours le même cycle.

```
Utilisateur

↓

Shell

↓

Intent Engine

↓

Context Engine

↓

Provider Manager

↓

Providers

↓

Contexte enrichi

↓

IA

↓

Réponse

↓

Utilisateur
```

---

# Responsabilités

## Baygon

Responsable de :

- comprendre une intention ;
- construire un contexte ;
- appeler les bons fournisseurs ;
- sécuriser les échanges ;
- restituer une réponse.

---

## Les fournisseurs

Responsables de :

- stocker les données ;
- exécuter les actions ;
- fournir les API.

---

## Le modèle IA

Responsable de :

- raisonner ;
- expliquer ;
- proposer ;
- générer.

Le modèle IA ne possède aucune connaissance permanente de l'infrastructure.

---

# Règles d'architecture

Une couche ne peut communiquer qu'avec la couche immédiatement inférieure.

Les dépendances circulaires sont interdites.

Le cœur de Baygon ne dépend d'aucun fournisseur.

Les providers ne communiquent jamais entre eux.

Toute communication externe passe par le Provider Manager.

---

# Critères de validation

L'architecture est conforme si :

- un fournisseur peut être remplacé sans modifier le cœur ;
- un modèle IA peut être remplacé sans modifier le cœur ;
- un nouveau projet peut être ajouté sans modifier le cœur ;
- une nouvelle interface (Web, CLI, Mobile...) peut être ajoutée sans modifier le cœur ;
- Baygon reste principalement un orchestrateur.
