from core.optimizer import MPCOptimizer

class OracleOptimizer(MPCOptimizer):
    """
    Offline optimizer with full future knowledge (PRD Section 18).
    For MVP purposes, this acts as an MPC optimizer with a track-length horizon 
    and 0 uncertainty in the forecast.
    """
    def __init__(self, simulator, forecaster, full_track_steps: int = 100):
        super().__init__(simulator, forecaster, horizon_steps=full_track_steps)
        
    def get_action(self, simulator_state, dt_s=1.0) -> tuple[float, float]:
        """
        Oracle intercepts the prediction to force uncertainty to 0.
        """
        # Save original function
        original_predict = self.forecaster.predict_energy_required
        
        def oracle_predict(horizon_m):
            e_req, sig_e = original_predict(horizon_m)
            # Oracle has no uncertainty
            return e_req, 0.0
            
        # Patch momentarily
        self.forecaster.predict_energy_required = oracle_predict
        
        try:
            # Run MPC with large horizon and 0 uncertainty
            action = super().get_action(simulator_state, dt_s)
        finally:
            # Restore
            self.forecaster.predict_energy_required = original_predict
            
        return action
