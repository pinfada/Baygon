# Chapitre 5 — Exigences Non Fonctionnelles

## Objectif

Les exigences non fonctionnelles définissent les qualités que Baygon doit garantir indépendamment des fonctionnalités proposées.

---

# ENF-001 — Simplicité

Le cœur de Baygon doit rester volontairement minimaliste.

Toute complexité doit être déléguée aux fournisseurs spécialisés.

---

# ENF-002 — Maintenabilité

Une fonctionnalité ne doit être ajoutée que si son bénéfice est supérieur à son coût de maintenance.

Toute fonctionnalité inutilisée ou redondante doit être supprimée.

---

# ENF-003 — Modularité

Chaque composant doit être indépendant.

Une modification dans un module ne doit pas impacter les autres modules.

---

# ENF-004 — Découplage

Le cœur de Baygon ne dépend d'aucun fournisseur.

Tous les fournisseurs sont accessibles uniquement via des adaptateurs.

---

# ENF-005 — Sécurité

La sécurité est appliquée par défaut.

Tout accès est authentifié.

Toute action est autorisée avant d'être exécutée.

Tous les échanges sensibles sont chiffrés.

---

# ENF-006 — Disponibilité

Baygon doit continuer à fonctionner même si un fournisseur est indisponible.

Les fonctionnalités dépendantes de ce fournisseur doivent être dégradées proprement.

---

# ENF-007 — Portabilité

Le même projet Baygon doit fonctionner sur tout système d'exploitation compatible sans modification.

---

# ENF-008 — Observabilité

Chaque action importante doit être observable.

Minimum :

- début
- fin
- durée
- succès
- échec
- erreur éventuelle

---

# ENF-009 — Auditabilité

Toute action sensible doit laisser une trace consultable.

---

# ENF-010 — Performance

Le démarrage du Shell doit être quasi instantané.

Les traitements lourds doivent être exécutés de manière asynchrone.

---

# ENF-011 — Robustesse

Une erreur provenant d'un fournisseur ne doit jamais provoquer l'arrêt de Baygon.

Les erreurs doivent être isolées.

---

# ENF-012 — Extensibilité

L'ajout :

- d'un fournisseur ;
- d'un projet ;
- d'un modèle IA ;

ne nécessite aucune modification du noyau.

---

# ENF-013 — Évolutivité

Baygon doit pouvoir gérer un nombre croissant de projets sans modification architecturale.

---

# ENF-014 — Compatibilité

Baygon privilégie les standards ouverts.

Les API publiques sont préférées aux mécanismes propriétaires.

---

# ENF-015 — Documentation

Toute fonctionnalité est documentée avant son implémentation.

La documentation fait partie intégrante du produit.

---

# ENF-016 — Tests

Toute fonctionnalité critique doit être testable automatiquement.

---

# ENF-017 — Résilience

Une interruption réseau ne doit jamais entraîner la perte d'informations côté utilisateur.

Les opérations longues doivent pouvoir être reprises.

---

# ENF-018 — Expérience utilisateur

L'utilisateur ne doit jamais avoir besoin de connaître :

- le fournisseur utilisé ;
- l'API appelée ;
- la commande technique exécutée.

Il exprime uniquement son intention.

---

# ENF-019 — Neutralité technologique

Baygon ne favorise aucun :

- fournisseur cloud ;
- fournisseur Git ;
- fournisseur IA ;
- hébergeur.

Tous sont interchangeables.

---

# ENF-020 — Durabilité

Chaque décision technique doit pouvoir rester pertinente pendant plusieurs années.

Les technologies choisies doivent privilégier :

- la stabilité ;
- la simplicité ;
- la pérennité.

---

# Indicateurs de qualité

Baygon est considéré conforme si :

- le remplacement d'un fournisseur nécessite uniquement un nouvel adaptateur ;
- le noyau reste indépendant des fournisseurs ;
- la maintenance mensuelle reste faible ;
- la documentation reste synchronisée avec l'implémentation ;
- l'utilisateur peut travailler efficacement depuis n'importe quel appareil.
