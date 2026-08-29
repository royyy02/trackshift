# pyrefly: ignore [missing-import]
from fastapi.testclient import TestClient

import dashboard_server
import config.vehicle_config as vehicle_config
import config.regulation_config as regulation_config


def _reset_to_f1_mode(client: TestClient):
    """
    Drives config back to F1 defaults through the app's own 'set_mode' websocket path --
    deliberately not a hand-maintained list of fields to restore. set_mode's fleet branch
    mutates ~10 module-level config attributes (vehicle_config.*, regulation_config.*); an
    earlier version of this file restored only 2 of them in a test's own cleanup and left the
    rest (e.g. regulation_config.ENERGY_STORE_CAP_MJ) leaked as fleet values for every test that
    ran afterward in the same process -- exactly the "two implementations of the same reset
    drift apart" bug pattern this whole test file exists to catch, just in the test's own
    cleanup code instead of the app. Going back through the real code path can't drift from
    itself.
    """
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"command": "set_mode", "mode": "f1"})


def test_set_mode_round_trip_restores_correct_f1_vehicle_config():
    """
    Regression guard: dashboard_server's websocket 'set_mode' handler used to hardcode the
    wrong F1-restore values (CDA=1.0, CLA=4.5) instead of vehicle_config.py's actual documented
    defaults (0.95, 2.5) -- so toggling to Fleet mode and back permanently corrupted the F1
    car's aero parameters for the rest of the server's life, with nothing catching it: no test
    previously exercised the websocket handler at all, only the core physics/optimizer modules
    in isolation.
    """
    client = TestClient(dashboard_server.app)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # initial "Connected. Ready to start." status message

            ws.send_json({"command": "set_mode", "mode": "fleet"})
            ws.send_json({"command": "set_mode", "mode": "f1"})

        assert vehicle_config.CDA == 0.95, f"CDA restored to {vehicle_config.CDA}, expected 0.95"
        assert vehicle_config.CLA == 2.5, f"CLA restored to {vehicle_config.CLA}, expected 2.5"
        assert regulation_config.ENERGY_STORE_CAP_MJ == 4.0
    finally:
        # This test mutates module-level config shared with every other test in the process --
        # always leave it as found, even if an assertion above failed.
        _reset_to_f1_mode(client)


def test_set_mode_fleet_applies_fleet_config():
    """Sanity check the other direction: switching *into* fleet mode actually changes the
    live vehicle config, so the round-trip test above is exercising a real transition and not
    silently no-op'ing."""
    client = TestClient(dashboard_server.app)
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"command": "set_mode", "mode": "fleet"})

        assert vehicle_config.VEHICLE_MASS_KG == 300
        assert vehicle_config.CDA == 0.6
        assert regulation_config.ENERGY_STORE_CAP_MJ == 10.0
    finally:
        _reset_to_f1_mode(client)
