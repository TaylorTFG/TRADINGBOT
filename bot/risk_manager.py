# ============================================================
# RISK MANAGER - GESTIONE DEL RISCHIO PER SCALPING
# Parametri ottimizzati per scalping crypto H24:
# SL 0.5%, TP 0.8%, max duration 15min, cooldown 2min dopo SL
# ============================================================

import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class RiskManager:
    """
    Risk Manager per SCALPING CRYPTO H24.

    Parametri ottimizzati:
    - Stop Loss: 0.5% (strettissimo)
    - Take Profit: 0.8% (piccoli guadagni frequenti)
    - Trailing Stop: activation 0.4%, distance 0.25%
    - Position Duration: max 15 minuti (timeout)
    - Cooldown: 2 minuti dopo ogni stop loss
    - Daily Loss: -3% → stop trading
    - Daily Target: +2% → riduce size al 50%
    - Max Trades: 50 per giorno
    - Max Open: 2 posizioni contemporanee
    """

    def __init__(self, config: dict, database):
        """Inizializza il Risk Manager per scalping."""
        self.config = config
        self.db = database
        self.risk_config = config.get('risk_management', {})

        # ---- PARAMETRI SCALPING ----
        self.stop_loss_pct = self.risk_config.get('stop_loss_pct', 0.005)        # -0.5%
        self.take_profit_pct = self.risk_config.get('take_profit_pct', 0.008)    # +0.8%
        self.max_risk_per_trade = self.risk_config.get('max_risk_per_trade', 0.02)

        # Trailing stop (activation 0.4%, distance 0.25%)
        trailing = self.risk_config.get('trailing_stop', {})
        self.trailing_enabled = trailing.get('enabled', True)
        self.trailing_activation = trailing.get('activation_pct', 0.004)
        self.trailing_distance = trailing.get('trail_pct', 0.0025)

        # Position limits
        self.max_open_positions = config.get('trading', {}).get('max_open_positions', 2)

        # Daily limits
        daily = self.risk_config.get('daily', {})
        self.max_daily_loss = daily.get('max_loss_pct', 0.03)        # -3% = $16.35
        self.daily_profit_target = daily.get('target_profit_pct', 0.02)  # +2% = $10.9
        self.max_trades_per_day = daily.get('max_trades', 50)

        # Weekly limits
        weekly = self.risk_config.get('weekly', {})
        self.max_weekly_loss = weekly.get('max_loss_pct', 0.08)
        self.pause_days = weekly.get('pause_days', 1)

        # Quality filters
        quality = self.risk_config.get('quality_filters', {})
        self.max_spread_pct = quality.get('max_spread_pct', 0.001)  # 0.1%
        self.cooldown_after_loss_sec = quality.get('cooldown_after_loss_sec', 120)  # 2 min
        self.max_position_duration_min = quality.get('max_position_duration_min', 15)

        # Sizing
        sizing = self.risk_config.get('sizing', {})
        self.full_agreement_pct = sizing.get('full_agreement_pct', 0.02)
        self.partial_agreement_pct = sizing.get('partial_agreement_pct', 0.01)

        # Stato interno
        self._paused_until: Optional[datetime] = None
        self._daily_starting_capital: Optional[float] = None
        self._today_reduced_size = False
        self._last_stop_loss_time: Optional[datetime] = None
        self._trades_today: int = 0

        logger.info(
            f"Risk Manager (Scalping) inizializzato | "
            f"SL: {self.stop_loss_pct*100:.1f}%, TP: {self.take_profit_pct*100:.1f}%, "
            f"Max Daily Loss: {self.max_daily_loss*100:.1f}%, Max Trades: {self.max_trades_per_day}"
        )

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
        Calcola la dimensione della posizione per scalping.

        Usa percentuale fissa del capitale:
        - 3/3 voti: 2% capitale
        - 2/3 voti: 1% capitale

        Args:
            capital: Capitale totale disponibile
            price: Prezzo corrente dell'asset
            atr: Average True Range (unused per scalping, usa % fissa)
            vote_score: Numero di voti concordi
            macro_multiplier: Moltiplicatore macro contesto

        Returns:
            Dizionario con qty, capital_at_risk, stop_loss, take_profit
        """
        # Seleziona percentuale base in base ai voti
        if vote_score >= 3:
            base_pct = self.full_agreement_pct
        else:
            base_pct = self.partial_agreement_pct

        # Applica moltiplicatore macro
        effective_pct = base_pct * macro_multiplier

        # Riduci size se abbiamo raggiunto target giornaliero
        if self._today_reduced_size:
            effective_pct *= 0.5
            logger.debug("Size ridotta al 50% per target giornaliero raggiunto")

        # Calcolo quantità
        capital_at_risk = capital * effective_pct
        qty = capital_at_risk / price

        # Arrotonda a 6 decimali (per crypto frazioni)
        qty = round(qty, 6)

        if qty < 0.000001:
            qty = 0

        # Stop loss e take profit (fissi per scalping)
        stop_loss = price * (1 - self.stop_loss_pct)
        take_profit = price * (1 + self.take_profit_pct)

        result = {
            'qty': qty,
            'capital_at_risk': qty * price,
            'stop_loss': round(stop_loss, 4),
            'take_profit': round(take_profit, 4),
            'effective_pct': effective_pct,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'ratio': self.take_profit_pct / self.stop_loss_pct if self.stop_loss_pct > 0 else 0,
        }

        logger.debug(
            f"Position sizing: qty={qty:.6f}, risk=${qty * price:.2f}, "
            f"SL=${stop_loss:.2f} (-{self.stop_loss_pct*100:.1f}%), "
            f"TP=${take_profit:.2f} (+{self.take_profit_pct*100:.1f}%)"
        )
        return result

    # ----------------------------------------------------------------
    # STOP LOSS E TRAILING STOP
    # ----------------------------------------------------------------

    def update_trailing_stop(self, trade: Dict, current_price: float) -> Optional[float]:
        """
        Aggiorna il trailing stop per scalping.

        Activation: +0.4%, Distance: 0.25%

        Args:
            trade: Dati del trade
            current_price: Prezzo corrente

        Returns:
            Nuovo prezzo dello stop loss o None
        """
        if not self.trailing_enabled:
            return None

        entry_price = trade['entry_price']
        current_stop = trade.get('stop_loss', 0)
        side = trade.get('side', 'buy')

        if side == 'buy':
            profit_pct = (current_price - entry_price) / entry_price

            # Si attiva solo dopo +0.4%
            if profit_pct < self.trailing_activation:
                return None

            # Nuovo stop a distanza 0.25%
            new_stop = current_price * (1 - self.trailing_distance)

            # Stop si muove solo in avanti
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
        """Verifica se lo stop loss è stato raggiunto."""
        stop_loss = trade.get('stop_loss', 0)
        side = trade.get('side', 'buy')

        if side == 'buy':
            return current_price <= stop_loss and stop_loss > 0
        else:
            return current_price >= stop_loss and stop_loss > 0

    def should_take_profit(self, trade: Dict, current_price: float) -> bool:
        """Verifica se il take profit è stato raggiunto."""
        take_profit = trade.get('take_profit', 0)
        side = trade.get('side', 'buy')

        if side == 'buy':
            return current_price >= take_profit and take_profit > 0
        else:
            return current_price <= take_profit and take_profit > 0

    def should_close_by_timeout(self, trade: Dict) -> bool:
        """
        Verifica se una posizione ha superato il timeout (15 minuti).

        Args:
            trade: Dati del trade (deve contenere created_at)

        Returns:
            True se la posizione è aperta da più di 15 minuti
        """
        if 'created_at' not in trade:
            return False

        try:
            created = datetime.fromisoformat(trade['created_at'])
            now = datetime.now(IT_TZ) if created.tzinfo else datetime.now()

            if created.tzinfo is None:
                created = created.replace(tzinfo=IT_TZ)
            elif now.tzinfo is None:
                now = datetime.now(IT_TZ)

            duration = now - created
            timeout_exceeded = duration > timedelta(minutes=self.max_position_duration_min)

            if timeout_exceeded:
                logger.debug(
                    f"[{trade.get('symbol')}] Timeout posizione: "
                    f"{duration.total_seconds()/60:.0f}min > {self.max_position_duration_min}min"
                )

            return timeout_exceeded

        except Exception as e:
            logger.warning(f"Errore verifica timeout: {e}")
            return False

    def is_in_cooldown(self) -> bool:
        """
        Verifica se siamo in cooldown dopo uno stop loss (2 minuti).

        Returns:
            True se in cooldown
        """
        if self._last_stop_loss_time is None:
            return False

        now = datetime.now(IT_TZ)
        elapsed = (now - self._last_stop_loss_time).total_seconds()
        in_cooldown = elapsed < self.cooldown_after_loss_sec

        if in_cooldown:
            logger.debug(f"In cooldown per altri {self.cooldown_after_loss_sec - elapsed:.0f}sec")

        return in_cooldown

    def set_stop_loss_cooldown(self):
        """Registra lo stop loss corrente per avviare il cooldown."""
        self._last_stop_loss_time = datetime.now(IT_TZ)
        logger.info(f"Cooldown attivato per {self.cooldown_after_loss_sec}sec")

    # ----------------------------------------------------------------
    # LIMITI GIORNALIERI
    # ----------------------------------------------------------------

    def check_daily_limits(self, current_capital: float, starting_capital: float) -> Dict:
        """
        Controlla i limiti giornalieri.

        - Se perdita >= -3% → stop trading
        - Se profitto >= +2% → riduce size al 50%
        - Se trade >= 50 → stop trading

        Args:
            current_capital: Capitale attuale
            starting_capital: Capitale inizio giornata

        Returns:
            Dizionario con can_trade, reason
        """
        if starting_capital <= 0:
            return {'can_trade': True, 'should_reduce_size': False, 'reason': ''}

        daily_change = (current_capital - starting_capital) / starting_capital

        # Perdita giornaliera: -3%
        if daily_change <= -self.max_daily_loss:
            logger.warning(f"Perdita giornaliera massima: {daily_change:.2%} >= {self.max_daily_loss:.2%}")
            return {
                'can_trade': False,
                'should_reduce_size': False,
                'reason': f'Perdita giornaliera {daily_change:.2%} supera limite {self.max_daily_loss:.2%}',
                'daily_pnl_pct': daily_change
            }

        # Target profitto: +2%
        if daily_change >= self.daily_profit_target:
            self._today_reduced_size = True
            logger.info(f"Target profitto raggiunto: {daily_change:.2%}. Size ridotta al 50%")
            return {
                'can_trade': True,
                'should_reduce_size': True,
                'reason': f'Target {daily_change:.2%} raggiunto. Size al 50%',
                'daily_pnl_pct': daily_change
            }

        return {
            'can_trade': True,
            'should_reduce_size': False,
            'reason': '',
            'daily_pnl_pct': daily_change
        }

    def check_daily_trade_count(self) -> Dict:
        """
        Controlla se è stato raggiunto il limite di 50 trade al giorno.

        Returns:
            Dizionario con can_trade, trades_today, reason
        """
        if self._trades_today >= self.max_trades_per_day:
            logger.warning(f"Limite trade giornalieri raggiunto: {self._trades_today}/{self.max_trades_per_day}")
            return {
                'can_trade': False,
                'trades_today': self._trades_today,
                'reason': f'Max {self.max_trades_per_day} trade/giorno raggiunti'
            }

        return {
            'can_trade': True,
            'trades_today': self._trades_today,
            'reason': ''
        }

    def increment_trade_count(self):
        """Incrementa il contatore di trade giornalieri."""
        self._trades_today += 1
        logger.debug(f"Trade count: {self._trades_today}/{self.max_trades_per_day}")

    def reset_daily_state(self):
        """Resetta lo stato giornaliero a mezzanotte."""
        self._today_reduced_size = False
        self._trades_today = 0
        self._last_stop_loss_time = None
        logger.info("Stato giornaliero resettato")

    # ----------------------------------------------------------------
    # LIMITI SETTIMANALI
    # ----------------------------------------------------------------

    def check_weekly_limits(self, weekly_pnl_pct: float) -> Dict:
        """
        Controlla i limiti settimanali.

        Args:
            weekly_pnl_pct: Variazione percentuale settimanale

        Returns:
            Dizionario con should_pause, pause_until
        """
        if weekly_pnl_pct <= -self.max_weekly_loss:
            pause_until = datetime.now(IT_TZ) + timedelta(days=self.pause_days)
            self._paused_until = pause_until

            logger.warning(
                f"Perdita settimanale {weekly_pnl_pct:.2%} supera limite {self.max_weekly_loss:.2%}. "
                f"Pausa fino al {pause_until.strftime('%d/%m/%Y')}"
            )

            return {
                'should_pause': True,
                'pause_until': pause_until,
                'reason': f'Perdita settimanale {weekly_pnl_pct:.2%} eccessiva',
                'pause_days': self.pause_days
            }

        return {'should_pause': False, 'reason': ''}

    def is_paused(self) -> bool:
        """Verifica se il bot è in pausa."""
        if self._paused_until is None:
            return False
        return datetime.now(IT_TZ) < self._paused_until

    def get_pause_end_time(self) -> Optional[datetime]:
        """Restituisce quando finisce la pausa."""
        return self._paused_until

    # ----------------------------------------------------------------
    # VALIDAZIONE POSIZIONI
    # ----------------------------------------------------------------

    def can_open_position(self, symbol: str, open_positions: List[Dict]) -> Dict:
        """
        Verifica se è possibile aprire una nuova posizione.

        Checks:
        - Max 2 posizioni aperte
        - Non aprire su stessa coppia
        - Non aprire se in cooldown dopo SL
        - Non aprire se max trade/giorno raggiunto

        Args:
            symbol: Simbolo da tradare
            open_positions: Posizioni aperte

        Returns:
            Dizionario con can_open, reason
        """
        # Max posizioni: 2
        if len(open_positions) >= self.max_open_positions:
            return {
                'can_open': False,
                'reason': f'Max {self.max_open_positions} posizioni aperte'
            }

        # Non aprire su stessa coppia
        for pos in open_positions:
            if pos.get('symbol', '') == symbol:
                return {
                    'can_open': False,
                    'reason': f'Posizione già aperta su {symbol}'
                }

        # Cooldown dopo SL
        if self.is_in_cooldown():
            return {
                'can_open': False,
                'reason': f'Cooldown attivo per altri {self.cooldown_after_loss_sec}sec'
            }

        # Max trade/giorno
        if self._trades_today >= self.max_trades_per_day:
            return {
                'can_open': False,
                'reason': f'Limite trade giornalieri raggiunto ({self._trades_today}/{self.max_trades_per_day})'
            }

        # Pausa settimanale
        if self.is_paused():
            pause_end = self.get_pause_end_time()
            return {
                'can_open': False,
                'reason': f'Bot in pausa fino al {pause_end.strftime("%d/%m/%Y") if pause_end else "N/A"}'
            }

        return {'can_open': True, 'reason': ''}

    # ----------------------------------------------------------------
    # CHIUSURA FINE GIORNATA
    # ----------------------------------------------------------------

    def should_force_close(self, force_close_time: str = "23:58") -> bool:
        """Verifica se è l'ora di chiusura forzata."""
        now = datetime.now(IT_TZ)
        close_time = datetime.strptime(force_close_time, "%H:%M").time()
        return now.time() >= close_time

    # ----------------------------------------------------------------
    # REPORT RISCHIO
    # ----------------------------------------------------------------

    def get_risk_report(self, capital: float, open_positions: List[Dict]) -> Dict:
        """Genera report dello stato del rischio."""
        total_at_risk = sum(pos.get('market_value', 0) for pos in open_positions)
        capital_at_risk_pct = total_at_risk / capital if capital > 0 else 0

        return {
            'timestamp': datetime.now().isoformat(),
            'total_capital': capital,
            'open_positions_count': len(open_positions),
            'max_positions': self.max_open_positions,
            'capital_at_risk': total_at_risk,
            'capital_at_risk_pct': capital_at_risk_pct,
            'is_paused': self.is_paused(),
            'in_cooldown': self.is_in_cooldown(),
            'trades_today': self._trades_today,
            'max_trades_per_day': self.max_trades_per_day,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'trailing_enabled': self.trailing_enabled,
            'max_position_duration_min': self.max_position_duration_min,
        }
