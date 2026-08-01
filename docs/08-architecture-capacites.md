# Chapitre 8 — Architecture par Capacités (Capability Architecture)

## Objectif

Baygon est construit autour des capacités qu'il peut fournir.

Une capacité représente une action ou un service que Baygon peut utiliser.

Une capacité est indépendante de son implémentation.

---

# Définition

Une capacité décrit :

- ce qui peut être fait ;
- jamais comment.

Exemples :

- Repository
- Deployment
- Logs
- Metrics
- Database
- Storage
- Secrets
- SSH
- Workspace
- AI
- Notifications
- Billing

---

# Principe

Une capacité peut être fournie par plusieurs implémentations.

Exemple

Capability

Repository

↓

Implémentations possibles

- GitHub
- GitLab
- Forgejo
- Gitea
- Bitbucket

Baygon ne connaît jamais ces fournisseurs.

Il ne connaît que la capacité Repository.

---

# Exemple

L'utilisateur demande :

Déploie JiyuFit.

Baygon raisonne ainsi :

Intention

↓

Capability : Deployment

↓

Recherche de l'implémentation

↓

Render

↓

Déploiement

Si demain Render est remplacé par Fly.io :

Aucun changement dans Baygon.

---

# Capacités minimales

Repository

Gestion du code source.

---

Deployment

Déploiement d'une application.

---

Workspace

Ouverture d'un environnement de développement.

---

Logs

Consultation des journaux.

---

Metrics

Consultation des métriques.

---

Tracing

Consultation des traces.

---

SSH

Connexion distante.

---

Database

Connexion à une base de données.

---

Secrets

Lecture des secrets.

---

Storage

Gestion des fichiers.

---

AI

Raisonnement.

---

Identity

Authentification.

---

Notification

Envoi de notifications.

---

Backup

Sauvegarde.

---

Recovery

Restauration.

---

Configuration

Lecture des configurations.

---

# Sélection

Une capacité peut posséder plusieurs implémentations.

Baygon sélectionne :

- l'implémentation par défaut ;
- une implémentation demandée ;
- une implémentation de secours.

---

# Exemple

Capability

Metrics

Implémentations :

- Grafana
- Datadog
- Prometheus
- New Relic

Baygon choisit automatiquement celle configurée.

---

# Contrat

Chaque capacité définit une interface.

Toutes les implémentations doivent respecter cette interface.

---

# Découverte

Au démarrage,

Baygon découvre :

- les capacités disponibles ;
- leurs implémentations ;
- leurs versions.

---

# Échec

Si aucune implémentation n'est disponible :

La capacité est marquée comme indisponible.

Le reste du système continue à fonctionner.

---

# Avantages

- Aucun fournisseur codé en dur.

- Changement d'outil sans impact sur le Core.

- Architecture extrêmement découplée.

- Ajout d'une nouvelle implémentation sans modification du noyau.

- Tests simplifiés.

- Maintenance réduite.

---

# Règle fondamentale

Le Core connaît uniquement les capacités.

Il ignore totalement les implémentations.
