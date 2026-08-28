import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import random

from core.vehicle_model import VehicleModel

# [Design] PRD §9.1: bounded total track length
MIN_TRACK_LENGTH_M = 3500.0
MAX_TRACK_LENGTH_M = 7000.0

# Corner subdivision count used to walk a curved segment as a polygon (both here, to find
# where a segment list ends up in (x, z) space, and in frontend/app.js's generateTrackPoints,
# to actually draw it). MUST match the frontend's CORNER_STEPS constant -- the closing path is
# solved against exact circular-arc math, so if the two discretizations disagree, the browser
# draws a track with a visible seam even though this module verifies a perfectly closed loop.
CORNER_WALK_STEPS = 64

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

# [Design] Radius used for the two closing-loop corners that bend the track back to the
# start/finish line (see TrackGenerator._generate_closing_path). Chosen from the middle of
# the "medium_corner" band so the closure reads as a normal, regulation-consistent corner
# pair rather than a special case.
CLOSING_CORNER_RADIUS_M = 100.0
CLOSING_CORNER_TYPE = "medium_corner"

# Below this, a computed closing arc/straight is close enough to zero that adding a
# TrackSegment for it would be a degenerate sliver; the pose is close enough to already
# closed that skipping it is a negligible (sub-degree / sub-meter) approximation.
MIN_CLOSING_SEGMENT_LENGTH_M = 0.5

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
    def __init__(self, segment_type: str, length_m: float, radius_m: float = float('inf'),
                 direction: int = 1):
        self.segment_type = segment_type
        self.length_m = length_m
        self.radius_m = radius_m
        # +1 / -1: which way the corner turns. Irrelevant for straights (radius_m == inf).
        # This is real generated data, not a rendering afterthought -- the frontend used to
        # just alternate left/right for every corner it drew, which is exactly why the track
        # never closed into a loop: nothing about that alternation had any relationship to
        # where the track actually needed to end up. Directions are decided here instead, and
        # the closing path (TrackGenerator._generate_closing_path) is solved to match them.
        self.direction = direction

    def __repr__(self):
        return (f"TrackSegment({self.segment_type}, {self.length_m:.1f}m, "
                f"r={self.radius_m}, dir={self.direction})")


def total_length_m(segments: list[TrackSegment]) -> float:
    return sum(segment.length_m for segment in segments)


