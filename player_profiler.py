"""
Advanced Player Profiler for CS2 Prop Grading.

Dimensions:
  1. Role Classification      — Firepower/Entry/Support/IGL based on HLTV buckets
  2. Performance Ceiling      — Peak-to-average ratio (flash-round potential)
  3. Consistency Score        — Coefficient of variation (lower = more stable)
  4. Round Environment Fit    — How player performs in map-length scenarios
  5. Matchup Profile          — Tiers vs Top-5/10/20/50 opponents
  6. Economy Resilience       — Performance on pistol/save/buy rounds
"""

import logging
import statistics as _stats
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class PlayerProfiler:
    """Analyzes player role, consistency, and ceiling potential."""

    # Role classification thresholds (0-100 buckets from HLTV)
    ROLE_THRESHOLDS = {
        "Firepower": 75,       # Attack prowess
        "Entrying": 70,        # Entry frag success
        "Trading": 65,         # Trade follow-up ability
        "Opening": 60,         # First-kill success
        "Clutching": 60,       # 1vX win rate
        "Sniping": 50,         # AWP/long-range efficiency
        "Utility": 55,         # Support/utility impact
    }

    def __init__(self, player_stats: Dict):
        """
        Initialize profiler with player's full stat dict.
        Expected keys: 'name', 'attributes' (bucket dict), 'kill_distribution' (list),
                      'recent_avg', 'per_map_stats', 'vs_tier_ratings'
        """
        self.player_stats = player_stats
        self.name = player_stats.get("name", "Unknown")

    def classify_primary_role(self) -> Tuple[str, Dict]:
        """
        Classify primary role based on HLTV attribute buckets.
        Returns: (role_name, {score, tier, confidence})
        """
        attrs = self.player_stats.get("attributes", {})
        if not attrs:
            return ("Unclassified", {"score": 0, "tier": "N/A", "confidence": 0})

        # Score each bucket
        scores = {k: attrs.get(k, 0) for k in self.ROLE_THRESHOLDS.keys()}
        primary_role = max(scores, key=scores.get)
        primary_score = scores[primary_role]

        # Secondary role (second-highest)
        remaining = {k: v for k, v in scores.items() if k != primary_role}
        secondary_role = max(remaining, key=remaining.get) if remaining else None
        secondary_score = remaining.get(secondary_role, 0) if secondary_role else 0

        # Confidence: margin between primary and secondary
        confidence = min(100, (primary_score - secondary_score + 20))

        tier = self._score_to_tier(primary_score)

        return (
            primary_role,
            {
                "score": primary_score,
                "tier": tier,
                "confidence": confidence,
                "secondary_role": secondary_role,
                "secondary_score": secondary_score,
                "all_scores": scores,
            },
        )

    def compute_consistency_score(self) -> Dict:
        """
        Measure kill distribution volatility using coefficient of variation (CV).
        Lower CV = more consistent; higher CV = more volatile.

        Returns: {'cv': float, 'label': str, 'stability_tier': str}
        """
        kill_dist = self.player_stats.get("kill_distribution", [])
        if not kill_dist or len(kill_dist) < 2:
            return {"cv": None, "label": "Insufficient data", "stability_tier": "N/A"}

        mean_val = _stats.mean(kill_dist)
        if mean_val == 0:
            return {"cv": None, "label": "Zero average", "stability_tier": "N/A"}

        stdev_val = _stats.stdev(kill_dist) if len(kill_dist) >= 2 else 0
        cv = (stdev_val / mean_val) * 100 if mean_val > 0 else 0

        # Classify stability
        if cv < 20:
            stability = "Elite Consistency"
        elif cv < 30:
            stability = "Very Stable"
        elif cv < 40:
            stability = "Stable"
        elif cv < 50:
            stability = "Moderate Variance"
        else:
            stability = "High Volatility"

        return {
            "cv": round(cv, 2),
            "label": stability,
            "stability_tier": stability,
            "sample_size": len(kill_dist),
        }

    def compute_performance_ceiling(self) -> Dict:
        """
        Calculate peak-to-average ratio to identify flash-round potential.
        Ceiling = P90 / Mean

        Returns: {'ceiling_ratio': float, 'peak_kills': int, 'projection': str}
        """
        kill_dist = self.player_stats.get("kill_distribution", [])
        if not kill_dist or len(kill_dist) < 5:
            return {
                "ceiling_ratio": None,
                "peak_kills": None,
                "projection": "Insufficient data",
            }

        sorted_kills = sorted(kill_dist, reverse=True)
        p90_idx = max(0, int(len(sorted_kills) * 0.10))
        p90_val = sorted_kills[p90_idx]
        mean_val = _stats.mean(kill_dist)

        if mean_val == 0:
            return {
                "ceiling_ratio": None,
                "peak_kills": p90_val,
                "projection": "Zero baseline",
            }

        ceiling_ratio = p90_val / mean_val

        return {
            "ceiling_ratio": round(ceiling_ratio, 2),
            "peak_kills": p90_val,
            "p90_projected_kills": round(p90_val, 1),
            "mean_kills": round(mean_val, 1),
            "projection": f"Ceiling: {p90_val}K ({ceiling_ratio:.2f}x baseline)",
        }

    def analyze_matchup_tiers(self) -> Dict:
        """
        Compare player's rating against tier buckets (Top-5, Top-10, Top-20, Top-50).
        Returns performance deltas vs baseline.
        """
        vs_tiers = self.player_stats.get("vs_tier_ratings", {})
        if not vs_tiers:
            return {"tiers": {}, "strongest_vs": None, "weakest_vs": None}

        tiers_data = {}
        for tier_name in ["Top-5", "Top-10", "Top-20", "Top-50"]:
            rating = vs_tiers.get(tier_name, 0)
            tiers_data[tier_name] = {
                "rating": rating,
                "tier_label": self._rating_to_label(rating),
            }

        strongest = max(tiers_data, key=lambda k: tiers_data[k]["rating"])
        weakest = min(tiers_data, key=lambda k: tiers_data[k]["rating"])

        return {
            "tiers": tiers_data,
            "strongest_vs": strongest,
            "weakest_vs": weakest,
            "top5_rating": vs_tiers.get("Top-5"),
        }

    def round_environment_fit(self) -> Dict:
        """
        Analyze how player performs in different round-length scenarios.
        Uses per-map stats to infer short (30-36 rounds), normal (38-42), long (44+).
        """
        per_map = self.player_stats.get("per_map_stats", {})
        if not per_map:
            return {"fit_profile": "No map data", "scenarios": {}}

        scenarios = {"short": [], "normal": [], "long": []}
        for map_name, stats in per_map.items():
            avg_rounds = stats.get("avg_rounds", 0)
            avg_kills = stats.get("avg_kills", 0)

            if avg_rounds <= 36:
                scenarios["short"].append(avg_kills)
            elif avg_rounds <= 42:
                scenarios["normal"].append(avg_kills)
            else:
                scenarios["long"].append(avg_kills)

        result = {}
        for scenario_key in ["short", "normal", "long"]:
            kills_list = scenarios[scenario_key]
            if kills_list:
                result[scenario_key] = {
                    "avg_kills": round(_stats.mean(kills_list), 1),
                    "sample": len(kills_list),
                }
            else:
                result[scenario_key] = {"avg_kills": 0, "sample": 0}

        # Determine best fit
        best_fit = max(
            result, key=lambda k: result[k]["avg_kills"] if result[k]["sample"] > 0 else 0
        )
        return {"scenarios": result, "best_fit": best_fit}

    def full_profile_summary(self) -> Dict:
        """
        Assemble complete player profile into one dict.
        """
        role, role_data = self.classify_primary_role()
        consistency = self.compute_consistency_score()
        ceiling = self.compute_performance_ceiling()
        matchup_tiers = self.analyze_matchup_tiers()
        environment = self.round_environment_fit()

        return {
            "player_name": self.name,
            "role_classification": {"primary_role": role, **role_data},
            "consistency_profile": consistency,
            "performance_ceiling": ceiling,
            "matchup_analysis": matchup_tiers,
            "round_environment_fit": environment,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _score_to_tier(score: int) -> str:
        """Convert 0-100 bucket score to tier label."""
        if score >= 85:
            return "S Tier (Elite)"
        elif score >= 70:
            return "A Tier (Strong)"
        elif score >= 55:
            return "B Tier (Above Average)"
        elif score >= 40:
            return "C Tier (Average)"
        else:
            return "D Tier (Below Average)"

    @staticmethod
    def _rating_to_label(rating: float) -> str:
        """Convert HLTV rating (0-3+) to performance label."""
        if rating >= 1.30:
            return "Elite"
        elif rating >= 1.15:
            return "Strong"
        elif rating >= 1.00:
            return "Above Average"
        elif rating >= 0.85:
            return "Average"
        else:
            return "Below Average"
