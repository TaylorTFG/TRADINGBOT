# ============================================================
# RISK MANAGER - GESTIONE DEL RISCHIO PER SCALPING
# Parametri ottimizzati per scalping crypto H24:
# SL 0.5%, TP 0.8%, max duration 15min, cooldown 2min dopo SL
# ============================================================

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class RiskManager:
    """
    Risk Manager per SCALPING CRYPTO H24 - SCALATO €2500.

    Parametri ottimizzati per €2500 capitale:
    - Stop Loss: 0.5% (strettissimo)
    - Take Profit: 1.0% (ratio 1:2)
    - Trailing Stop: activation 1.0%, distance 0.3%
    - Break-Even: activation 0.7% (zero loss guarantee)
    - Position Duration: max 15 minuti (timeout)
    - Cooldown: 2 minuti dopo ogni stop loss
    - Daily Loss: -4% → stop trading (€100)
    - Daily Target: +2.5% → riduce size al 50% (€62.50)
    - Max Trades: 80 per giorno (aumentato)
    - Max Open: 4 posizioni contemporanee (25% max per pos)
    """

    def __init__(self, config: dict, database):
        """Inizializza il Risk Manager per scalping."""
        self.config = config
        self.db = database
        self.risk_config = config.get('risk_management', {})

        # ---- PARAMETRI SCALPING EVOLUTO ----
        self.stop_loss_pct = self.risk_config.get('stop_loss_pct', 0.005)        # -0.5%
        self.take_profit_pct = self.risk_config.get('take_profit_pct', 0.010)    # +1.0% (era 0.8%)
        self.max_risk_per_trade = self.risk_config.get('max_risk_per_trade', 0.025)  # 2.5% (scalato)

        # Trailing stop (activation 1.0%, distance 0.3%)
        trailing = self.risk_config.get('trailing_stop', {})
        self.trailing_enabled = trailing.get('enabled', True)
        self.trailing_activation = trailing.get('activation_pct', 0.01)    # Attiva dopo +1% (era 0.4%)
        self.trailing_distance = trailing.get('trail_pct', 0.003)          # Distance 0.3% (era 0.25%)

        # Break-Even automatico (activation 0.7%)
        break_even = self.risk_config.get('break_even', {})
        self.break_even_enabled = break_even.get('enabled', True)
        self.break_even_activation = break_even.get('activation_pct', 0.007)  # Attiva a +0.7%

        # Position limits
        self.max_open_positions = config.get('trading', {}).get('max_open_positions', 2)

        # Daily limits (scalati per €2500)
        daily = self.risk_config.get('daily', {})
        self.max_daily_loss = daily.get('max_loss_pct', 0.04)        # -4% = €100 (era -3%)
        self.daily_profit_target = daily.get('target_profit_pct', 0.025)  # +2.5% = €62.50 (era +2%)
        self.max_trades_per_day = daily.get('max_trades', 80)        # 80 trade (era 50)

        # Weekly limits
        weekly = self.risk_config.get('weekly', {})
        self.max_weekly_loss = weekly.get('max_loss_pct', 0.08)
        self.pause_days = weekly.get('pause_days', 1)

        # Quality filters
        quality = self.risk_config.get('quality_filters', {})
        self.max_spread_pct = quality.get('max_spread_pct', 0.001)  # 0.1%
        self.cooldown_after_loss_sec = quality.get('cooldown_after_loss_sec', 120)  # 2 min
        self.max_position_duration_min = quality.get('max_position_duration_min', 15)

        # Sizing (4 posizioni, 25% max per pos)
        sizing = self.risk_config.get('sizing', {})
        self.full_agreement_pct = sizing.get('full_agreement_pct', 0.025)     # 2.5% (era 2%)
        self.partial_agreement_pct = sizing.get('partial_agreement_pct', 0.0125)  # 1.25% (era 1%)
        self.max_position_pct = sizing.get('max_position_pct', 0.025)         # Hard limit 2.5%

        # Stato interno
        self._paused_until: Optional[datetime] = None
        self._daily_starting_capital: Optional[float] = None
        self._today_reduced_size = False
        self._last_stop_loss_time: Optional[datetime] = None
        self._trades_today: int = 0

        logger.info(
            f"Risk Manager (Scalping H24 €2500) inizializzato | "
            f"SL: {self.stop_loss_pct*100:.1f}%, TP: {self.take_profit_pct*100:.1f}% (R/R 1:2), "
            f"Trailing: +{self.trailing_activation*100:.1f}% activation, "
            f"Break-even: +{self.break_even_activation*100:.1f}%, "
            f"Max Positions: 4, Max Daily Loss: {self.max_daily_loss*100:.1f}%, "
            f"Max Trades: {self.max_trades_per_day}"
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

    def calculate_atr_based_stops(
        self,
        df_1min,
        entry_price: float,
        atr_period: int = 7
    ) -> Dict:
        """
        Calcola SL e TP dinamici basati su ATR (volatilità del mercato).

        Formula:
        - SL = 1.2 × ATR(7), bounds [0.3%, 1.0%]
        - TP = 2.5 × ATR(7), bounds [0.7%, 2.5%]
        - Trailing: activation 1.2×ATR, distance 0.4%

        Questo adatta il rischio alla volatilità:
        - Mercato volatile: SL/TP più ampi
        - Mercato stabile: SL/TP più stretti
        """
        if df_1min is None or len(df_1min) < atr_period + 5:
            # Fallback a fixed SL/TP se dati insufficienti
            return {
                'sl_pct': self.stop_loss_pct,
                'tp_pct': self.take_profit_pct,
                'trailing_activation': self.trailing_activation,
                'trailing_distance': self.trailing_distance,
                'atr_used': False,
                'atr_value': None,
                'reason': 'Dati insufficienti, fallback a fixed SL/TP'
            }

        try:
            import pandas as pd
            # Calcola ATR manualmente o usa libreria ta se disponibile
            high = df_1min['high']
            low = df_1min['low']
            close = df_1min['close']

            # True Range
            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

            # ATR = media mobile del True Range
            atr = true_range.rolling(window=atr_period).mean()
            atr_current = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else None

            if atr_current is None or atr_current == 0:
                return {
                    'sl_pct': self.stop_loss_pct,
                    'tp_pct': self.take_profit_pct,
                    'trailing_activation': self.trailing_activation,
                    'trailing_distance': self.trailing_distance,
                    'atr_used': False,
                    'atr_value': None,
                    'reason': 'ATR non disponibile'
                }

            # Calcola percentuali basate su ATR
            atr_pct = atr_current / entry_price

            # SL: 1.2 × ATR, bounds [0.3%, 1.0%]
            sl_pct = min(0.010, max(0.003, 1.2 * atr_pct))

            # TP: 2.5 × ATR, bounds [0.7%, 2.5%]
            tp_pct = min(0.025, max(0.007, 2.5 * atr_pct))

            # Trailing: activation 1.2×ATR, distance 0.4%
            trailing_activation = 1.2 * atr_pct
            trailing_distance = 0.004

            result = {
                'sl_pct': round(sl_pct, 5),
                'tp_pct': round(tp_pct, 5),
                'trailing_activation': round(trailing_activation, 5),
                'trailing_distance': trailing_distance,
                'atr_used': True,
                'atr_value': round(atr_current, 4),
                'atr_pct': round(atr_pct * 100, 3),
                'reason': f'ATR={atr_current:.4f} ({atr_pct*100:.3f}%)'
            }

            logger.debug(
                f"ATR-based stops: SL={sl_pct*100:.2f}% ({sl_pct*entry_price:.2f}), "
                f"TP={tp_pct*100:.2f}% ({tp_pct*entry_price:.2f}), "
                f"ATR={atr_current:.4f}"
            )

            return result

        except Exception as e:
            logger.error(f"Errore calcolo ATR-based stops: {e}")
            return {
                'sl_pct': self.stop_loss_pct,
                'tp_pct': self.take_profit_pct,
                'trailing_activation': self.trailing_activation,
                'trailing_distance': self.trailing_distance,
                'atr_used': False,
                'atr_value': None,
                'reason': f'Errore: {str(e)}'
            }

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

            # Normalizza created se naive (senza timezone)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            # Usa UTC per il timestamp corrente
            now = datetime.now(timezone.utc)

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

        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_stop_loss_time).total_seconds()
        in_cooldown = elapsed < self.cooldown_after_loss_sec

        if in_cooldown:
            logger.debug(f"In cooldown per altri {self.cooldown_after_loss_sec - elapsed:.0f}sec")

        return in_cooldown

    def set_stop_loss_cooldown(self):
        """Registra lo stop loss corrente per avviare il cooldown."""
        self._last_stop_loss_time = datetime.now(timezone.utc)
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
            pause_until = datetime.now(timezone.utc) + timedelta(days=self.pause_days)
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
        return datetime.now(timezone.utc) < self._paused_until

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
        now = datetime.now(timezone.utc)
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
            'timestamp': datetime.now(timezone.utc).isoformat(),
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
