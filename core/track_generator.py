import random

class TrackSegment:
    def __init__(self, segment_type: str, length_m: float, radius_m: float = float('inf')):
        self.segment_type = segment_type
        self.length_m = length_m
        self.radius_m = radius_m

class TrackGenerator:
    """
    Constraint-based procedural circuit generation (PRD Section 9).
    MVP: Generates a sequence of simple segments to test the vehicle model.
    """
    
    TRACK_CLASSES = {
        "High-speed": {"straight_freq": 0.6, "slow_freq": 0.1},
        "Technical": {"straight_freq": 0.2, "slow_freq": 0.5},
        "Balanced": {"straight_freq": 0.4, "slow_freq": 0.3}
    }
    
    def __init__(self, track_class: str = "Balanced", seed: int = 42):
        self.track_class = track_class
        self.seed = seed
        random.seed(seed)
        
    def generate_track(self, target_length_m: float = 5000.0) -> list[TrackSegment]:
        """Generates a simplified sequence of track segments."""
        segments = []
        current_length = 0.0
        
        # Ensure we have at least one straight and one corner for testing
        segments.append(TrackSegment("Straight", 1000.0, float('inf')))
        current_length += 1000.0
        
        segments.append(TrackSegment("Slow corner", 100.0, 30.0))
        current_length += 100.0
        
        # Pad the rest with a generic mix
        while current_length < target_length_m:
            if random.random() < self.TRACK_CLASSES.get(self.track_class, {}).get("straight_freq", 0.5):
                length = random.uniform(200, 1000)
                segments.append(TrackSegment("Straight", length, float('inf')))
                current_length += length
            else:
                length = random.uniform(50, 150)
                radius = random.uniform(30, 150)
                segments.append(TrackSegment("Medium corner", length, radius))
                current_length += length
                
        return segments
