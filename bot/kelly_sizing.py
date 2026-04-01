# ============================================================
# KELLY SIZING - Edge-Based Position Sizing
# Calcola position size usando Kelly Criterion
# ============================================================

import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class KellySizing:
    """
    Calcola position size usando Kelly Criterion basato su edge statistico.

    Kelly Criterion Formula:
    f* = (win_rate × avg_win - loss_rate × avg_loss) / avg_win

    Dove:
    - win_rate: % di trade vincenti
    - loss_rate: % di trade perdenti (= 1 - win_rate)
    - avg_win: profitto medio dei trade vincenti
    - avg_loss: perdita media dei trade perdenti (in valore assoluto)

    Questo calcola la frazione ottimale del capitale da rischiare
    per massimizzare la crescita nel lungo termine.

    Con Half-Kelly Safety (f*/2):
    - Bounds: [8%, 22%] del capitale per trade
    - Default 15% se < 20 trade storici (conservativo)

    Razionale:
    - Full Kelly è troppo aggressivo e causa drawdown severi
    - Half-Kelly è più robusta e adatta per scalping
    - Se edge è positivo (f* > 0), aumentiamo size
    - Se edge è negativo (f* < 0), non tradiamo
    - Bounds prevengono over-sizing anche con edge altissimo
    """

    def __init__(self, config: dict, database):
        """Inizializza Kelly Sizing Calculator."""
        self.config = config
        self.db = database

        # Parametri Kelly
        self.window = 50  # Ultimi 50 trade per calcolo rolling
        self.kelly_fraction_min = 0.08  # 8% minimo
        self.kelly_fraction_max = 0.22  # 22% massimo
        self.kelly_default = 0.15  # 15% se < 20 trade
        self.kelly_safety = 0.5  # Half-Kelly = f*/2

        logger.info(
            f"KellySizing inizializzato (window={self.window}, "
            f"bounds=[{self.kelly_fraction_min*100:.0f}%, {self.kelly_fraction_max*100:.0f}%])"
        )

    def calculate_kelly_fraction(self) -> Dict:
        """
        Calcola la frazione Kelly ottimale sul rolling window.

        Ritorna:
        {
            'kelly_fraction': float (non limitato, per diagnostica),
            'kelly_fraction_safe': float (con bounds, il valore effettivo da usare),
            'position_size_pct': float (percentuale finale del capitale per trade),
            'win_rate': float (0-1),
            'avg_win': float ($ per win),
            'avg_loss': float ($ per loss),
            'profit_factor': float (gross_profit / gross_loss),
            'trades_count': int,
            'recommendation': str,
            'timestamp': str
        }
        """
        try:
            # Prendi ultimi 30 trade chiusi
            trades = self.db.get_trade_history(limit=30)

            # Escludi trade con |pnl| > $5 (chiaramente anomalo)
            max_normal_pnl = 5.0
            trades = [t for t in trades if t.get('pnl') is not None and abs(t.get('pnl', 0)) <= max_normal_pnl]

            if not trades or len(trades) < 10:
                # Insufficienti dati: usa default conservativo
                return {
                    'kelly_fraction': 0.0,
                    'kelly_fraction_safe': self.kelly_default,
                    'position_size_pct': self.kelly_default,
                    'win_rate': 0.5,
                    'avg_win': 0.0,
                    'avg_loss': 0.0,
                    'profit_factor': 1.0,
                    'trades_count': len(trades),
                    'recommendation': f'< 5 trades ({len(trades)} attuali), uso default {self.kelly_default*100:.0f}%',
                    'timestamp': datetime.now().isoformat()
                }

            # ---- CALCOLA METRICHE ----
            # Filtra solo trade con pnl valido (non None)
            trades_valid = [t for t in trades if t.get('pnl') is not None]
            wins = [t for t in trades_valid if t.get('pnl', 0) > 0]
            losses = [t for t in trades_valid if t.get('pnl', 0) <= 0]

            if not trades_valid or len(trades_valid) < 5:
                # Insufficienti dati validi
                return {
                    'kelly_fraction': 0.0,
                    'kelly_fraction_safe': self.kelly_default,
                    'position_size_pct': self.kelly_default,
                    'win_rate': 0.5,
                    'avg_win': 0.0,
                    'avg_loss': 0.0,
                    'profit_factor': 1.0,
                    'trades_count': len(trades_valid),
                    'recommendation': f'< 5 valid trades ({len(trades_valid)} attuali), uso default {self.kelly_default*100:.0f}%',
                    'timestamp': datetime.now().isoformat()
                }

            if not wins or not losses:
                # Edge non definito (100% win o 100% loss)
                return {
                    'kelly_fraction': 0.0,
                    'kelly_fraction_safe': self.kelly_default,
                    'position_size_pct': self.kelly_default,
                    'win_rate': len(wins) / len(trades),
                    'avg_win': sum([t['pnl'] for t in wins]) / len(wins) if wins else 0,
                    'avg_loss': sum([abs(t['pnl']) for t in losses]) / len(losses) if losses else 0,
                    'profit_factor': 1.0,
                    'trades_count': len(trades),
                    'recommendation': 'Win/loss ratio not stable, use default sizing',
                    'timestamp': datetime.now().isoformat()
                }

            # Win rate e loss rate (usa trades_valid per denominatore)
            win_rate = len(wins) / len(trades_valid)
            loss_rate = 1.0 - win_rate

            # Profitti e perdite medie (in $ per trade)
            avg_win = sum([t['pnl'] for t in wins]) / len(wins)
            avg_loss = sum([abs(t['pnl']) for t in losses]) / len(losses)

            # Profit factor (gross_profit / gross_loss)
            gross_profit = sum([t['pnl'] for t in wins])
            gross_loss = sum([abs(t['pnl']) for t in losses])
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 1.0

            # ---- KELLY FORMULA ----
            # f* = (wr × W - lr × L) / W
            # Dove W = avg_win, L = avg_loss
            if avg_win > 0:
                kelly_fraction = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
            else:
                kelly_fraction = 0.0

            # Half-Kelly safety (f*/2)
            kelly_fraction_safe = kelly_fraction * self.kelly_safety

            # Applica bounds
            position_size_pct = max(
                self.kelly_fraction_min,
                min(self.kelly_fraction_max, kelly_fraction_safe)
            )

            # Generare raccomandazione
            if kelly_fraction < 0:
                recommendation = "Negative edge - reduce sizing or pause trading"
            elif kelly_fraction < 0.05:
                recommendation = "Weak edge - use minimum sizing"
            elif kelly_fraction > 0.5:
                recommendation = "Strong edge - at max sizing bounds"
            else:
                recommendation = f"Edge-based sizing: Kelly={kelly_fraction*100:.1f}% → Safe={kelly_fraction_safe*100:.1f}%"

            result = {
                'kelly_fraction': round(kelly_fraction, 4),
                'kelly_fraction_safe': round(kelly_fraction_safe, 4),
                'position_size_pct': round(position_size_pct, 4),
                'win_rate': round(win_rate, 3),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'profit_factor': round(profit_factor, 2),
                'trades_count': len(trades),
                'recommendation': recommendation,
                'timestamp': datetime.now().isoformat()
            }

            logger.info(
                f"Kelly Sizing: WR={win_rate*100:.1f}%, W=${avg_win:.2f}, L=${avg_loss:.2f} "
                f"→ f*={kelly_fraction*100:.1f}% → Safe={kelly_fraction_safe*100:.1f}% "
                f"→ Final={position_size_pct*100:.1f}% (PF={profit_factor:.2f})"
            )

            return result

        except Exception as e:
            logger.error(f"Errore calcolo Kelly fraction: {e}")
            return {
                'kelly_fraction': 0.0,
                'kelly_fraction_safe': self.kelly_default,
                'position_size_pct': self.kelly_default,
                'win_rate': 0.5,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 1.0,
                'trades_count': 0,
                'recommendation': f'Errore calcolo: {str(e)}',
                'timestamp': datetime.now().isoformat()
            }

    def get_kelly_diagnostics(self) -> Dict:
        """
        Ritorna diagnostica completa del Kelly Criterion.

        Utile per dashboard e debugging.
        """
        kelly_info = self.calculate_kelly_fraction()

        diagnostics = {
            'kelly_formula': 'f* = (wr × W - (1-wr) × L) / W',
            'kelly_inputs': {
                'win_rate': kelly_info['win_rate'],
                'avg_win': kelly_info['avg_win'],
                'avg_loss': kelly_info['avg_loss']
            },
            'kelly_outputs': {
                'kelly_fraction': kelly_info['kelly_fraction'],
                'kelly_fraction_half': kelly_info['kelly_fraction_safe'],
                'position_size_pct': kelly_info['position_size_pct'],
                'bounds': [self.kelly_fraction_min, self.kelly_fraction_max]
            },
            'metrics': {
                'profit_factor': kelly_info['profit_factor'],
                'trades_count': kelly_info['trades_count'],
                'recommendation': kelly_info['recommendation']
            }
        }

        return diagnostics