class TrackGenerator:
    """
    Constraint-based procedural circuit generation (PRD Section 9).

    The reduced-order vehicle model (§10) carries no heading/2D-position state during a race
    -- the Simulator only ever needs 1D distance along this segment list, looped lap-over-lap
    (core/simulator.py), and corner radius for the speed-limit/braking checks. Full continuous
    clothoid-transition curvature was explicitly rejected for the vehicle model itself (§10's
    comparison table), and that's still true here.

    What *is* built here is a real 2D layout (each corner's turn direction, not just its
    radius) and a closing return path back to the start/finish pose (_generate_closing_path),
    so the track the frontend draws is an actual closed loop rather than an open random walk
    that happens to be geometrically consistent while never re-approaching its own start. That
    2D layout is purely a rendering/visualization concern -- the Simulator itself never reads
    `TrackSegment.direction` or any (x, z) position, so this doesn't change the physics.
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
        # The closing path (a couple of corners plus, usually, a connecting straight) adds
        # length on top of the random walk below; generate the walk a bit short of the target
        # so the closed total tends to land near it rather than consistently overshooting.
        outbound_target_m = target_length_m * 0.8

        for _ in range(MAX_GENERATION_ATTEMPTS):
            outbound = self._generate_candidate(outbound_target_m)
            closing = self._generate_closing_path(outbound)
            candidate = outbound + closing
            total = total_length_m(candidate)
            if MIN_TRACK_LENGTH_M <= total <= MAX_TRACK_LENGTH_M and self._is_feasible(candidate):
                return candidate

        # Exceptionally rare for these segment ranges/vehicle limits; surface loudly rather
        # than silently handing back an infeasible track (PRD §1.2: never silently fail).
        raise RuntimeError(
            f"TrackGenerator could not produce a feasible, closed-loop '{self.track_class}' "
            f"track (seed={self.seed}) in {MAX_GENERATION_ATTEMPTS} attempts."
        )

    def _generate_closing_path(self, outbound: list["TrackSegment"]) -> list["TrackSegment"]:
        """
        Computes a real, drivable return path (two corners and, usually, a connecting
        straight) that bends the track from wherever `outbound` ends back to the start line
        (position (0, 0), heading 0) -- so the track drawn by the frontend is an actual closed
        loop instead of an open random walk, and the closure is regulation-consistent track
        (real corners the vehicle model applies its normal speed-limit/braking checks to),
        not just a cosmetic line connecting the ends.

        This is a restricted case of a Dubins path (the classic shortest-path-between-two-poses
        result for a vehicle with a minimum turning radius): only the "same-turn-sense" curve-
        straight-curve family (both corners turning the same way) is used. That family is
        always geometrically valid for any two poses and any radius -- unlike the "opposite-
        sense" family, which only exists when the poses are far enough apart -- so this never
        fails to produce a closure, at the cost of not always being the globally shortest one.
        """
        x0, z0, heading0 = self._walk_end_pose(outbound)
        R = CLOSING_CORNER_RADIUS_M

        best = (float('inf'), 1, 0.0, 0.0, 0.0)
        for direction in (1, -1):
            # Circle a vehicle at (x, z, heading) turning with this `direction` is on (derived
            # by integrating dx/ds=sin(heading(s)), dz/ds=cos(heading(s)) over arc length s).
            def circle_center(x, z, heading, direction=direction):
                return (x + direction * R * math.cos(heading), z - direction * R * math.sin(heading))

            c1x, c1z = circle_center(x0, z0, heading0)
            # Target pose is the start/finish line: (0, 0), heading 0.
            c2x, c2z = circle_center(0.0, 0.0, 0.0)

            dx, dz = c2x - c1x, c2z - c1z
            straight_len = math.hypot(dx, dz)
            # Heading of the connecting tangent: for equal-radius circles turning the same
            # sense, the tangent line is parallel to the center-to-center line.
            tangent_heading = math.atan2(dx, dz) if straight_len > 1e-9 else heading0

            if direction == 1:
                turn1_angle = (tangent_heading - heading0) % (2 * math.pi)
                turn2_angle = (0.0 - tangent_heading) % (2 * math.pi)
            else:
                turn1_angle = (heading0 - tangent_heading) % (2 * math.pi)
                turn2_angle = (tangent_heading - 0.0) % (2 * math.pi)

            total_len = R * turn1_angle + straight_len + R * turn2_angle
            candidate = (total_len, direction, turn1_angle, straight_len, turn2_angle)
            if candidate[0] < best[0]:
                best = candidate

        _, direction, turn1_angle, straight_len, turn2_angle = best

        closing_segments = []
        if R * turn1_angle >= MIN_CLOSING_SEGMENT_LENGTH_M:
            closing_segments.append(
                TrackSegment(CLOSING_CORNER_TYPE, R * turn1_angle, R, direction)
            )
        if straight_len >= MIN_CLOSING_SEGMENT_LENGTH_M:
            closing_segments.append(TrackSegment("straight", straight_len, float('inf')))
        if R * turn2_angle >= MIN_CLOSING_SEGMENT_LENGTH_M:
            closing_segments.append(
                TrackSegment(CLOSING_CORNER_TYPE, R * turn2_angle, R, direction)
            )
        return closing_segments

    @staticmethod
    def _walk_end_pose(segments: list["TrackSegment"]) -> tuple[float, float, float]:
        """Replays the same forward-walk math the frontend uses to draw the track (see
        frontend/app.js's generateTrackPoints) to find where a segment list ends up, in the
        same (x, z, heading) convention the closing-path math above is built on."""
        x, z, heading = 0.0, 0.0, 0.0
        for segment in segments:
            if segment.radius_m == float('inf'):
                x += math.sin(heading) * segment.length_m
                z += math.cos(heading) * segment.length_m
            else:
                theta = segment.length_m / segment.radius_m
                direction = segment.direction
                steps = CORNER_WALK_STEPS
                step_dist = segment.length_m / steps
                for i in range(1, steps + 1):
                    step_heading = heading + direction * theta * (i / steps)
                    x += math.sin(step_heading) * step_dist
                    z += math.cos(step_heading) * step_dist
                heading += direction * theta
        return x, z, heading

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
                direction = self._rng.choice([1, -1])
                segments.append(TrackSegment(seg_type, length, radius, direction))
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
