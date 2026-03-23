#!/usr/bin/env python3
# ============================================================
# RENDER DASHBOARD - Streamlit + Trading Bot
# La dashboard è l'app principale, il bot gira in background
# ============================================================

import os
import sys
import threading
import logging
import subprocess

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_trading_bot():
    """Avvia il trading bot in background."""
    try:
        logger.info("🤖 Avvio Trading Bot in background...")
        from main import run_bot
        import argparse

        args = argparse.Namespace(config='config.yaml', mode=None)
        run_bot(args)

    except Exception as e:
        logger.error(f"Errore bot: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info("🚀 Render Dashboard - Avviamento")

    # Porta di Render
    port = int(os.environ.get('PORT', 8501))
    logger.info(f"📊 Dashboard ascolta su porta: {port}")

    # Avvia Trading Bot in background thread
    bot_thread = threading.Thread(target=run_trading_bot, daemon=True)
    bot_thread.start()
    logger.info("✅ Trading Bot thread avviato")

    # Avvia Streamlit come app principale
    logger.info("📱 Avvio Streamlit Dashboard...")
    os.system(f"streamlit run dashboard/app.py --server.port={port} --server.address=0.0.0.0 --logger.level=warning")
