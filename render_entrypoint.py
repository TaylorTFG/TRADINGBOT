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
from flask import Flask, jsonify
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crea app Flask
app = Flask(__name__)

# Variabili globali
bot_running = False
bot_thread = None


@app.route('/')
def health_check():
    """Health check per Render."""
    status_file = Path('data/bot_status.json')

    if status_file.exists():
        import json
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
    status_file = Path('data/bot_status.json')

    if status_file.exists():
        import json
        try:
            with open(status_file, 'r') as f:
                return jsonify(json.load(f))
        except Exception:
            pass

    return jsonify({'status': 'unknown'}), 503


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


def start_bot():
    """Avvia il bot in un thread daemon."""
    global bot_thread, bot_running

    if not bot_running:
        bot_thread = threading.Thread(target=run_bot_in_background, daemon=True)
        bot_thread.start()
        bot_running = True
        logger.info("✅ Bot thread avviato")


if __name__ == "__main__":
    # Porta di Render (default 5000 in locale)
    port = int(os.environ.get('PORT', 5000))

    logger.info(f"🚀 Render Entrypoint - Porta: {port}")

    # Avvia il bot in background
    start_bot()

    # Avvia Flask server
    logger.info(f"🌐 Web server in ascolto su 0.0.0.0:{port}")
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        use_reloader=False
    )
