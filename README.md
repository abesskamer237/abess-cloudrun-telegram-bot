# Cloud Run Telegram Deployer — Skills Boost

Bot Telegram qui attend un lien Google Skills Boost / Cloud Console, extrait le Project ID, vérifie l'accès Google Cloud du VPS, déploie une image Docker et renvoie l'URL `run.app`.

- Image Docker par défaut : `docker.io/abess237/abess-ops1:latest`
- Région par défaut : `europe-west1`
- Installation interactive : `sudo bash install.sh`
- Commandes Telegram : `/start`, `/status`, `/cancel`

## Installation

Sur un VPS Ubuntu, exécute :

```bash
git clone https://github.com/abesskamer237/abess-cloudrun-telegram-bot.git
cd abess-cloudrun-telegram-bot
sudo bash install.sh
```

L'installateur demande l'ID Telegram autorisé, le token Telegram, l'image Docker, la région et si le service doit être public. Il installe les dépendances, crée un service systemd et démarre le bot. Le bot reste ensuite en attente d'un lien envoyé en message Telegram.

## Authentification Google Cloud obligatoire

Le bot analyse le lien localement ; il n'ouvre pas le navigateur et n'utilise pas le paramètre `token`, les cookies ou une session Google. L'ID Telegram et le token du bot ne donnent pas accès à Google Cloud. Pour déployer, le VPS doit avoir une identité `gcloud` déjà authentifiée et autorisée à utiliser Cloud Run et l'image Docker. Les identifiants de laboratoire peuvent expirer ou avoir des restrictions de quota/permissions.

Pour vérifier l'authentification, utilise `gcloud auth list` sous le même compte système que le service. Un flux interactif peut être lancé avec `gcloud auth login --no-launch-browser`, mais il ne garantit pas que les comptes temporaires Skills Boost soient compatibles.

Par défaut, le service Cloud Run est privé. L'option publique expose le service sans authentification Google : ne l'active que si c'est voulu et sûr.

## Contrôle et journaux

```bash
sudo systemctl status cloudrun-telegram-bot
sudo journalctl -u cloudrun-telegram-bot -f
```

## Limites

Le bot ne contourne pas les restrictions des laboratoires et ne réutilise pas les sessions Google du lien. Un déploiement peut échouer si le projet est expiré, si les APIs ou rôles IAM manquent, si l'image n'est pas accessible ou si les quotas sont épuisés.
