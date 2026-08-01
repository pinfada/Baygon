# Chapitre 10 — Capability Registry

## Objectif

Le Capability Registry est le catalogue central de Baygon.

Il référence toutes les capacités disponibles et leurs implémentations.

Le Core n'utilise jamais directement une implémentation.

Il interroge toujours le Registry.

---

# Responsabilités

Le Capability Registry est responsable de :

- découvrir les capacités ;
- enregistrer les implémentations ;
- résoudre les dépendances ;
- sélectionner une implémentation ;
- vérifier la compatibilité ;
- exposer les capacités disponibles.

---

# Architecture

```
Capability

↓

Registry

↓

Implementations

↓

Execution
```

---

# Exemple

Capability

Repository

↓

Registry

↓

GitHub

GitLab

Forgejo

Gitea

↓

GitHub sélectionné

---

# Sélection

Une capacité peut posséder plusieurs implémentations.

Le Registry applique les règles suivantes.

1.

Implémentation explicitement demandée.

2.

Implémentation par défaut.

3.

Implémentation compatible.

4.

Erreur.

---

# Interface

Chaque implémentation expose la même interface.

Exemple

Repository

```
clone()

pull()

push()

branch()

commit()

diff()

history()
```

Toutes les implémentations doivent respecter ce contrat.

---

# Cycle de vie

Découverte

↓

Validation

↓

Enregistrement

↓

Activation

↓

Disponible

---

# États

Une implémentation possède un état.

ACTIVE

Disponible.

---

INACTIVE

Désactivée.

---

FAILED

Erreur.

---

DEPRECATED

Obsolète.

---

UNKNOWN

État inconnu.

---

# Métadonnées

Chaque implémentation expose :

- identifiant ;
- version ;
- auteur ;
- licence ;
- compatibilité ;
- capacités fournies ;
- dépendances.

---

# Compatibilité

Une implémentation peut déclarer :

- système d'exploitation ;
- architecture ;
- version minimale ;
- version maximale.

---

# Résolution

Lorsqu'une intention nécessite une capacité :

Intent

↓

Capability

↓

Registry

↓

Implementation

↓

Execution Engine

---

# Hot Reload

Le Registry peut :

- ajouter une implémentation ;
- retirer une implémentation ;
- mettre à jour une implémentation.

Sans redémarrer Baygon lorsque cela est possible.

---

# Isolation

Une implémentation ne peut pas accéder directement :

- au Core ;
- aux autres implémentations ;
- aux secrets d'une autre capacité.

Toute communication passe par les interfaces publiques.

---

# Journalisation

Toutes les opérations sont journalisées.

Minimum :

- chargement ;
- activation ;
- désactivation ;
- erreur ;
- sélection.

---

# Règles

Une implémentation fournit une seule capacité principale.

Une implémentation ne dépend jamais d'une autre implémentation.

Une capacité ne dépend jamais d'un fournisseur particulier.

Le Registry est la seule source de vérité concernant les capacités disponibles.

---

# Critères d'acceptation

Le Capability Registry est conforme si :

- une nouvelle implémentation peut être ajoutée sans modifier le Core ;
- plusieurs implémentations peuvent coexister ;
- le remplacement d'une implémentation ne modifie pas les intentions ;
- toutes les implémentations respectent un contrat commun ;
- le Registry reste totalement indépendant des projets.

---

# Règle fondamentale

Le Registry connaît les capacités.

Les capacités connaissent leurs interfaces.

Les implémentations connaissent uniquement leur fournisseur.

Le Core ne connaît que le Registry.
