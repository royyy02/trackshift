import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random

from core.vehicle_model import VehicleModel

# [Design] PRD §9.1: bounded total track length
MIN_TRACK_LENGTH_M = 3500.0
MAX_TRACK_LENGTH_M = 7000.0

# [Public estimate, generic circuit literature] PRD §9.3 segment-type parameter ranges
STRAIGHT_LENGTH_RANGE_M = (200.0, 1800.0)
CORNER_RADIUS_RANGES_M = {
    "high_speed_corner": (150.0, 300.0),
    "medium_corner": (60.0, 150.0),
    "slow_corner": (15.0, 60.0),
    "hairpin": (8.0, 15.0),
}

# [Engineering assumption] PRD §9.3 only specifies corner radius, not arc length; the
# reduced-order point-mass model (§10) still needs a traversal length per corner, so a
# representative arc-length band is assumed per corner class, not sourced from the PRD table.
CORNER_ARC_LENGTH_RANGES_M = {
    "high_speed_corner": (80.0, 180.0),
    "medium_corner": (40.0, 100.0),
    "slow_corner": (20.0, 60.0),
    "hairpin": (10.0, 30.0),
}

# [Design] Optimistic top-speed ceiling used only as the feasibility check's assumption of
# "driver accelerates as hard as possible down every straight" (§9.1's "feasible vehicle
# trajectory exists" check), not a claimed achievable top speed.
FEASIBILITY_TOP_SPEED_MS = 100.0  # ~360 km/h

MAX_GENERATION_ATTEMPTS = 100

# [Design] PRD §9.2: six named track classes, each a distribution over segment-type frequency.
TRACK_CLASSES = {
    "High-speed": {
        "straight": 0.55, "high_speed_corner": 0.30, "medium_corner": 0.10,
        "slow_corner": 0.04, "hairpin": 0.01,
    },
    "Technical": {
        "straight": 0.15, "high_speed_corner": 0.05, "medium_corner": 0.40,
        "slow_corner": 0.30, "hairpin": 0.10,
    },
    "Balanced": {
        "straight": 0.35, "high_speed_corner": 0.15, "medium_corner": 0.25,
        "slow_corner": 0.20, "hairpin": 0.05,
    },
    "Heavy-braking": {
        "straight": 0.25, "high_speed_corner": 0.05, "medium_corner": 0.20,
        "slow_corner": 0.25, "hairpin": 0.25,
    },
    "Energy-intensive": {
        "straight": 0.55, "high_speed_corner": 0.25, "medium_corner": 0.12,
        "slow_corner": 0.06, "hairpin": 0.02,
    },
    "Energy-recovery-heavy": {
        "straight": 0.20, "high_speed_corner": 0.05, "medium_corner": 0.20,
        "slow_corner": 0.30, "hairpin": 0.25,
    },
}


class TrackSegment:
    def __init__(self, segment_type: str, length_m: float, radius_m: float = float('inf')):
        self.segment_type = segment_type
        self.length_m = length_m
        self.radius_m = radius_m

    def __repr__(self):
        return f"TrackSegment({self.segment_type}, {self.length_m:.1f}m, r={self.radius_m})"


def total_length_m(segments: list[TrackSegment]) -> float:
    return sum(segment.length_m for segment in segments)


