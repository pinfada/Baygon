@echo off
rem Baygon — serveur multi-projets, lancé au démarrage de la session.
rem Le jeton d'API est lu dans la variable d'environnement utilisateur
rem BAYGON_API_TOKEN (jamais écrit dans un fichier de configuration).
rem La page web mobile est servie sur / ; l'API sur /health, /plan, /run…
rem
rem Accès depuis le téléphone (même réseau Wi-Fi) :
rem     http://<ip-du-pc>:8787/
rem Depuis l'extérieur, passer par un tunnel (ex. `tailscale up` ou
rem `cloudflared tunnel`) plutôt que d'ouvrir le port sur Internet.
"C:\Users\m_oli\Projets\Baygon\.venv\Scripts\baygon.exe" ^
    --projects "C:\Users\m_oli\Projets" ^
    serve --host 0.0.0.0 --port 8787 --rate-limit 120
