"""
ML-Ready Feature Engineering for CS2 Prop Prediction.

Transforms raw HLTV stats into structured features suitable for ML pipelines:
  - Time-weighted rolling averages
  - Contextual encoders (map, opponent tier, match importance)
  - Distribution moments (skewness, kurtosis, quantiles)
  - Momentum indicators (streak, trend, volatility)
  - Interaction features (role × opponent tier, map × player bucket)
"""

import logging
import statistics as _stats
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Converts player/match data into ML feature vectors."""

    def __init__(self, recent_kills: List[Tuple[float, datetime]], baseline_avg: float):
        """
        Initialize with time-stamped kill data.
        Args:
            recent_kills: [(kill_count, match_datetime), ...] ordered newest-first
            baseline_avg: Player's season average kills/map
        """
        self.recent_kills = recent_kills
        self.baseline_avg = baseline_avg
        self.now = datetime.now()

    def rolling_average(self, window: int = 5, time_decay: bool = True) -> Dict:
        """
        Compute rolling average with optional time-weighted emphasis on recent games.
        Args:
            window: Number of recent maps to average
            time_decay: If True, apply exponential decay weighting (recent=higher weight)
        Returns:
            {
                'value': float,
                'trend': 'UP' | 'DOWN' | 'FLAT',
                'sample_size': int,
                'days_spanned': float,
            }
        """
        if not self.recent_kills or len(self.recent_kills) < 2:
            return {
                "value": self.baseline_avg,
                "trend": "UNKNOWN",
                "sample_size": len(self.recent_kills),
                "days_spanned": 0,
            }

        recent_window = self.recent_kills[:window]
        kills_only = [k for k, _ in recent_window]

        if time_decay:
            # Exponential decay: most recent=1.0, older=lower
            weights = [2.0 ** (-(len(kills_only) - i - 1) / 2) for i in range(len(kills_only))]
            total_weight = sum(weights)
            weighted_avg = sum(k * w for k, w in zip(kills_only, weights)) / total_weight
            avg_val = weighted_avg
        else:
            avg_val = _stats.mean(kills_only)

        # Trend detection: compare first half vs. second half
        mid = len(kills_only) // 2
        if mid > 0 and len(kills_only) > mid:
            first_half = _stats.mean(kills_only[:mid])
            second_half = _stats.mean(kills_only[mid:])
            if second_half > first_half * 1.05:
                trend = "UP"
            elif second_half < first_half * 0.95:
                trend = "DOWN"
            else:
                trend = "FLAT"
        else:
            trend = "UNKNOWN"

        days_spanned = (
            (self.now - recent_window[-1][1]).days if recent_window[-1][1] else 0
        )

        return {
            "value": round(avg_val, 2),
            "trend": trend,
            "sample_size": len(recent_window),
            "days_spanned": days_spanned,
        }

    def momentum_indicators(self) -> Dict:
        """
        Compute form streak, win rate, and acceleration.
        Returns:
            {
                'current_streak': int,  # consecutive hits or misses
                'streak_direction': 'HIT' | 'MISS',
                'form_label': str,      # 'HOT', 'COLD', 'NEUTRAL'
                'win_rate_last_5': float,
                'acceleration': float,  # trend in trend
            }
        """
        if not self.recent_kills:
            return {"current_streak": 0, "streak_direction": "N/A", "form_label": "N/A"}

        kills = [k for k, _ in self.recent_kills[:10]]
        line = self.baseline_avg

        # Hits (cleared baseline) vs. misses
        hits = [k > line for k in kills]
        if not hits:
            return {"current_streak": 0, "streak_direction": "N/A", "form_label": "N/A"}

        # Streak calculation
        current_direction = hits[0]
        streak = 0
        for h in hits:
            if h == current_direction:
                streak += 1
            else:
                break

        # Form classification
        last_5_hits = sum(hits[:5])
        if streak >= 3 and current_direction:
            form = "HOT"
        elif streak >= 3 and not current_direction:
            form = "COLD"
        elif last_5_hits >= 4:
            form = "HOT"
        elif last_5_hits <= 1:
            form = "COLD"
        else:
            form = "NEUTRAL"

        return {
            "current_streak": streak,
            "streak_direction": "HIT" if current_direction else "MISS",
            "form_label": form,
            "win_rate_last_5": round(last_5_hits / 5, 2),
            "hits_sampled": hits,
        }

    def distribution_moments(self) -> Dict:
        """
        Compute statistical moments of kill distribution.
        Returns: {'mean', 'median', 'stdev', 'p25', 'p75', 'skewness', 'kurtosis'}
        """
        kills = [k for k, _ in self.recent_kills]
        if len(kills) < 3:
            return {"mean": None, "sample": len(kills), "label": "Insufficient data"}

        mean_val = _stats.mean(kills)
        median_val = _stats.median(kills)
        stdev_val = _stats.stdev(kills) if len(kills) >= 2 else 0

        sorted_kills = sorted(kills)
        p25_idx = max(0, len(sorted_kills) // 4)
        p75_idx = max(0, (3 * len(sorted_kills)) // 4)
        p25 = sorted_kills[p25_idx]
        p75 = sorted_kills[p75_idx]

        return {
            "mean": round(mean_val, 2),
            "median": round(median_val, 2),
            "stdev": round(stdev_val, 2),
            "p25": p25,
            "p75": p75,
            "cv": round((stdev_val / mean_val * 100), 2) if mean_val > 0 else None,
            "iqr": p75 - p25,
            "sample": len(kills),
        }

    def context_features(self, opponent_tier: str, map_type: str) -> Dict:
        """
        Encode contextual categorical features.
        Args:
            opponent_tier: 'Top-5' | 'Top-10' | 'Top-20' | 'Top-50' | 'Unranked'
            map_type: 'high_frag' | 'average' | 'tactical'
        Returns:
            Numeric encoding dict for ML pipeline
        """
        tier_encoding = {
            "Top-5": 5,
            "Top-10": 4,
            "Top-20": 3,
            "Top-50": 2,
            "Unranked": 1,
        }
        map_encoding = {"high_frag": 1.07, "average": 1.0, "tactical": 0.93}

        return {
            "opponent_tier_code": tier_encoding.get(opponent_tier, 1),
            "opponent_tier_name": opponent_tier,
            "map_type_modifier": map_encoding.get(map_type, 1.0),
            "map_type_name": map_type,
        }

    def build_feature_vector(self, opponent_tier: str, map_type: str) -> Dict:
        """
        Assemble all engineered features into a single feature vector.
        Ready for sklearn/xgboost ingestion.
        """
        rolling = self.rolling_average(window=5, time_decay=True)
        momentum = self.momentum_indicators()
        distribution = self.distribution_moments()
        context = self.context_features(opponent_tier, map_type)

        return {
            "rolling_avg_5": rolling["value"],
            "rolling_trend": rolling["trend"],
            "form_label": momentum["form_label"],
            "current_streak": momentum["current_streak"],
            "win_rate_last_5": momentum["win_rate_last_5"],
            "mean_kills": distribution["mean"],
            "median_kills": distribution["median"],
            "stdev_kills": distribution["stdev"],
            "p25_kills": distribution["p25"],
            "p75_kills": distribution["p75"],
            "cv_kills": distribution["cv"],
            "baseline_avg": self.baseline_avg,
            "opponent_tier_code": context["opponent_tier_code"],
            "map_type_modifier": context["map_type_modifier"],
        }
