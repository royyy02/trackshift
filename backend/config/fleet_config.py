"""
Fleet configuration for EV delivery vehicles (PRD Section 31).
This config is applied during the EV Fleet scenario run.
"""

# Vehicle Config
VEHICLE_MASS_KG = 300
ICE_POWER_KW = 0.0
CDA = 0.6
CLA = 0.0
PEAK_LATERAL_ACCELERATION_G = 0.8
PEAK_LONGITUDINAL_DECELERATION_G = 0.8

# Regulation / Battery Config
DEPLOYMENT_CURVE = [
    {"speed_kmh": 0, "power_kw": 5.0},
    {"speed_kmh": 40, "power_kw": 5.0},
    {"speed_kmh": 45, "power_kw": 0}
]

LIMITED_POWER_MODE_CURVE = [
    {"speed_kmh": 0, "power_kw": 2.5},
    {"speed_kmh": 30, "power_kw": 2.5},
    {"speed_kmh": 35, "power_kw": 0}
]

ENERGY_STORE_CAP_MJ = 10.0
MAX_MGU_K_DEPLOY_POWER_KW = 5.0
MAX_MGU_K_REGEN_POWER_KW = 2.0
