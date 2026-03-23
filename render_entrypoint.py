#!/usr/bin/env python3
# ============================================================
# RENDER ENTRYPOINT
# Avvia il bot + un web server per Render
# La porta è fornita da Render via variabile PORT
# ============================================================

import os
import sys
import threading
import logging
import asyncio
from flask import Flask, jsonify
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import yaml per leggere config
import yaml

# Crea app Flask
app = Flask(__name__)

# Variabili globali
bot_running = False
bot_thread = None


@app.route('/')
def root():
    """Redirect alla dashboard Streamlit."""
    # Redirige a Streamlit sulla porta locale
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trading Bot Dashboard</title>
        <meta http-equiv="refresh" content="0; url=/dashboard/" />
    </head>
    <body>
        <p>Redirecting to dashboard...</p>
    </body>
    </html>
    '''


@app.route('/dashboard/')
def dashboard():
    """Serve la dashboard HTML."""
    try:
        with open('render_dashboard.html', 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return jsonify({'error': 'Dashboard non disponibile', 'details': str(e)}), 500


@app.route('/health')
def health_check():
    """Health check per Render."""
    import json
    status_file = Path('data/bot_status.json')

    if status_file.exists():
        try:
            with open(status_file, 'r') as f:
                status = json.load(f)
                return jsonify({
                    'status': 'running',
                    'bot_status': status.get('status', 'unknown'),
                    'timestamp': status.get('timestamp', 'N/A')
                })
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    return jsonify({'status': 'initializing', 'message': 'Bot starting...'})


@app.route('/api/status')
def api_status():
    """API per lo stato del bot."""
    import json
    status_file = Path('data/bot_status.json')

    try:
        if status_file.exists():
            with open(status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return jsonify({
                    'status': data.get('status', 'unknown'),
                    'status_it': data.get('status_it', 'SCONOSCIUTO'),
                    'mode': data.get('mode', 'paper'),
                    'timestamp': data.get('timestamp', 'N/A')
                })
    except Exception as e:
        logger.error(f"Errore lettura status: {e}")

    return jsonify({'status': 'initializing', 'message': 'Bot starting...'}), 202


@app.route('/api/logs')
def api_logs():
    """API per ultimi log."""
    log_dir = Path('logs')
    log_files = sorted(log_dir.glob('*.log'), reverse=True)

    if not log_files:
        return jsonify({'logs': ['No logs available']}), 404

    try:
        latest_log = log_files[0]
        with open(latest_log, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-30:]  # Ultimi 30 log

        return jsonify({
            'file': latest_log.name,
            'logs': lines,
            'count': len(lines)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/capital')
def api_capital():
    """API per il capitale virtuale."""
    try:
        vc_file = Path('data/virtual_capital.json')
        if vc_file.exists():
            import json
            with open(vc_file, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
    except Exception as e:
        logger.error(f"Errore lettura capitale: {e}")

    return jsonify({'capital_eur': 500, 'capital_usd': 545}), 202


def run_telegram_bot_in_background():
    """Avvia il Telegram bot handler in un thread separato."""
    try:
        logger.info("📱 Avvio Telegram Bot Handler...")

        # Carica il config per ottenere il token
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        bot_token = config.get('telegram', {}).get('bot_token', '')

        if 'YOUR_' in bot_token or not bot_token:
            logger.warning("⚠️ Telegram bot token non configurato, skipping...")
            return

        # Importa e avvia il telegram handler
        from bot.telegram_handler import start_telegram_bot

        # Crea un nuovo event loop per il thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Avvia il telegram bot (blocking call)
        loop.run_until_complete(start_telegram_bot(bot_token))

    except ImportError as e:
        logger.warning(f"⚠️ telegram_handler non disponibile: {e}")
    except Exception as e:
        logger.error(f"Errore Telegram bot: {e}", exc_info=True)


def run_simple_telegram_bot_background():
    """Avvia il Telegram bot semplice in background."""
    try:
        logger.info("📱 Avvio Simple Telegram Bot...")

        # Carica config per ottenere il token
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        bot_token = config.get('telegram', {}).get('bot_token', '')

        if 'YOUR_' in bot_token or not bot_token:
            logger.warning("⚠️ Telegram bot token non configurato")
            return

        from bot.simple_telegram import start_simple_telegram_bot
        start_simple_telegram_bot(bot_token)

    except ImportError:
        logger.warning("⚠️ simple_telegram module not found")
    except Exception as e:
        logger.error(f"Errore Telegram bot: {e}", exc_info=True)


def run_bot_in_background():
    """Avvia il bot in un thread separato."""
    global bot_running

    try:
        logger.info("🤖 Avvio Trading Bot in background...")

        # Importa e avvia il bot
        from main import run_bot
        import argparse

        # Crea args per il bot
        args = argparse.Namespace(
            config='config.yaml',
            mode=None
        )

        # Avvia il bot
        run_bot(args)

    except KeyboardInterrupt:
        logger.info("Bot fermato")
    except Exception as e:
        logger.error(f"Errore bot: {e}", exc_info=True)




if __name__ == "__main__":
    # Porta di Render (default 5000 in locale)
    port = int(os.environ.get('PORT', 5000))

    logger.info(f"🚀 Render Entrypoint - Porta: {port}")

    # Avvia il TRADING BOT in background thread
    bot_thread = threading.Thread(target=run_bot_in_background, daemon=True)
    bot_thread.start()
    logger.info("✅ Trading Bot thread avviato")

    # Avvia il TELEGRAM BOT in background thread
    telegram_thread = threading.Thread(target=run_simple_telegram_bot_background, daemon=True)
    telegram_thread.start()
    logger.info("✅ Telegram Bot thread avviato")

    # Avvia Flask server NEL MAIN THREAD
    logger.info(f"🌐 Web server in ascolto su 0.0.0.0:{port}")

    try:
        app.run(
            host='0.0.0.0',
            port=port,
            debug=False,
            use_reloader=False
        )
    except KeyboardInterrupt:
        logger.info("Server fermato")
