# ============================================================
# NOTIFICHE TELEGRAM - TRADING BOT
# Invia alerts e report in tempo reale via Telegram
# ============================================================

import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class TelegramNotifier:
    """
    Gestisce l'invio di notifiche via Telegram.
    Invia alerts per trade, stop loss, report giornalieri e settimanali.
    """

    def __init__(self, config: dict):
        """
        Inizializza il notificatore Telegram.

        Args:
            config: Configurazione completa dal config.yaml
        """
        self.config = config
        self.telegram_config = config.get('telegram', {})
        self.enabled = self.telegram_config.get('enabled', False)
        self.bot_token = self.telegram_config.get('bot_token', '')
        self.chat_id = self.telegram_config.get('chat_id', '')
        self.notifications = self.telegram_config.get('notifications', {})
        self._bot = None

        if self.enabled and self.bot_token and self.bot_token != 'YOUR_TELEGRAM_BOT_TOKEN':
            self._init_bot()
        else:
            if self.enabled:
                logger.warning("Telegram abilitato ma token non configurato. Notifiche disabilitate.")
            self.enabled = False

    def _init_bot(self):
        """Inizializza il bot Telegram."""
        try:
            from telegram import Bot
            self._bot = Bot(token=self.bot_token)
            logger.info("Bot Telegram inizializzato")
        except ImportError:
            logger.warning("python-telegram-bot non installato. Notifiche Telegram disabilitate.")
            self.enabled = False
        except Exception as e:
            logger.error(f"Errore inizializzazione Telegram: {e}")
            self.enabled = False

    def _send_message(self, message: str) -> bool:
        """
        Invia un messaggio Telegram in modo sincrono.

        Args:
            message: Testo del messaggio (supporta Markdown)

        Returns:
            True se il messaggio è stato inviato con successo
        """
        if not self.enabled or not self._bot:
            logger.debug(f"[TELEGRAM SIMULATO] {message[:100]}...")
            return True

        try:
            # Usa asyncio per inviare il messaggio in modo sincrono
            async def _send():
                await self._bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode='Markdown'
                )

            # Esegui in modo sincrono
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Se c'è già un loop in esecuzione, usa run_coroutine_threadsafe
                    import concurrent.futures
                    future = asyncio.run_coroutine_threadsafe(_send(), loop)
                    future.result(timeout=10)
                else:
                    loop.run_until_complete(_send())
            except RuntimeError:
                asyncio.run(_send())

            logger.debug(f"Notifica Telegram inviata: {message[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Errore invio Telegram: {e}")
            return False

    # ----------------------------------------------------------------
    # NOTIFICHE TRADE
    # ----------------------------------------------------------------

    def notify_trade_open(self, trade_data: Dict) -> bool:
        """
        Notifica apertura di un nuovo trade.

        Args:
            trade_data: Dati del trade aperto
        """
        if not self.notifications.get('trade_open', True):
            return True

        symbol = trade_data.get('symbol', 'N/A')
        side = trade_data.get('side', 'N/A').upper()
        price = trade_data.get('entry_price', 0)
        qty = trade_data.get('quantity', 0)
        strategy = trade_data.get('strategy', 'N/A')
        stop_loss = trade_data.get('stop_loss', 0)
        take_profit = trade_data.get('take_profit', 0)
        vote_score = trade_data.get('vote_score', 0)

        # Emoji in base alla direzione
        emoji = "🟢" if side == "BUY" else "🔴"
        side_it = "ACQUISTO" if side == "BUY" else "VENDITA"

        message = (
            f"{emoji} *TRADE APERTO*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📊 Asset: `{symbol}`\n"
            f"📈 Direzione: *{side_it}*\n"
            f"💰 Prezzo entrata: `${price:.2f}`\n"
            f"📦 Quantità: `{qty}`\n"
            f"🎯 Strategia: `{strategy}`\n"
            f"🗳️ Voti: `{vote_score}/3`\n"
            f"🛑 Stop Loss: `${stop_loss:.2f}`\n"
            f"✅ Take Profit: `${take_profit:.2f}`\n"
            f"⏰ Ora: `{datetime.now(IT_TZ).strftime('%H:%M:%S')}`"
        )

        return self._send_message(message)

    def notify_trade_close(self, trade_data: Dict, exit_reason: str) -> bool:
        """
        Notifica chiusura di un trade con risultato.

        Args:
            trade_data: Dati del trade chiuso
            exit_reason: Motivo della chiusura
        """
        if not self.notifications.get('trade_close', True):
            return True

        symbol = trade_data.get('symbol', 'N/A')
        pnl = trade_data.get('pnl', 0)
        pnl_pct = trade_data.get('pnl_pct', 0) * 100
        entry_price = trade_data.get('entry_price', 0)
        exit_price = trade_data.get('exit_price', 0)
        strategy = trade_data.get('strategy', 'N/A')

        # Emoji in base al risultato
        if pnl > 0:
            emoji = "✅"
            result_emoji = "💚"
        else:
            emoji = "❌"
            result_emoji = "🔴"

        message = (
            f"{emoji} *TRADE CHIUSO*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📊 Asset: `{symbol}`\n"
            f"🎯 Strategia: `{strategy}`\n"
            f"📥 Entrata: `${entry_price:.2f}`\n"
            f"📤 Uscita: `${exit_price:.2f}`\n"
            f"📋 Motivo: `{exit_reason}`\n"
            f"{result_emoji} *P&L: {'+' if pnl >= 0 else ''}{pnl:.2f}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%)*\n"
            f"⏰ Ora: `{datetime.now(IT_TZ).strftime('%H:%M:%S')}`"
        )

        return self._send_message(message)

    def notify_stop_loss(self, symbol: str, price: float, pnl: float) -> bool:
        """Alert immediato per stop loss scattato."""
        if not self.notifications.get('stop_loss_hit', True):
            return True

        message = (
            f"🚨 *STOP LOSS SCATTATO*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📊 Asset: `{symbol}`\n"
            f"💰 Prezzo: `${price:.2f}`\n"
            f"🔴 Perdita: `{pnl:.2f}$`\n"
            f"⏰ Ora: `{datetime.now(IT_TZ).strftime('%H:%M:%S')}`\n"
            f"⚠️ _Monitorare la situazione_"
        )

        return self._send_message(message)

    # ----------------------------------------------------------------
    # ALERT DI SISTEMA
    # ----------------------------------------------------------------

    def notify_daily_drawdown(self, current_loss_pct: float, capital: float) -> bool:
        """Alert per raggiungimento drawdown giornaliero massimo."""
        if not self.notifications.get('daily_drawdown', True):
            return True

        message = (
            f"🚨 *DRAWDOWN GIORNALIERO RAGGIUNTO*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📉 Perdita: `{current_loss_pct:.2f}%`\n"
            f"💰 Capitale: `${capital:.2f}`\n"
            f"🤖 *BOT FERMATO AUTOMATICAMENTE*\n"
            f"⏰ Ora: `{datetime.now(IT_TZ).strftime('%H:%M:%S')}`\n"
            f"ℹ️ _Il bot riprenderà domani_"
        )

        return self._send_message(message)

    def notify_bot_status(self, status: str, reason: str = "") -> bool:
        """Notifica cambio di stato del bot."""
        status_map = {
            'started': ('🟢', 'AVVIATO'),
            'stopped': ('🔴', 'FERMATO'),
            'paused': ('🟡', 'IN PAUSA'),
            'error': ('❌', 'ERRORE'),
        }
        emoji, status_it = status_map.get(status, ('ℹ️', status.upper()))

        message = (
            f"{emoji} *BOT {status_it}*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🕐 Ora: `{datetime.now(IT_TZ).strftime('%d/%m/%Y %H:%M:%S')}`"
        )

        if reason:
            message += f"\n📝 Motivo: _{reason}_"

        return self._send_message(message)

    def notify_live_trading_ready(self, days_profitable: int) -> bool:
        """Suggerisce il passaggio al live trading dopo N giorni profittevoli."""
        message = (
            f"🎉 *PAPER TRADING PRONTO PER LIVE!*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ Il bot ha completato *{days_profitable} giorni profittevoli* in paper trading!\n\n"
            f"📊 Considera il passaggio al live trading:\n"
            f"1. Verifica le performance nella dashboard\n"
            f"2. Valuta il rischio con denaro reale\n"
            f"3. Usa il pannello Configurazione per attivare il live\n\n"
            f"⚠️ _Ricorda: il trading comporta rischi di perdita del capitale_"
        )

        return self._send_message(message)

    # ----------------------------------------------------------------
    # REPORT
    # ----------------------------------------------------------------

    def send_daily_report(self, stats: Dict) -> bool:
        """
        Invia il report giornaliero con statistiche complete.

        Args:
            stats: Dizionario con le statistiche del giorno
        """
        if not self.notifications.get('daily_report', True):
            return True

        today = datetime.now(IT_TZ).strftime('%d/%m/%Y')
        pnl = stats.get('total_pnl', 0)
        pnl_pct = stats.get('pnl_pct', 0) * 100
        trades = stats.get('trades_count', 0)
        winning = stats.get('winning_trades', 0)
        losing = stats.get('losing_trades', 0)
        capital = stats.get('ending_capital', 0)

        win_rate = (winning / trades * 100) if trades > 0 else 0
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        result_emoji = "✅" if pnl >= 0 else "❌"

        message = (
            f"📊 *REPORT GIORNALIERO - {today}*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"{pnl_emoji} P&L: *{'+' if pnl >= 0 else ''}{pnl:.2f}$ ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%)*\n"
            f"💼 Capitale: `${capital:.2f}`\n"
            f"📈 Trade eseguiti: `{trades}`\n"
            f"✅ Vincenti: `{winning}`\n"
            f"❌ Perdenti: `{losing}`\n"
            f"🎯 Win Rate: `{win_rate:.1f}%`\n"
        )

        if stats.get('best_trade'):
            message += f"🏆 Miglior trade: `+{stats['best_trade']:.2f}$`\n"
        if stats.get('worst_trade'):
            message += f"💔 Peggior trade: `{stats['worst_trade']:.2f}$`\n"

        message += f"\n{result_emoji} _Resoconto ore {datetime.now(IT_TZ).strftime('%H:%M')}_"

        return self._send_message(message)

    def send_weekly_report(self, stats: Dict) -> bool:
        """
        Invia il report settimanale ogni venerdì sera.

        Args:
            stats: Dizionario con le statistiche della settimana
        """
        if not self.notifications.get('weekly_report', True):
            return True

        week = datetime.now(IT_TZ).strftime('%d/%m/%Y')
        pnl = stats.get('total_pnl', 0)
        pnl_pct = stats.get('pnl_pct', 0) * 100
        trades = stats.get('total_trades', 0)
        win_rate = stats.get('win_rate', 0) * 100
        sharpe = stats.get('sharpe_ratio', 0)
        capital = stats.get('ending_capital', 0)
        best_strategy = stats.get('best_strategy', 'N/A')

        pnl_emoji = "🚀" if pnl > 0 else "📉"

        message = (
            f"📅 *REPORT SETTIMANALE - {week}*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"{pnl_emoji} *Performance settimana:*\n"
            f"💰 P&L Totale: `{'+' if pnl >= 0 else ''}{pnl:.2f}$ ({pnl_pct:+.2f}%)`\n"
            f"💼 Capitale Finale: `${capital:.2f}`\n\n"
            f"📊 *Statistiche:*\n"
            f"📈 Trade Totali: `{trades}`\n"
            f"🎯 Win Rate: `{win_rate:.1f}%`\n"
            f"📐 Sharpe Ratio: `{sharpe:.2f}`\n"
            f"🏆 Strategia Migliore: `{best_strategy}`\n"
        )

        if stats.get('paused_next_week'):
            message += f"\n⚠️ *PAUSA AUTOMATICA ATTIVA*\nIl bot riprenderà tra 2 giorni per perdite eccessive"

        message += f"\n\n_Prossima sessione: lunedì_"

        return self._send_message(message)
