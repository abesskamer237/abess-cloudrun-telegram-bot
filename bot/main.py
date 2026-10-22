import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("cloudrun-link-deployer")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_IDS = {
    int(x.strip()) for x in os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").split(",")
    if x.strip().isdigit()
}
GCLOUD = os.getenv("GCLOUD_BIN", "gcloud").strip()
DEFAULT_IMAGE = os.getenv(
    "DEFAULT_IMAGE", "docker.io/abess237/abess-ops1:latest"
).strip()
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "europe-west1").strip()
SERVICE_PREFIX = os.getenv("SERVICE_NAME_PREFIX", "abess-run").strip().lower()
PUBLIC_ACCESS = os.getenv("ALLOW_UNAUTHENTICATED", "false").strip().lower() == "true"
DEPLOY_TIMEOUT = int(os.getenv("DEPLOY_TIMEOUT_SECONDS", "900"))

PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,62}$")
REGION_RE = re.compile(r"^[a-z]+-[a-z0-9]+[0-9]$")
SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{0,48}[a-z0-9]$")


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in ALLOWED_IDS)


async def require_allowed(update: Update) -> bool:
    if not is_allowed(update):
        if update.effective_message:
            await update.effective_message.reply_text(
                "⛔ Accès refusé : ton ID Telegram n'est pas autorisé."
            )
        return False
    return True


def extract_project_id(raw: str) -> str | None:
    """Parse a Skills Boost/Cloud Console URL locally; never opens it or uses its token."""
    raw = raw.strip()
    if len(raw) > 6000:
        return None
    try:
        initial = urlparse(raw)
        host = (initial.hostname or "").lower()
        if initial.scheme != "https" or host not in {
            "skills.google", "www.skills.google",
            "cloudskillsboost.google", "www.cloudskillsboost.google",
            "console.cloud.google.com",
        }:
            return None
    except Exception:
        return None

    candidate = raw
    for _ in range(7):
        match = re.search(
            r"(?:[?&]|%3[fF]|%26)project(?:=|%3[dD])([a-z][a-z0-9-]{4,62})(?:[&#%]|$)",
            candidate,
        )
        if match and PROJECT_RE.fullmatch(match.group(1)):
            return match.group(1)
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    return None


