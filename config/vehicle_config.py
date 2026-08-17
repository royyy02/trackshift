"""
Vehicle configuration parameters based on PRD Section 8.
Values are explicitly categorized as [Official], [Public estimate], [Engineering assumption], or [Derived].
"""

# [Official] FIA 2026 Technical Regulations
MINIMUM_CAR_WEIGHT_KG = 768

# [Engineering assumption] Regulatory minimum + reported industry early-season overweight margin
VEHICLE_MASS_KG = 800

# [Public estimate] Generic public F1 aero literature, adjusted by the regulation-stated ~drag-reduction target
CDA = 0.95 # 0.9-1.0 m^2 equivalent

# [Public estimate] Coefficient of Lift * Area for downforce (F1 cars have high downforce)
CLA = 2.5 # ~2.5-3.0 m^2 equivalent

# [Public estimate] Generic racing-slick tire literature, not Haas-specific
ROLLING_RESISTANCE_COEFFICIENT = 0.0135 # 0.012-0.015

# [Public estimate] Publicly cited typical modern-F1 cornering-g literature
PEAK_LATERAL_ACCELERATION_G = 5.0 # 4.5-5.5 g

# [Public estimate] Publicly cited typical modern-F1 braking-g literature
PEAK_LONGITUDINAL_DECELERATION_G = 5.5 # ~5-6 g
