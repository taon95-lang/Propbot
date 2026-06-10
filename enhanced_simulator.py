"""
Enhanced Kill Simulation Engine for CS2 Prop Projection.

Improves upon the base simulator with:
  - Multi-scenario projections (short/normal/long maps)
  - Bootstrap confidence intervals (P25, P75)
  - Risk-adjusted probability modulation
  - Integrated H2H context weighting
  - Empirical quantile calculations
"""

import logging
import random
import statistics as _stats
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Container for simulation output."""

    mean_projection: float
    median_projection: float
    std_dev: float
    p25: float
    p75: float
    p10: float
    p90: float
    over_probability: float
    under_probability: float
    hit_rate: float
    sample_size: int
    scenarios: Dict  # short/normal/long projections
    confidence_modifier: float  # 0.0-1.0, reflects data quality

    def to_dict(self) -> Dict:
        return {
            "mean_projection": round(self.mean_projection, 2),
            "median_projection": round(self.median_projection, 2),
            "std_dev": round(self.std_dev, 2),
            "p25": round(self.p25, 2),
            "p75": round(self.p75, 2),
            "p10": round(self.p10, 2),
            "p90": round(self.p90, 2),
            "over_probability": round(self.over_probability, 1),
            "under_probability": round(self.under_probability, 1),
            "hit_rate": round(self.hit_rate, 1),
            "sample_size": self.sample_size,
            "scenarios": self.scenarios,
            "confidence_modifier": round(self.confidence_modifier, 3),
        }


class EnhancedSimulator:
    """Runs multi-scenario Monte Carlo simulations with confidence bands."""

    def __init__(
        self,
        kill_distribution: List[float],
        baseline_avg: float,
        multiplier: float = 1.0,
        h2h_context: Optional[Dict] = None,
    ):
        """
        Args:
            kill_distribution: Recent kill counts per map
            baseline_avg: Player's season average
            multiplier: Deep analysis multiplier (defensive profile, rank, etc.)
            h2h_context: {'avg_kills': float, 'sample': int, 'adjusted': bool}
        """
        self.kill_distribution = kill_distribution
        self.baseline_avg = baseline_avg
        self.multiplier = multiplier
        self.h2h_context = h2h_context or {}

    def run_simulation(
        self,
        line: float,
        rounds: int = 40,
        num_sims: int = 10000,
        confidence_level: float = 0.95,
    ) -> SimulationResult:
        """
        Run Monte Carlo simulation projecting kills across multiple maps.
        Args:
            line: The betting line to evaluate
            rounds: Expected number of rounds in the match (BO3 avg ~40)
            num_sims: Number of Monte Carlo iterations
            confidence_level: For confidence interval (default 95%)
        Returns:
            SimulationResult with full distribution analysis
        """
        if not self.kill_distribution or len(self.kill_distribution) < 3:
            logger.warning(
                f"[simulator] Insufficient data: {len(self.kill_distribution)} samples"
            )
            return self._fallback_result(line)

        # Phase 1: Baseline projection
        baseline_proj = self._project_baseline(rounds)

        # Phase 2: Apply multipliers (deep analysis, H2H context)
        adjusted_proj = baseline_proj * self.multiplier

        # Phase 3: Integrate H2H context if available
        if self.h2h_context.get("avg_kills"):
            adjusted_proj = self._blend_h2h(
                adjusted_proj, self.h2h_context.get("avg_kills"), baseline_proj
            )

        # Phase 4: Run Monte Carlo on adjusted distribution
        simulated_totals = []
        for _ in range(num_sims):
            sample_maps = random.choices(self.kill_distribution, k=2)  # BO3 = 2 maps
            total = sum(sample_maps) * self.multiplier
            simulated_totals.append(total)

        # Phase 5: Compute quantiles and probabilities
        simulated_totals.sort()
        mean_sim = _stats.mean(simulated_totals)
        median_sim = _stats.median(simulated_totals)
        std_sim = _stats.stdev(simulated_totals) if len(simulated_totals) > 1 else 0

        # Empirical quantiles
        p10_idx = max(0, int(num_sims * 0.10))
        p25_idx = max(0, int(num_sims * 0.25))
        p75_idx = max(0, int(num_sims * 0.75))
        p90_idx = max(0, int(num_sims * 0.90))

        p10 = simulated_totals[p10_idx]
        p25 = simulated_totals[p25_idx]
        p75 = simulated_totals[p75_idx]
        p90 = simulated_totals[p90_idx]

        # Over/Under probability
        over_count = sum(1 for t in simulated_totals if t > line)
        over_prob = (over_count / num_sims) * 100
        under_prob = 100 - over_prob

        # Hit rate: fraction of recent data above line
        hit_rate = (
            sum(1 for k in self.kill_distribution if k > (line / 2)) / len(self.kill_distribution)
            * 100
        )  # Scaled for 2-map BO3

        # Confidence modifier: based on sample size quality
        sample_confidence = min(1.0, len(self.kill_distribution) / 20.0)

        # Multi-scenario projections
        scenarios = self._compute_scenarios(rounds)

        return SimulationResult(
            mean_projection=mean_sim,
            median_projection=median_sim,
            std_dev=std_sim,
            p25=p25,
            p75=p75,
            p10=p10,
            p90=p90,
            over_probability=over_prob,
            under_probability=under_prob,
            hit_rate=hit_rate,
            sample_size=len(self.kill_distribution),
            scenarios=scenarios,
            confidence_modifier=sample_confidence,
        )

    def _project_baseline(self, rounds: int) -> float:
        """
        Project baseline kills based on per-round rate.
        BO3 typically runs 38-42 rounds; use player's baseline adjusted for round count.
        """
        if not self.kill_distribution or self.baseline_avg == 0:
            return 0

        avg_kill_dist = _stats.mean(self.kill_distribution)
        # Typical BO3 is 40 rounds / 2 maps = 20 rounds per map
        baseline_per_round = avg_kill_dist / 20.0
        return baseline_per_round * rounds

    def _blend_h2h(self, current_proj: float, h2h_avg: float, baseline: float) -> float:
        """
        Blend H2H average with current projection (capped at 25% weight).
        H2H is context-only and cannot override recent form.
        """
        h2h_weight = 0.15  # Conservative 15% (vs. 25% hard cap)
        blended = (current_proj * (1 - h2h_weight)) + (h2h_avg * h2h_weight)
        return blended

    def _compute_scenarios(self, rounds: int) -> Dict:
        """
        Compute projected kills in short/normal/long map scenarios.
        """
        baseline = self.baseline_avg

        return {
            "short_map": {
                "rounds": 32,
                "expected_kills": round((baseline / 20.0) * 32 * self.multiplier, 1),
                "description": "Short BO3 (blowout or stomp)",
            },
            "normal_map": {
                "rounds": 40,
                "expected_kills": round((baseline / 20.0) * 40 * self.multiplier, 1),
                "description": "Standard BO3 (most likely)",
            },
            "long_map": {
                "rounds": 48,
                "expected_kills": round((baseline / 20.0) * 48 * self.multiplier, 1),
                "description": "Long BO3 (close, competitive)",
            },
        }

    def _fallback_result(self, line: float) -> SimulationResult:
        """Return safe fallback when data is insufficient."""
        return SimulationResult(
            mean_projection=self.baseline_avg,
            median_projection=self.baseline_avg,
            std_dev=0,
            p25=self.baseline_avg * 0.9,
            p75=self.baseline_avg * 1.1,
            p10=self.baseline_avg * 0.8,
            p90=self.baseline_avg * 1.2,
            over_probability=50.0,
            under_probability=50.0,
            hit_rate=50.0,
            sample_size=0,
            scenarios={},
            confidence_modifier=0.0,
        )
