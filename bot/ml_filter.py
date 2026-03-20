# ============================================================
# ML FILTER - RANDOM FOREST CLASSIFIER
# Filtro aggiuntivo basato su Machine Learning
# Predice se un trade sarà profittevole nelle prossime 2 ore
# ============================================================

import logging
import os
import pickle
import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class MLFilter:
    """
    Filtro ML basato su Random Forest Classifier.

    Features usate per la predizione:
    - Ultimi 20 valori di RSI, MACD, volume ratio, ATR
    - Distanza da EMA200
    - Sentiment score
    - Ora del giorno (come feature ciclica)
    - Giorno della settimana
    - VIX level (se disponibile)

    Target: trade profittevole si/no nelle successive 2 ore

    Training: automatico ogni domenica sugli ultimi 6 mesi
    Soglia: 65% confidence per validare il segnale
    """

    def __init__(self, config: dict, database):
        """
        Inizializza il filtro ML.

        Args:
            config: Configurazione dal config.yaml
            database: Istanza del DatabaseManager
        """
        self.config = config
        self.db = database
        self.ml_config = config.get('ml_filter', {})
        self.enabled = self.ml_config.get('enabled', True)
        self.min_confidence = self.ml_config.get('min_confidence', 0.65)
        self.model_path = 'models/ml_model.pkl'
        self.scaler_path = 'models/ml_scaler.pkl'

        # Parametri Random Forest
        self.n_estimators = self.ml_config.get('n_estimators', 100)
        self.max_depth = self.ml_config.get('max_depth', 10)
        self.random_state = self.ml_config.get('random_state', 42)

        # Modello e scaler
        self._model = None
        self._scaler = None
        self._is_trained = False
        self._feature_names = []

        # Carica modello esistente se presente
        self._load_model()

        logger.info(f"MLFilter inizializzato (confidence min: {self.min_confidence})")

    def _load_model(self):
        """Carica il modello ML dal file se esiste."""
        try:
            if os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    self._model = pickle.load(f)
                logger.info("Modello ML caricato da file")
                self._is_trained = True

            if os.path.exists(self.scaler_path):
                with open(self.scaler_path, 'rb') as f:
                    self._scaler = pickle.load(f)
        except Exception as e:
            logger.warning(f"Impossibile caricare modello ML: {e}. Sarà addestrato al primo training.")

    def _save_model(self):
        """Salva il modello ML su file."""
        try:
            os.makedirs('models', exist_ok=True)
            with open(self.model_path, 'wb') as f:
                pickle.dump(self._model, f)
            with open(self.scaler_path, 'wb') as f:
                pickle.dump(self._scaler, f)
            logger.info(f"Modello ML salvato in {self.model_path}")
        except Exception as e:
            logger.error(f"Errore salvataggio modello: {e}")

    def extract_features(
        self,
        df: pd.DataFrame,
        sentiment_score: float = 0.0,
        vix_level: Optional[float] = None
    ) -> Optional[np.ndarray]:
        """
        Estrae le feature per il modello ML dall'ultimo punto del DataFrame.

        Args:
            df: DataFrame con indicatori tecnici calcolati
            sentiment_score: Score sentiment corrente
            vix_level: Livello VIX attuale

        Returns:
            Array numpy con le feature o None se dati insufficienti
        """
        if df is None or len(df) < 20:
            return None

        try:
            last = df.iloc[-1]
            now = datetime.now(IT_TZ)

            features = {}

            # --- Feature base ---
            features['rsi'] = float(last.get('rsi', 50)) if pd.notna(last.get('rsi')) else 50.0
            features['macd'] = float(last.get('macd', 0)) if pd.notna(last.get('macd')) else 0.0
            features['macd_signal'] = float(last.get('macd_signal', 0)) if pd.notna(last.get('macd_signal')) else 0.0
            features['macd_hist'] = float(last.get('macd_hist', 0)) if pd.notna(last.get('macd_hist')) else 0.0
            features['volume_ratio'] = float(last.get('volume_ratio', 1)) if pd.notna(last.get('volume_ratio')) else 1.0
            features['atr'] = float(last.get('atr', 0)) if pd.notna(last.get('atr')) else 0.0
            features['adx'] = float(last.get('adx', 25)) if pd.notna(last.get('adx')) else 25.0

            # --- Distanza da EMA200 ---
            close = float(last.get('close', 0))
            ema200 = float(last.get('ema200', close)) if pd.notna(last.get('ema200')) else close
            features['dist_ema200'] = (close - ema200) / ema200 if ema200 > 0 else 0.0

            # --- Trend EMA20 vs EMA50 ---
            ema20 = float(last.get('ema_20', close)) if pd.notna(last.get('ema_20')) else close
            ema50 = float(last.get('ema_50', close)) if pd.notna(last.get('ema_50')) else close
            features['ema_cross'] = (ema20 - ema50) / ema50 if ema50 > 0 else 0.0

            # --- Bollinger Band Position ---
            bb_upper = float(last.get('bb_upper', close * 1.02)) if pd.notna(last.get('bb_upper')) else close * 1.02
            bb_lower = float(last.get('bb_lower', close * 0.98)) if pd.notna(last.get('bb_lower')) else close * 0.98
            bb_range = bb_upper - bb_lower
            features['bb_position'] = (close - bb_lower) / bb_range if bb_range > 0 else 0.5

            # --- Volatilità recente ---
            if len(df) >= 20:
                recent_returns = df['close'].pct_change().tail(20)
                features['volatility_20'] = float(recent_returns.std()) if not recent_returns.empty else 0.0
            else:
                features['volatility_20'] = 0.0

            # --- Momentum ---
            if len(df) >= 10:
                features['momentum_5'] = float(
                    (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]
                ) if df['close'].iloc[-5] > 0 else 0.0
                features['momentum_10'] = float(
                    (df['close'].iloc[-1] - df['close'].iloc[-10]) / df['close'].iloc[-10]
                ) if df['close'].iloc[-10] > 0 else 0.0
            else:
                features['momentum_5'] = 0.0
                features['momentum_10'] = 0.0

            # --- Sentiment ---
            features['sentiment_score'] = float(sentiment_score)

            # --- Temporali (features cicliche) ---
            # Ora del giorno come seno/coseno per catturare la ciclicità
            hour_of_day = now.hour + now.minute / 60
            features['hour_sin'] = float(np.sin(2 * np.pi * hour_of_day / 24))
            features['hour_cos'] = float(np.cos(2 * np.pi * hour_of_day / 24))

            # Giorno della settimana (0=Lun, 6=Dom)
            day_of_week = now.weekday()
            features['day_sin'] = float(np.sin(2 * np.pi * day_of_week / 7))
            features['day_cos'] = float(np.cos(2 * np.pi * day_of_week / 7))

            # --- VIX ---
            features['vix'] = float(vix_level) if vix_level is not None else 20.0

            # Converti in array numpy preservando l'ordine
            self._feature_names = list(features.keys())
            feature_array = np.array([features[k] for k in self._feature_names]).reshape(1, -1)

            # Sostituisci NaN e Inf
            feature_array = np.nan_to_num(feature_array, nan=0.0, posinf=0.0, neginf=0.0)

            return feature_array

        except Exception as e:
            logger.error(f"Errore estrazione features ML: {e}")
            return None

    def predict(
        self,
        df: pd.DataFrame,
        sentiment_score: float = 0.0,
        vix_level: Optional[float] = None
    ) -> Dict:
        """
        Predice se il trade sarà profittevole.

        Args:
            df: DataFrame con indicatori tecnici
            sentiment_score: Score del sentiment
            vix_level: Livello VIX

        Returns:
            Dizionario con profitable, confidence, approved
        """
        if not self.enabled:
            return {
                'approved': True,
                'confidence': 1.0,
                'reason': 'ML filter disabilitato'
            }

        # Se non c'è un modello addestrato, approva sempre
        if not self._is_trained or self._model is None:
            return {
                'approved': True,
                'confidence': 0.5,
                'reason': 'Modello ML non ancora addestrato. Approva di default.'
            }

        # Estrai features
        features = self.extract_features(df, sentiment_score, vix_level)
        if features is None:
            return {
                'approved': True,
                'confidence': 0.5,
                'reason': 'Feature extraction fallita. Approva di default.'
            }

        try:
            # Applica scaler se disponibile
            if self._scaler is not None:
                features = self._scaler.transform(features)

            # Predizione
            proba = self._model.predict_proba(features)[0]

            # Indice 1 = classe "profittevole"
            confidence = float(proba[1]) if len(proba) > 1 else float(proba[0])
            predicted_profitable = confidence >= 0.5
            approved = confidence >= self.min_confidence

            result = {
                'approved': approved,
                'predicted_profitable': predicted_profitable,
                'confidence': confidence,
                'min_confidence': self.min_confidence,
                'reason': (
                    f"ML approva con {confidence:.1%} confidence" if approved
                    else f"ML rigetta: {confidence:.1%} < {self.min_confidence:.1%}"
                )
            }

            logger.debug(
                f"ML Predict: {'APPROVED' if approved else 'REJECTED'} "
                f"(confidence: {confidence:.1%})"
            )
            return result

        except Exception as e:
            logger.error(f"Errore predizione ML: {e}")
            return {
                'approved': True,
                'confidence': 0.5,
                'reason': f'Errore ML: {e}. Approva di default.'
            }

    def train(self, broker, symbols: List[str]) -> Dict:
        """
        Addestra il modello ML su dati storici.

        Args:
            broker: BrokerClient per recuperare dati storici
            symbols: Lista simboli su cui addestrare

        Returns:
            Dizionario con metriche del training
        """
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, classification_report

        logger.info("Inizio training modello ML...")

        training_months = self.ml_config.get('training_months', 6)
        start_date = datetime.now() - timedelta(days=training_months * 30)

        all_features = []
        all_labels = []

        for symbol in symbols:
            try:
                # Recupera dati storici
                df = broker.get_bars(symbol, '5m', start_date)
                if df is None or len(df) < 200:
                    logger.warning(f"Dati insufficienti per training su {symbol}")
                    continue

                # Calcola indicatori (usa ConfluenceStrategy)
                from bot.strategy_confluence import ConfluenceStrategy
                confluence = ConfluenceStrategy(self.config)
                df = confluence.calculate_indicators(df)
                if df is None:
                    continue

                # Calcola volume ratio manualmente
                df['volume_ma'] = df['volume'].rolling(20).mean()
                df['volume_ratio'] = df['volume'] / df['volume_ma']

                # Genera features e label per ogni punto temporale
                for i in range(100, len(df) - 24):
                    window = df.iloc[i-20:i+1].copy()

                    # Estrai feature
                    feature = self.extract_features(window)
                    if feature is None:
                        continue

                    # Label: prezzo è salito del >1% nelle successive 2 ore?
                    future_price = df['close'].iloc[i + 24]  # 24 candele da 5min = 2 ore
                    current_price = df['close'].iloc[i]
                    future_return = (future_price - current_price) / current_price
                    label = 1 if future_return > 0.01 else 0  # +1% = profittevole

                    all_features.append(feature.flatten())
                    all_labels.append(label)

                logger.debug(f"Training data da {symbol}: {len(all_labels)} campioni")

            except Exception as e:
                logger.error(f"Errore raccolta training data per {symbol}: {e}")

        if len(all_features) < 100:
            logger.warning(f"Dataset troppo piccolo per training: {len(all_features)} campioni")
            return {'success': False, 'reason': 'Dataset insufficiente'}

        X = np.array(all_features)
        y = np.array(all_labels)

        logger.info(f"Dataset training: {len(X)} campioni, {X.shape[1]} features")
        logger.info(f"Distribuzione classi: profittevole={sum(y)}, non profittevole={len(y)-sum(y)}")

        # Split train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=self.random_state, stratify=y
        )

        # Normalizzazione
        self._scaler = StandardScaler()
        X_train_scaled = self._scaler.fit_transform(X_train)
        X_test_scaled = self._scaler.transform(X_test)

        # Training Random Forest
        self._model = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            random_state=self.random_state,
            n_jobs=-1,  # Usa tutti i core disponibili
            class_weight='balanced'  # Bilancia classi sbilanciate
        )

        self._model.fit(X_train_scaled, y_train)
        self._is_trained = True

        # Valutazione
        y_pred = self._model.predict(X_test_scaled)
        accuracy = accuracy_score(y_test, y_pred)

        # Importanza features
        feature_importance = dict(zip(
            self._feature_names,
            self._model.feature_importances_
        ))
        top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:5]

        # Salva il modello
        self._save_model()

        metrics = {
            'success': True,
            'accuracy': accuracy,
            'train_samples': len(X_train),
            'test_samples': len(X_test),
            'positive_rate': sum(y) / len(y),
            'top_features': top_features,
            'trained_at': datetime.now().isoformat()
        }

        logger.info(
            f"ML Training completato: accuracy={accuracy:.2%}, "
            f"campioni={len(X)}, "
            f"top feature: {top_features[0][0] if top_features else 'N/A'}"
        )

        return metrics

    def should_retrain(self) -> bool:
        """
        Verifica se è domenica e se il modello deve essere riaddestrato.

        Returns:
            True se è domenica e il modello non è stato addestrato oggi
        """
        if not self.ml_config.get('auto_retrain', True):
            return False

        now = datetime.now(IT_TZ)
        retrain_day = self.ml_config.get('retrain_day', 'sunday').lower()

        day_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2,
            'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
        }

        target_day = day_map.get(retrain_day, 6)

        if now.weekday() == target_day:
            # Verifica se il modello è stato addestrato oggi
            if os.path.exists(self.model_path):
                mod_time = os.path.getmtime(self.model_path)
                mod_date = datetime.fromtimestamp(mod_time).date()
                return mod_date < now.date()
            return True

        return False
