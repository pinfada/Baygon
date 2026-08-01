# Chapitre 11 — Déploiement en production

## Objectif

Exposer le Shell Baygon (API + page web) sur Internet de façon sûre,
pour qu'un développeur puisse travailler depuis n'importe quel appareil
avec sa seule identité.

Baygon ne gère pas TLS lui-même : conformément à l'Article 3, la
terminaison TLS est déléguée à un reverse proxy spécialisé.

---

## Architecture recommandée

```
Téléphone / tablette / ordinateur
        │  HTTPS (TLS)
        ▼
Reverse proxy (Caddy, Nginx, ...)
        │  HTTP local (127.0.0.1)
        ▼
baygon serve  (systemd)
```

Le serveur Baygon n'écoute que sur `127.0.0.1` (défaut) ; seul le proxy
est exposé.

---

## 1. Le jeton d'API

Le serveur refuse de démarrer sans jeton (sécurité par défaut).

Générer un jeton fort et le fournir via l'environnement — jamais dans
`baygon.yaml` :

```console
$ openssl rand -hex 32
```

Le jeton peut aussi venir du gestionnaire de secrets (secret
`API_TOKEN` de la capacité `secrets`).

---

## 2. Unité systemd

`/etc/systemd/system/baygon.service` :

```ini
[Unit]
Description=Baygon Shell (API + web)
After=network.target

[Service]
User=baygon
WorkingDirectory=/srv/monprojet
Environment=BAYGON_API_TOKEN=<jeton>
# ou : EnvironmentFile=/etc/baygon/env  (fichier root:root 0600)
ExecStart=/usr/bin/env baygon serve --host 127.0.0.1 --port 8787 --rate-limit 120
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/srv/monprojet/.baygon

[Install]
WantedBy=multi-user.target
```

```console
$ systemctl enable --now baygon
```

---

## 3. Reverse proxy TLS

### Caddy (certificats automatiques)

`/etc/caddy/Caddyfile` :

```
baygon.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

### Nginx

```nginx
server {
    listen 443 ssl;
    server_name baygon.example.com;
    ssl_certificate     /etc/letsencrypt/live/baygon.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/baygon.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

---

## 4. Vérifications

```console
$ curl https://baygon.example.com/health
{"status": "ok", ...}

$ curl https://baygon.example.com/capabilities
{"error": "authentication required: ..."}        # 401 sans jeton — attendu

$ curl -H "Authorization: Bearer <jeton>" https://baygon.example.com/capabilities
{...}                                            # 200 avec jeton
```

Depuis un téléphone : ouvrir `https://baygon.example.com/`, saisir le
jeton, exprimer une intention.

---

## 5. Protections actives

- **Authentification** : `Authorization: Bearer` requis partout sauf
  `/health` et la page statique ; comparaison en temps constant.
- **Limitation de débit** : 120 req/min par client par défaut
  (`--rate-limit`), `429` + `Retry-After` au-delà, `/health` exempté.
- **En-têtes** : `nosniff`, `no-store`, `X-Frame-Options: DENY`.
- **Audit** : chaque échec d'authentification publie un événement
  `AuthFailed` ; chaque intention exécutée est journalisée dans
  `.baygon/history.jsonl`.
- **Rechargement à chaud** : `POST /reload` (authentifié) applique une
  nouvelle configuration sans coupure.

---

## Règles

Le jeton n'est jamais dans la configuration.

Baygon n'écoute jamais directement sur Internet.

TLS appartient au proxy.

Les secrets appartiennent au gestionnaire de secrets.
