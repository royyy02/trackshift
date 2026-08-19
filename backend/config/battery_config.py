"""
Battery configuration parameters based on PRD Section 8 & 11.
Values are explicitly categorized as [Official], [Public estimate], [Engineering assumption], or [Derived].
"""

from config.regulation_config import ENERGY_STORE_CAP_MJ

# [Official] Regulation is itself the constraint
BATTERY_USABLE_CAPACITY_MJ = ENERGY_STORE_CAP_MJ

# [Engineering assumption] Generic li-ion/motor-inverter efficiency literature (MVP version)
DRIVE_REGEN_ROUND_TRIP_EFFICIENCY = 0.90 # 90% flat for MVP
