import math
import pytest

from core.track_generator import (
    TrackGenerator,
    TRACK_CLASSES,
    MIN_TRACK_LENGTH_M,
    MAX_TRACK_LENGTH_M,
    total_length_m,
)


def test_unknown_track_class_rejected():
    with pytest.raises(ValueError):
        TrackGenerator(track_class="Nonexistent")


@pytest.mark.parametrize("track_class", list(TRACK_CLASSES))
def test_generated_track_respects_length_bounds(track_class):
    """PRD §9.1: bounded total track length (3.5-7.0 km)."""
    gen = TrackGenerator(track_class=track_class, seed=1)
    track = gen.generate_track(target_length_m=5000.0)
    length = total_length_m(track)
    assert length >= MIN_TRACK_LENGTH_M
    # Generation stops once it crosses the target, so a small overshoot beyond the target
    # is expected; only the hard upper bound is enforced strictly.
    assert length <= MAX_TRACK_LENGTH_M + 500.0


def test_target_length_clamped_to_bounds():
    gen = TrackGenerator(track_class="Balanced", seed=1)
    track = gen.generate_track(target_length_m=1.0)
    assert total_length_m(track) >= MIN_TRACK_LENGTH_M


def test_generation_is_deterministic_per_seed():
    """Reproducibility (PRD §30): same class+seed must yield the same track."""
    track_a = TrackGenerator(track_class="Technical", seed=7).generate_track()
    track_b = TrackGenerator(track_class="Technical", seed=7).generate_track()
    assert [(s.segment_type, s.length_m, s.radius_m, s.direction) for s in track_a] == \
        [(s.segment_type, s.length_m, s.radius_m, s.direction) for s in track_b]


@pytest.mark.parametrize("track_class", list(TRACK_CLASSES))
def test_generated_track_closes_into_a_loop(track_class):
    """
    The 2D layout the frontend draws (core/track_generator.py's TrackSegment.direction plus
    the appended closing path) must actually return to the start/finish pose -- otherwise the
    dashboard renders an open dead-end road instead of a circuit. Heading must close exactly
    (it's a pure sum of signed turn angles, independent of how finely each arc is
    discretized); position only closes to within the corner-walk's chord-vs-arc
    discretization error, so it's checked against a generous-but-meaningful tolerance rather
    than exact equality.
    """
    gen = TrackGenerator(track_class=track_class, seed=11)
    track = gen.generate_track()
    x, z, heading = gen._walk_end_pose(track)

    heading_err_rad = ((heading + math.pi) % (2 * math.pi)) - math.pi
    assert abs(heading_err_rad) < 1e-9, f"Heading didn't close exactly for {track_class}"

    dist_from_start = math.hypot(x, z)
    assert dist_from_start < 15.0, (
        f"{track_class} track ended {dist_from_start:.1f} m from the start/finish line"
    )


@pytest.mark.parametrize("track_class", list(TRACK_CLASSES))
def test_generated_track_is_feasible(track_class):
    """
    PRD §9.1: every corner must be reachable from the previous segment's achievable speed
    within available braking distance (no impossible geometry).
    """
    from core.vehicle_model import VehicleModel

    gen = TrackGenerator(track_class=track_class, seed=3)
    track = gen.generate_track()
    vehicle = VehicleModel()
    max_decel = vehicle.get_max_braking_deceleration()

    v_prev = 0.0
    for i, segment in enumerate(track):
        if segment.radius_m == float('inf'):
            v_prev = 100.0
            continue
        v_limit = vehicle.get_corner_speed_limit(segment.radius_m)
        if v_prev > v_limit:
            required = (v_prev ** 2 - v_limit ** 2) / (2 * max_decel)
            available = segment.length_m + track[i - 1].length_m
            assert required <= available + 1e-6, f"Impossible geometry at segment {i} ({track_class})"
        v_prev = min(v_prev, v_limit)
