from core.simulator import Simulator


def test_single_lap_finishes_at_lap_length():
    sim = Simulator()
    sim.load_track("Balanced", laps=1, seed=1)

    steps = 0
    while not sim.is_finished and steps < 20000:
        sim.step(1.0, 100.0, 0.0)
        steps += 1

    assert sim.is_finished
    assert sim.lap == 1
    assert abs(sim.distance_m - sim.total_race_distance_m) < 1e-6


def test_multi_lap_wraps_and_increments_lap_counter():
    sim = Simulator()
    sim.load_track("Balanced", laps=3, seed=1)
    lap_length = sim.lap_length_m

    seen_laps = {1}
    steps = 0
    while not sim.is_finished and steps < 60000:
        sim.step(1.0, 200.0, 0.0)
        seen_laps.add(sim.lap)
        steps += 1

    assert sim.is_finished
    assert sim.lap == 3
    assert seen_laps == {1, 2, 3}
    assert abs(sim.distance_m - 3 * lap_length) < 1e-6


def test_distance_remaining_counts_down_to_zero():
    sim = Simulator()
    sim.load_track("Balanced", laps=2, seed=1)
    initial_remaining = sim.distance_remaining_m
    assert abs(initial_remaining - sim.total_race_distance_m) < 1e-6

    steps = 0
    while not sim.is_finished and steps < 40000:
        sim.step(1.0, 150.0, 0.0)
        steps += 1

    assert sim.distance_remaining_m == 0.0


def test_distance_never_exceeds_total_race_distance():
    sim = Simulator()
    sim.load_track("High-speed", laps=1, seed=2)

    steps = 0
    while not sim.is_finished and steps < 20000:
        sim.step(1.0, 350.0, 0.0)
        assert sim.distance_m <= sim.total_race_distance_m + 1e-9
        steps += 1
