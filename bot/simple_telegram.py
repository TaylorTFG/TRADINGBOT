#!/usr/bin/env python3
# ============================================================
# SIMPLE TELEGRAM HANDLER - HTTP Polling (No AsyncIO)
# Risponde ai comandi /start, /status, /logs, /config
# ============================================================

import requests
import json
import time
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class SimpleTelegramBot:
    """Bot Telegram semplice con HTTP polling."""

    def __init__(self, bot_token: str, chat_id: str = ""):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        self.last_update_id = 0

    def get_updates(self):
        """Ottiene i nuovi messaggi da Telegram."""
        try:
            url = f"{self.api_url}/getUpdates"
            params = {'offset': self.last_update_id + 1, 'timeout': 10}
            response = requests.post(url, json=params, timeout=15)

            if response.status_code == 200:
                updates = response.json().get('result', [])
                return updates
        except Exception as e:
            logger.error(f"Errore getUpdates: {e}")

        return []

    def send_message(self, chat_id: str, text: str):
        """Invia un messaggio Telegram."""
        try:
            url = f"{self.api_url}/sendMessage"
            data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
            response = requests.post(url, json=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Errore sendMessage: {e}")
            return False

    def handle_start(self, chat_id: str):
        """Comando /start"""
        self.chat_id = str(chat_id)
        msg = (
            "🤖 *Trading Bot Attivo*\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "Comandi disponibili:\n"
            "/status - Stato del bot\n"
            "/logs - Ultimi log\n"
            "/config - Configurazione\n"
            "/help - Aiuto\n\n"
            "📊 Sto analizzando 20 asset H24"
        )
        self.send_message(chat_id, msg)
        logger.info(f"✅ Start da {chat_id}")

    def handle_status(self, chat_id: str):
        """Comando /status"""
        try:
            status_file = Path('data/bot_status.json')
            if status_file.exists():
                with open(status_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                vc_file = Path('data/virtual_capital.json')
                capital = "€500"
                if vc_file.exists():
                    with open(vc_file, 'r', encoding='utf-8') as f:
                        vc = json.load(f)
                        capital = f"€{vc.get('capital_eur', 500):.2f}"

                msg = (
                    f"🤖 *Stato Bot*\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"Status: {data.get('status_it', 'SCONOSCIUTO')}\n"
                    f"Modalità: {data.get('mode', 'paper').upper()}\n"
                    f"Capitale: {capital}\n"
                    f"Asset: 20\n"
                    f"⏰ Ultimo update: {data.get('timestamp', 'N/A')}"
                )
                self.send_message(chat_id, msg)
            else:
                self.send_message(chat_id, "⏳ Bot non ancora inizializzato")
        except Exception as e:
            self.send_message(chat_id, f"❌ Errore: {str(e)}")

    def handle_logs(self, chat_id: str):
        """Comando /logs"""
        try:
            log_dir = Path('logs')
            log_files = sorted(log_dir.glob('*.log'), reverse=True)

            if not log_files:
                self.send_message(chat_id, "📝 Nessun log disponibile")
                return

            with open(log_files[0], 'r', encoding='utf-8') as f:
                lines = f.readlines()[-15:]

            log_text = "".join(lines)
            msg = f"📝 *Ultimi Log*\n```\n{log_text}\n```"
            self.send_message(chat_id, msg)
        except Exception as e:
            self.send_message(chat_id, f"❌ Errore: {str(e)}")

    def handle_config(self, chat_id: str):
        """Comando /config"""
        msg = (
            "⚙️ *Configurazione*\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📊 *Portfolio*\n"
            "• 7 ETF (SPY, QQQ, IWM, XLK, XLV, XLF, GLD)\n"
            "• 10 Stock (AAPL, MSFT, NVDA, TSLA, AMZN, GOOGL, META, NFLX, AMD, INTC)\n"
            "• 3 Crypto (BTC/USD, ETH/USD, SOL/USD)\n\n"
            "📈 *Strategie*\n"
            "✅ Confluence (5 indicatori)\n"
            "✅ Breakout (supporti/resistenze)\n"
            "❌ Sentiment (disabilitata)\n\n"
            "🎯 *Risk Management*\n"
            "Stop Loss: -1.5%\n"
            "Take Profit: +3%"
        )
        self.send_message(chat_id, msg)

    def handle_help(self, chat_id: str):
        """Comando /help"""
        self.handle_start(chat_id)

    def process_update(self, update):
        """Elabora un aggiornamento da Telegram."""
        try:
            message = update.get('message', {})
            chat_id = message.get('chat', {}).get('id')
            text = message.get('text', '').strip()

            if not chat_id or not text:
                return

            # Salva l'ultimo update ID
            self.last_update_id = max(self.last_update_id, update.get('update_id', 0))

            # Processa i comandi
            if text.startswith('/start'):
                self.handle_start(chat_id)
            elif text.startswith('/status'):
                self.handle_status(chat_id)
            elif text.startswith('/logs'):
                self.handle_logs(chat_id)
            elif text.startswith('/config'):
                self.handle_config(chat_id)
            elif text.startswith('/help'):
                self.handle_help(chat_id)
            else:
                self.send_message(chat_id, "❓ Comando non riconosciuto.\nDigita /help per l'aiuto.")

        except Exception as e:
            logger.error(f"Errore process_update: {e}")

    def run(self):
        """Loop principale di polling."""
        logger.info("🤖 Simple Telegram Bot avviato (polling)")

        while True:
            try:
                updates = self.get_updates()
                for update in updates:
                    self.process_update(update)

                time.sleep(1)

            except KeyboardInterrupt:
                logger.info("Bot Telegram fermato")
                break
            except Exception as e:
                logger.error(f"Errore main loop: {e}")
                time.sleep(5)


def start_simple_telegram_bot(bot_token: str):
    """Avvia il bot Telegram semplice."""
    if not bot_token or 'YOUR_' in bot_token:
        logger.warning("⚠️ Telegram bot token non configurato")
        return

    bot = SimpleTelegramBot(bot_token)
    bot.run()