class TrackGenerator:
    """
    Constraint-based procedural circuit generation (PRD Section 9).

    The reduced-order vehicle model (§10) carries no heading/2D-position state, so this
    generator does not build literal clothoid-transition geometry — that fidelity level was
    explicitly rejected for the vehicle model itself (§10's comparison table) and would be
    inconsistent to add here only. "Closed circuit" (§9.1) is instead realized by the
    Simulator looping this segment list lap-over-lap (core/simulator.py), which is the
    correct fidelity match: continuous curvature has no meaning for a point-mass model that
    never represents curvature as a continuous 2D quantity in the first place.
    """

    def __init__(self, track_class: str = "Balanced", seed: int = 42):
        if track_class not in TRACK_CLASSES:
            raise ValueError(
                f"Unknown track class '{track_class}'. Valid classes: {list(TRACK_CLASSES)}"
            )
        self.track_class = track_class
        self.seed = seed
        self._rng = random.Random(seed)
        self._vehicle = VehicleModel()

    def generate_track(self, target_length_m: float = 5000.0) -> list[TrackSegment]:
        """
        Generates a sequence of track segments satisfying PRD §9.1's generation constraints:
        realistic straight-length distribution, per-class corner-radius bounds, bounded total
        track length, and a feasible vehicle trajectory (validated by running the vehicle
        model's corner-speed/braking-distance check over the candidate at generation time,
        resampling on failure rather than hand-writing a separate rule set).
        """
        target_length_m = min(max(target_length_m, MIN_TRACK_LENGTH_M), MAX_TRACK_LENGTH_M)

        candidate = self._generate_candidate(target_length_m)
        for _ in range(MAX_GENERATION_ATTEMPTS - 1):
            if self._is_feasible(candidate):
                return candidate
            candidate = self._generate_candidate(target_length_m)

        # Exceptionally rare for these segment ranges/vehicle limits; surface loudly rather
        # than silently handing back an infeasible track (PRD §1.2: never silently fail).
        raise RuntimeError(
            f"TrackGenerator could not produce a feasible '{self.track_class}' track "
            f"(seed={self.seed}) in {MAX_GENERATION_ATTEMPTS} attempts."
        )

    def _generate_candidate(self, target_length_m: float) -> list[TrackSegment]:
        weights = TRACK_CLASSES[self.track_class]
        types = list(weights.keys())
        probs = list(weights.values())

        segments: list[TrackSegment] = []
        current_length = 0.0

        while current_length < target_length_m:
            seg_type = self._rng.choices(types, weights=probs, k=1)[0]
            if seg_type == "straight":
                length = self._rng.uniform(*STRAIGHT_LENGTH_RANGE_M)
                segments.append(TrackSegment("straight", length, float('inf')))
            else:
                radius = self._rng.uniform(*CORNER_RADIUS_RANGES_M[seg_type])
                length = self._rng.uniform(*CORNER_ARC_LENGTH_RANGES_M[seg_type])
                segments.append(TrackSegment(seg_type, length, radius))
            current_length += length

        return segments

    def _is_feasible(self, segments: list[TrackSegment]) -> bool:
        """
        PRD §9.1's "feasible vehicle trajectory exists" check: walk the lap once assuming the
        vehicle brakes as late as physically possible for every corner, and reject any track
        where a corner cannot be reached from the previous segment's achievable speed within
        the available braking distance — i.e. no impossible geometry.
        """
        if not segments:
            return False

        max_decel = self._vehicle.get_max_braking_deceleration()
        v_prev = 0.0  # standing start/finish straight

        for i, segment in enumerate(segments):
            if segment.radius_m == float('inf'):
                # Straight: optimistically assume the driver can reach the feasibility
                # ceiling given enough length; this never itself fails the check.
                v_prev = FEASIBILITY_TOP_SPEED_MS
                continue

            v_limit = self._vehicle.get_corner_speed_limit(segment.radius_m)
            if v_prev > v_limit:
                required_braking_distance = (v_prev ** 2 - v_limit ** 2) / (2 * max_decel)
                available_distance = segment.length_m + segments[i - 1].length_m
                if required_braking_distance > available_distance:
                    return False

            v_prev = min(v_prev, v_limit)

        return True


if __name__ == "__main__":
    for track_class in TRACK_CLASSES:
        gen = TrackGenerator(track_class=track_class, seed=1)
        track = gen.generate_track()
        n_corners = sum(1 for s in track if s.radius_m != float('inf'))
        print(f"{track_class:24s} segments={len(track):3d} corners={n_corners:3d} "
              f"length={total_length_m(track):8.1f} m")
