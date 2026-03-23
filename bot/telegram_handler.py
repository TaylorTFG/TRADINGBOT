# ============================================================
# TELEGRAM HANDLER - COMANDI BOT
# Gestisce i comandi /start, /stop, /status, /logs, ecc.
# ============================================================

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from pathlib import Path
import json
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class TelegramHandler:
    """Gestisce i comandi Telegram per il bot."""

    def __init__(self, bot_token: str, chat_id: str = ""):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.application = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start - Avvia il bot e salva il chat_id."""
        self.chat_id = str(update.effective_chat.id)

        # Salva chat_id nel config
        self._save_chat_id(self.chat_id)

        welcome_msg = (
            "🤖 *Trading Bot Attivo*\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "Comandi disponibili:\n"
            "/status - Stato del bot + performance\n"
            "/logs - Ultimi 20 log\n"
            "/stop - Ferma il bot\n"
            "/restart - Riavvia il bot\n"
            "/config - Mostra configurazione\n"
            "/help - Questo messaggio\n\n"
            "📊 Il bot sta analizzando 20 asset H24"
        )
        await update.message.reply_text(welcome_msg, parse_mode="Markdown")

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /status - Mostra stato del bot."""
        status_file = Path('data/bot_status.json')

        if status_file.exists():
            try:
                with open(status_file, 'r') as f:
                    status_data = json.load(f)

                status_msg = (
                    f"🤖 *Stato Bot*\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"Status: {status_data.get('status_it', 'SCONOSCIUTO')}\n"
                    f"Modalità: {status_data.get('mode', 'paper')}\n"
                    f"Ultimo update: {status_data.get('timestamp', 'N/A')}\n\n"
                    f"📊 Asset monitorati: 20\n"
                    f"💰 Capitale: €500 ($545 USD)\n"
                    f"⏰ Finestra: 15:30-21:45 IT"
                )
                await update.message.reply_text(status_msg, parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ Errore: {e}")
        else:
            await update.message.reply_text("⏳ Bot non ancora avviato")

    async def logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /logs - Mostra ultimi log."""
        log_dir = Path('logs')
        log_files = sorted(log_dir.glob('*.log'), reverse=True)

        if not log_files:
            await update.message.reply_text("📝 Nessun log disponibile")
            return

        try:
            latest_log = log_files[0]
            with open(latest_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-20:]  # Ultimi 20 log

            log_text = "".join(lines[-15:])  # Limita per Telegram
            await update.message.reply_text(
                f"📝 *Ultimi Log*\n```\n{log_text}\n```",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Errore lettura log: {e}")

    async def stop_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /stop - Ferma il bot."""
        await update.message.reply_text(
            "⏹️ *Comando di stop ricevuto*\n"
            "Per fermare il bot:\n"
            "1. Accedi al server Render\n"
            "2. Ferma il servizio\n\n"
            "Il bot si fermerà entro 30 secondi."
        )

    async def restart_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /restart - Riavvia il bot."""
        await update.message.reply_text(
            "🔄 *Riavvio in corso...*\n"
            "Il bot si fermerà e riavvierà entro 1 minuto."
        )

    async def config_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /config - Mostra configurazione."""
        config_msg = (
            "⚙️ *Configurazione Attuale*\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📊 *Portfolio*\n"
            "Asset: 20 (7 ETF + 10 Stock + 3 Crypto)\n"
            "Max per ciclo: 20\n\n"
            "💰 *Trading*\n"
            "Capitale: €500 ($545 USD)\n"
            "Modalità: Paper Trading\n"
            "Stop Loss: -1.5%\n"
            "Take Profit: +3%\n\n"
            "📈 *Strategie*\n"
            "✅ Confluence (5 indicatori)\n"
            "✅ Breakout\n"
            "❌ Sentiment (disabilitata)\n\n"
            "🕐 *Orari*\n"
            "15:30-17:00 / 19:00-21:45 IT"
        )
        await update.message.reply_text(config_msg, parse_mode="Markdown")

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /help - Aiuto."""
        await self.start(update, context)

    def _save_chat_id(self, chat_id: str):
        """Salva il chat_id nel config.yaml."""
        import yaml
        config_path = Path('config.yaml')

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            config['telegram']['chat_id'] = chat_id

            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True)

            logger.info(f"Chat ID salvato: {chat_id}")
        except Exception as e:
            logger.error(f"Errore salvataggio chat_id: {e}")

    def setup_handlers(self, application: Application):
        """Registra i handler dei comandi."""
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("status", self.status))
        application.add_handler(CommandHandler("logs", self.logs))
        application.add_handler(CommandHandler("stop", self.stop_bot))
        application.add_handler(CommandHandler("restart", self.restart_bot))
        application.add_handler(CommandHandler("config", self.config_cmd))
        application.add_handler(CommandHandler("help", self.help_cmd))

        return application


async def start_telegram_bot(bot_token: str):
    """Avvia il bot Telegram."""
    handler = TelegramHandler(bot_token)
    application = Application.builder().token(bot_token).build()

    handler.setup_handlers(application)

    logger.info("🤖 Telegram bot avviato")
    await application.run_polling()
