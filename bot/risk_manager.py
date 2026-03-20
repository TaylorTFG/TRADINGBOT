# ============================================================
# RISK MANAGER - GESTIONE DEL RISCHIO
# Calcola position sizing, stop loss, trailing stop,
# e monitora i limiti giornalieri/settimanali
# ============================================================

import logging
from datetime import datetime, date
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class RiskManager:
    """
    Gestisce tutto il rischio del bot:
    - Position sizing basato su ATR e capitale
    - Stop loss iniziale e trailing stop
    - Limiti giornalieri (max loss, target profit)
    - Limiti settimanali (max loss → pausa automatica)
    - Monitoraggio posizioni aperte
    """

    def __init__(self, config: dict, database):
        """
        Inizializza il Risk Manager.

        Args:
            config: Configurazione dal config.yaml
            database: Istanza del DatabaseManager
        """
        self.config = config
        self.db = database
        self.risk_config = config.get('risk_management', {})

        # Parametri di rischio
        self.max_risk_per_trade = self.risk_config.get('max_risk_per_trade', 0.02)
        self.stop_loss_pct = self.risk_config.get('stop_loss_pct', 0.015)
        self.take_profit_pct = self.risk_config.get('take_profit_pct', 0.03)
        self.max_open_positions = config.get('trading', {}).get('max_open_positions', 6)

        # Trailing stop
        trailing = self.risk_config.get('trailing_stop', {})
        self.trailing_enabled = trailing.get('enabled', True)
        self.trailing_activation = trailing.get('activation_pct', 0.01)
        self.trailing_distance = trailing.get('trail_pct', 0.008)

        # Limiti giornalieri
        daily = self.risk_config.get('daily', {})
        self.max_daily_loss = daily.get('max_loss_pct', 0.05)
        self.daily_profit_target = daily.get('target_profit_pct', 0.03)

        # Limiti settimanali
        weekly = self.risk_config.get('weekly', {})
        self.max_weekly_loss = weekly.get('max_loss_pct', 0.10)
        self.pause_days = weekly.get('pause_days', 2)

        # Sizing
        sizing = self.risk_config.get('sizing', {})
        self.full_agreement_pct = sizing.get('full_agreement_pct', 0.02)
        self.partial_agreement_pct = sizing.get('partial_agreement_pct', 0.01)

        # Stato interno
        self._paused_until: Optional[datetime] = None
        self._daily_starting_capital: Optional[float] = None
        self._weekly_starting_capital: Optional[float] = None
        self._today_reduced_size = False

        logger.info("Risk Manager inizializzato")

    # ----------------------------------------------------------------
    # POSITION SIZING
    # ----------------------------------------------------------------

    def calculate_position_size(
        self,
        capital: float,
        price: float,
        atr: Optional[float],
        vote_score: int,
        macro_multiplier: float = 1.0
    ) -> Dict:
        """
        Calcola la dimensione della posizione in base al rischio.

        Usa due metodi:
        1. Percentuale fissa del capitale basata sui voti
        2. ATR-based sizing per rispettare il rischio massimo per trade

        Args:
            capital: Capitale totale disponibile
            price: Prezzo corrente dell'asset
            atr: Average True Range (per sizing basato su volatilità)
            vote_score: Numero di voti concordi (2 o 3)
            macro_multiplier: Moltiplicatore macro contesto (0.5-1.0)

        Returns:
            Dizionario con qty, capital_at_risk, stop_loss, take_profit
        """
        # Seleziona percentuale base in base ai voti
        if vote_score >= 3:
            base_pct = self.full_agreement_pct
        else:
            base_pct = self.partial_agreement_pct

        # Applica moltiplicatore macro (es. VIX alto = size ridotta)
        effective_pct = base_pct * macro_multiplier

        # Riduci size se siamo a target profitto giornaliero
        if self._today_reduced_size:
            effective_pct *= 0.5
            logger.debug("Size ridotta al 50% per target giornaliero raggiunto")

        # Calcolo capitale da rischiare
        capital_at_risk = capital * effective_pct

        # Metodo 1: sizing basato su percentuale
        qty_pct = capital_at_risk / price

        # Metodo 2: sizing basato su ATR (se disponibile)
        if atr and atr > 0:
            # Risk = stop_distance = ATR * moltiplicatore
            stop_distance = atr * 1.5
            max_risk_dollars = capital * self.max_risk_per_trade
            qty_atr = max_risk_dollars / stop_distance
            # Usa il minore tra i due metodi per essere conservativi
            qty = min(qty_pct, qty_atr)
        else:
            qty = qty_pct

        # Arrotonda a 6 decimali (per crypto frazioni)
        qty = round(qty, 6)

        # Assicura almeno 1 unità (o frazione minima per crypto)
        if qty < 0.000001:
            qty = 0

        # Calcola stop loss e take profit
        stop_loss = price * (1 - self.stop_loss_pct)
        take_profit = price * (1 + self.take_profit_pct)

        result = {
            'qty': qty,
            'capital_at_risk': qty * price,
            'stop_loss': round(stop_loss, 4),
            'take_profit': round(take_profit, 4),
            'effective_pct': effective_pct,
            'method': 'atr' if (atr and atr > 0) else 'percentage'
        }

        logger.debug(f"Position sizing: qty={qty:.4f}, risk=${qty * price:.2f}, SL={stop_loss:.2f}, TP={take_profit:.2f}")
        return result

    # ----------------------------------------------------------------
    # STOP LOSS E TRAILING STOP
    # ----------------------------------------------------------------

    def update_trailing_stop(self, trade: Dict, current_price: float) -> Optional[float]:
        """
        Aggiorna il trailing stop se le condizioni sono soddisfatte.

        Il trailing stop si attiva quando il profitto raggiunge
        la soglia di attivazione e poi segue il prezzo.

        Args:
            trade: Dati del trade (entry_price, stop_loss, side, ecc.)
            current_price: Prezzo corrente dell'asset

        Returns:
            Nuovo prezzo dello stop loss o None se non cambiato
        """
        if not self.trailing_enabled:
            return None

        entry_price = trade['entry_price']
        current_stop = trade.get('stop_loss', 0)
        side = trade.get('side', 'buy')

        if side == 'buy':
            # Calcola profitto corrente
            profit_pct = (current_price - entry_price) / entry_price

            # Lo trailing si attiva solo dopo la soglia di attivazione
            if profit_pct < self.trailing_activation:
                return None

            # Calcola nuovo stop (prezzo - distanza trailing)
            new_stop = current_price * (1 - self.trailing_distance)

            # Lo stop si muove solo in avanti (mai indietro)
            if new_stop > current_stop:
                logger.debug(f"Trailing stop aggiornato: {current_stop:.2f} → {new_stop:.2f}")
                return round(new_stop, 4)

        else:  # sell/short
            profit_pct = (entry_price - current_price) / entry_price

            if profit_pct < self.trailing_activation:
                return None

            new_stop = current_price * (1 + self.trailing_distance)

            if new_stop < current_stop or current_stop == 0:
                return round(new_stop, 4)

        return None

    def should_stop_loss(self, trade: Dict, current_price: float) -> bool:
        """
        Verifica se lo stop loss è stato raggiunto.

        Args:
            trade: Dati del trade
            current_price: Prezzo corrente

        Returns:
            True se lo stop loss è stato colpito
        """
        stop_loss = trade.get('stop_loss', 0)
        side = trade.get('side', 'buy')

        if side == 'buy':
            return current_price <= stop_loss and stop_loss > 0
        else:
            return current_price >= stop_loss and stop_loss > 0

    def should_take_profit(self, trade: Dict, current_price: float) -> bool:
        """
        Verifica se il take profit è stato raggiunto.

        Args:
            trade: Dati del trade
            current_price: Prezzo corrente

        Returns:
            True se il take profit è stato raggiunto
        """
        take_profit = trade.get('take_profit', 0)
        side = trade.get('side', 'buy')

        if side == 'buy':
            return current_price >= take_profit and take_profit > 0
        else:
            return current_price <= take_profit and take_profit > 0

    # ----------------------------------------------------------------
    # LIMITI GIORNALIERI
    # ----------------------------------------------------------------

    def check_daily_limits(self, current_capital: float, starting_capital: float) -> Dict:
        """
        Controlla i limiti giornalieri di perdita e profitto.

        Args:
            current_capital: Capitale attuale
            starting_capital: Capitale all'inizio della giornata

        Returns:
            Dizionario con can_trade, should_reduce_size, reason
        """
        if starting_capital <= 0:
            return {'can_trade': True, 'should_reduce_size': False, 'reason': ''}

        daily_change = (current_capital - starting_capital) / starting_capital

        # Limite perdita giornaliera
        if daily_change <= -self.max_daily_loss:
            logger.warning(f"Perdita giornaliera massima raggiunta: {daily_change:.2%}")
            return {
                'can_trade': False,
                'should_reduce_size': False,
                'reason': f'Perdita giornaliera {daily_change:.2%} supera limite {self.max_daily_loss:.2%}',
                'daily_pnl_pct': daily_change
            }

        # Target profitto giornaliero → riduci size
        if daily_change >= self.daily_profit_target:
            self._today_reduced_size = True
            logger.info(f"Target profitto giornaliero raggiunto: {daily_change:.2%}. Size ridotta al 50%")
            return {
                'can_trade': True,
                'should_reduce_size': True,
                'reason': f'Target giornaliero {daily_change:.2%} raggiunto. Size al 50%',
                'daily_pnl_pct': daily_change
            }

        return {
            'can_trade': True,
            'should_reduce_size': False,
            'reason': '',
            'daily_pnl_pct': daily_change
        }

    def reset_daily_state(self):
        """Resetta lo stato giornaliero (chiamato ogni mattina)."""
        self._today_reduced_size = False
        logger.info("Stato giornaliero Risk Manager resettato")

    # ----------------------------------------------------------------
    # LIMITI SETTIMANALI
    # ----------------------------------------------------------------

    def check_weekly_limits(self, weekly_pnl_pct: float) -> Dict:
        """
        Controlla i limiti settimanali.

        Args:
            weekly_pnl_pct: Variazione percentuale settimanale

        Returns:
            Dizionario con should_pause, pause_until, reason
        """
        if weekly_pnl_pct <= -self.max_weekly_loss:
            # Calcola data di ripresa (dopo N giorni)
            from datetime import timedelta
            pause_until = datetime.now(IT_TZ) + timedelta(days=self.pause_days)
            self._paused_until = pause_until

            logger.warning(
                f"Perdita settimanale {weekly_pnl_pct:.2%} supera limite {self.max_weekly_loss:.2%}. "
                f"Bot in pausa fino al {pause_until.strftime('%d/%m/%Y')}"
            )

            return {
                'should_pause': True,
                'pause_until': pause_until,
                'reason': f'Perdita settimanale {weekly_pnl_pct:.2%} eccessiva',
                'pause_days': self.pause_days
            }

        return {'should_pause': False, 'reason': ''}

    def is_paused(self) -> bool:
        """Verifica se il bot è in pausa per perdite settimanali."""
        if self._paused_until is None:
            return False
        return datetime.now(IT_TZ) < self._paused_until

    def get_pause_end_time(self) -> Optional[datetime]:
        """Restituisce quando finisce la pausa settimanale."""
        return self._paused_until

    # ----------------------------------------------------------------
    # VALIDAZIONE POSIZIONI
    # ----------------------------------------------------------------

    def can_open_position(self, symbol: str, open_positions: List[Dict]) -> Dict:
        """
        Verifica se è possibile aprire una nuova posizione.

        Args:
            symbol: Simbolo che si vuole tradare
            open_positions: Lista delle posizioni attualmente aperte

        Returns:
            Dizionario con can_open e reason
        """
        # Controlla numero massimo posizioni
        if len(open_positions) >= self.max_open_positions:
            return {
                'can_open': False,
                'reason': f'Massimo {self.max_open_positions} posizioni già aperte'
            }

        # Controlla se è già aperta una posizione su questo simbolo
        for pos in open_positions:
            if pos.get('symbol', '') == symbol:
                return {
                    'can_open': False,
                    'reason': f'Posizione già aperta su {symbol}'
                }

        # Verifica pausa settimanale
        if self.is_paused():
            pause_end = self.get_pause_end_time()
            return {
                'can_open': False,
                'reason': f'Bot in pausa fino al {pause_end.strftime("%d/%m/%Y %H:%M") if pause_end else "N/A"}'
            }

        return {'can_open': True, 'reason': ''}

    # ----------------------------------------------------------------
    # CHIUSURA FINE GIORNATA
    # ----------------------------------------------------------------

    def should_force_close(self, force_close_time: str = "21:45") -> bool:
        """
        Verifica se è l'ora di chiusura forzata delle posizioni.

        Args:
            force_close_time: Orario di chiusura forzata (formato HH:MM)

        Returns:
            True se deve chiudere tutto
        """
        now = datetime.now(IT_TZ)
        close_time = datetime.strptime(force_close_time, "%H:%M").time()
        return now.time() >= close_time

    # ----------------------------------------------------------------
    # REPORT RISCHIO
    # ----------------------------------------------------------------

    def get_risk_report(self, capital: float, open_positions: List[Dict]) -> Dict:
        """
        Genera un report dello stato del rischio attuale.

        Args:
            capital: Capitale attuale
            open_positions: Lista posizioni aperte

        Returns:
            Report completo del rischio
        """
        total_at_risk = sum(
            pos.get('market_value', 0) for pos in open_positions
        )
        capital_at_risk_pct = total_at_risk / capital if capital > 0 else 0

        return {
            'timestamp': datetime.now().isoformat(),
            'total_capital': capital,
            'open_positions_count': len(open_positions),
            'max_positions': self.max_open_positions,
            'capital_at_risk': total_at_risk,
            'capital_at_risk_pct': capital_at_risk_pct,
            'is_paused': self.is_paused(),
            'pause_until': self._paused_until.isoformat() if self._paused_until else None,
            'today_reduced_size': self._today_reduced_size,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'trailing_enabled': self.trailing_enabled,
        }
