# Chapitre 2 — Constitution de Baygon

## Préambule

La Constitution de Baygon définit les principes immuables du projet.

Toute décision d'architecture, d'implémentation ou d'évolution doit respecter cette Constitution.

En cas de conflit entre une fonctionnalité et la Constitution, la Constitution prévaut.

---

# Article 1 — Raison d'être

Baygon existe pour supprimer la dépendance à un poste de travail et offrir une interface unique permettant de développer, exploiter et administrer un écosystème logiciel depuis n'importe quel appareil.

---

# Article 2 — Principe de simplicité

La simplicité est prioritaire sur la richesse fonctionnelle.

Une fonctionnalité inutile ou rarement utilisée ne doit pas être implémentée.

Chaque nouvelle fonctionnalité doit démontrer un bénéfice concret.

---

# Article 3 — Principe d'orchestration

Baygon n'a pas vocation à remplacer les outils spécialisés.

Baygon orchestre des services existants au travers d'une interface unifiée.

---

# Article 4 — Principe de découplage

Aucun fournisseur ne doit être indispensable.

Tout composant externe doit pouvoir être remplacé avec un impact minimal.

Les intégrations doivent être réalisées au travers d'adaptateurs.

---

# Article 5 — Principe d'intelligence

L'utilisateur exprime une intention.

Baygon décide des outils à utiliser pour satisfaire cette intention.

Le langage naturel constitue l'interface principale.

Les commandes traditionnelles restent disponibles.

---

# Article 6 — Principe de mobilité

Toutes les fonctionnalités critiques doivent être accessibles depuis :

- un ordinateur ;
- une tablette ;
- un téléphone.

Aucun workflow ne doit imposer un appareil particulier.

---

# Article 7 — Principe de sécurité

La sécurité est présente par défaut.

Les secrets ne sont jamais stockés en clair.

Le moindre privilège est appliqué à chaque action.

Toute opération sensible est traçable.

---

# Article 8 — Principe de transparence

Chaque action exécutée par Baygon doit pouvoir être expliquée.

L'utilisateur doit connaître :

- les outils utilisés ;
- les ressources consultées ;
- les actions exécutées ;
- les conséquences.

---

# Article 9 — Principe de responsabilité

Baygon propose.

L'utilisateur décide.

Aucune action destructive n'est exécutée sans validation explicite.

---

# Article 10 — Principe de maintenance

Le coût de maintenance doit rester inférieur au bénéfice apporté.

Une fonctionnalité difficile à maintenir doit être supprimée ou simplifiée.

---

# Article 11 — Principe de documentation

Toute décision d'architecture importante est documentée.

La documentation constitue la référence officielle du projet.

Le code implémente la documentation.

Jamais l'inverse.

---

# Article 12 — Principe de pérennité

Baygon doit rester utilisable indépendamment :

- du fournisseur cloud ;
- du fournisseur Git ;
- du modèle d'IA ;
- du système d'exploitation.

---

# Article 13 — Principe de minimalisme

Le cœur de Baygon doit rester volontairement limité.

Toute fonctionnalité qui peut être déléguée à un service existant doit l'être.

---

# Article 14 — Principe d'évolutivité

Baygon est conçu pour accompagner plusieurs projets.

L'ajout d'un nouveau projet ne doit nécessiter aucune modification du cœur du système.

---

# Article 15 — Principe de qualité

Une fonctionnalité est considérée terminée uniquement lorsqu'elle est :

- documentée ;
- testée ;
- observable ;
- sécurisée ;
- maintenable.

---

# Les interdictions

Baygon ne devra jamais :

- remplacer Git ;
- remplacer GitHub ;
- remplacer Docker ;
- remplacer Render ;
- remplacer Grafana ;
- remplacer PostgreSQL ;
- remplacer Redis ;
- remplacer un fournisseur d'IA.

Baygon ne devra jamais :

- imposer un cloud ;
- imposer une interface graphique ;
- imposer un modèle d'IA ;
- imposer un système d'exploitation.

Baygon ne devra jamais contenir de logique métier spécifique à un projet.

---

# Devise

Une intention.

Une réponse.

Depuis n'importe où.
