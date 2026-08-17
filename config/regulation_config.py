"""
Regulation configuration, based on PRD Section 2.1.
Single source of truth consumed by the vehicle/battery model and the optimizer's constraint set.
"""

# [Official] 2026 Technical Regulations
FIA_REGULATION_VERSION = "2026 Technical Regulations, as amended 2026-08-05"

MAX_MGU_K_DEPLOY_POWER_KW = 350 # baseline race deployment cap
MAX_MGU_K_REGEN_POWER_KW = 350 # baseline race regen cap
MAX_ENERGY_RECOVERY_MJ_LAP = {"default": 8.5, "min_event": 5.0, "max_event": 9.0}
ENERGY_STORE_CAP_MJ = 4.0 # max usable battery energy at any time

DEPLOYMENT_CURVE = [ # speed (km/h) -> max deploy power (kW)
    {"speed_kmh": 0, "power_kw": 250},
    {"speed_kmh": 290, "power_kw": 350},
    {"speed_kmh": 355, "power_kw": 0}
]

LIMITED_POWER_MODE_CURVE = [ # optional per-event "limited power" mode
    {"speed_kmh": 0, "power_kw": 250},
    {"speed_kmh": 310, "power_kw": 250},
    {"speed_kmh": 340, "power_kw": 100},
    {"speed_kmh": 345, "power_kw": 0}
]

DEPLOYMENT_ZONING = {"acceleration_zones_kw": 350, "elsewhere_kw": 250}
OVERRIDE_ASSIST_MJ = 0.5 # following-car override, <1s gap
BOOST_MAX_POWER_KW = 150 # incremental boost cap (race), per §2.4