async def run_gcloud(args: list[str], timeout: int = 60) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        GCLOUD, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return 124, f"Commande interrompue après {timeout} secondes."
    return proc.returncode or 0, output.decode("utf-8", errors="replace").strip()[-7000:]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_allowed(update):
        return
    await update.effective_message.reply_text(
        "☁️ Cloud Run Link Deployer\n\n"
        "Envoie directement ton lien Google Skills Boost / Cloud Console en un seul message.\n"
        "Si le lien contient un Project ID, le bot vérifie l'accès Google Cloud puis déploie l'image préconfigurée.\n\n"
        f"Image : {DEFAULT_IMAGE}\nRégion : {DEFAULT_REGION}\n"
        f"Accès public : {'activé' if PUBLIC_ACCESS else 'désactivé'}\n\n"
        "/status — vérifier la configuration\n"
        "/cancel — signaler l'annulation d'une opération en attente\n\n"
        "Le bot n'utilise pas le jeton du lien et ne se connecte pas à ta session de navigateur."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_allowed(update):
        return
    code, active_project = await run_gcloud(["config", "get-value", "project"], timeout=30)
    code2, account = await run_gcloud(
        ["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], timeout=30
    )
    await update.effective_message.reply_text(
        f"Image configurée : {DEFAULT_IMAGE}\nRégion : {DEFAULT_REGION}\n"
        f"Accès public : {'oui' if PUBLIC_ACCESS else 'non'}\n"
        f"Projet gcloud actif : {active_project or 'non défini'}\n"
        f"Compte actif : {account or 'aucun'}\n"
        f"Contrôle CLI : {'OK' if code == 0 and code2 == 0 else 'à vérifier'}"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_allowed(update):
        return
    context.user_data["cancel_deploy"] = True
    await update.effective_message.reply_text(
        "Cette commande ne peut pas interrompre une commande gcloud déjà lancée. "
        "Si aucun déploiement n'est en cours, elle sera sans effet."
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_allowed(update):
        return
    text = (update.effective_message.text or "").strip()
    project = extract_project_id(text)
    if not project:
        await update.effective_message.reply_text(
            "Lien non reconnu ou Project ID introuvable.\n"
            "Envoie le lien HTTPS complet provenant de skills.google ou de console.cloud.google.com. "
            "Le bot n'ouvre pas ce lien et ne récupère pas son jeton."
        )
        return
    if not DEFAULT_IMAGE or "REMPLACER_PAR" in DEFAULT_IMAGE:
        await update.effective_message.reply_text("Aucune image Docker valide n'est configurée dans .env.")
        return
    if not REGION_RE.fullmatch(DEFAULT_REGION):
        await update.effective_message.reply_text("DEFAULT_REGION est invalide dans .env.")
        return
    if not SERVICE_RE.fullmatch(SERVICE_PREFIX):
        await update.effective_message.reply_text("SERVICE_NAME_PREFIX est invalide dans .env.")
        return

    timestamp = datetime.now(timezone.utc).strftime("%m%d%H%M%S")
    service = f"{SERVICE_PREFIX}-{timestamp}"[:49].rstrip("-")
    if not SERVICE_RE.fullmatch(service):
        await update.effective_message.reply_text("Impossible de générer un nom de service valide.")
        return

    status_msg = await update.effective_message.reply_text(
        f"🔎 Projet détecté : {project}\n"
        f"📦 Image : {DEFAULT_IMAGE}\n"
        f"🌍 Région : {DEFAULT_REGION}\n"
        f"🛠 Service : {service}\n\n"
        "Étape 1/3 — vérification de l'authentification et de l'accès…"
    )

    # The URL is only parsed for project ID. No browser, cookies, password, or URL token is used.
    code, accounts = await run_gcloud(
        ["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], timeout=30
    )
    if code != 0 or not accounts:
        await status_msg.edit_text(
            "❌ Aucun compte Google Cloud actif sur le VPS.\n"
            "Configure une identité autorisée avec gcloud avant d'utiliser le bot. "
            "Le lien Skills Boost ne transmet pas sa session au VPS."
        )
        return

    code, _ = await run_gcloud(
        ["run", "services", "list", "--project", project, "--region", DEFAULT_REGION,
         "--format=value(metadata.name)"], timeout=60
    )
    if code != 0:
        await status_msg.edit_text(
            f"❌ Le VPS n'a pas pu interroger Cloud Run dans le projet {project}.\n"
            "Le laboratoire peut être expiré, les identifiants peuvent ne pas être autorisés, "
            "ou l'API/les rôles requis peuvent manquer.\n\n"
            "Le bot n'essaiera pas de contourner les restrictions du laboratoire."
        )
        return

    await status_msg.edit_text("🚀 Étape 2/3 — accès confirmé. Déploiement de l'image Docker…")
    args = [
        "run", "deploy", service,
        "--image", DEFAULT_IMAGE,
        "--project", project,
        "--region", DEFAULT_REGION,
        "--platform", "managed",
        "--format", "value(status.url)",
        "--quiet",
    ]
    args.append("--allow-unauthenticated" if PUBLIC_ACCESS else "--no-allow-unauthenticated")
    code, output = await run_gcloud(args, timeout=DEPLOY_TIMEOUT)

    if code != 0:
        await status_msg.edit_text(
            "❌ Échec du déploiement.\n"
            f"Projet : {project}\nImage : {DEFAULT_IMAGE}\n"
            "Causes possibles : droits IAM insuffisants, accès image refusé, API désactivée, "
            "quota/limites du laboratoire, image incompatible ou expiration du lab.\n\n"
            + (output[-2500:] or f"gcloud code {code}")
        )
        return

    url_match = re.search(
        r"https://[a-z0-9-]+-[a-z0-9-]+\.a\.run\.app|https://[a-z0-9-]+\.run\.app",
        output,
    )
    if not url_match:
        code2, detail = await run_gcloud(
            ["run", "services", "describe", service, "--project", project,
             "--region", DEFAULT_REGION, "--format=value(status.url)"], timeout=60
        )
        url = detail.strip().splitlines()[-1] if code2 == 0 and detail.strip() else ""
    else:
        url = url_match.group(0)

    if url.startswith("https://") and ".run.app" in url:
        await status_msg.edit_text(
            "✅ Déploiement terminé.\n\n"
            f"Projet : {project}\nService : {service}\nRégion : {DEFAULT_REGION}\n"
            f"Image : {DEFAULT_IMAGE}\nAccès public : {'oui' if PUBLIC_ACCESS else 'non'}\n\n"
            f"URL Cloud Run : {url}"
        )
    else:
        await status_msg.edit_text(
            "Le déploiement semble terminé, mais l'URL n'a pas pu être récupérée automatiquement.\n"
            f"Service : {service}\nSortie gcloud : {output[-2000:]}"
        )


def main() -> None:
    if not TOKEN:
        raise SystemExit("Configure TELEGRAM_BOT_TOKEN dans .env.")
    if not ALLOWED_IDS:
        raise SystemExit("Configure ALLOWED_TELEGRAM_USER_IDS avec ton ID Telegram numérique.")
    if not DEFAULT_IMAGE or "REMPLACER_PAR" in DEFAULT_IMAGE:
        raise SystemExit("Configure DEFAULT_IMAGE dans .env.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    log.info("Cloud Run Link Deployer démarré.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
