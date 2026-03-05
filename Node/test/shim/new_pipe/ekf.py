# Match fused_kf_estimate.m from Anirban

import numpy as np

np.set_printoptions(precision=3, suppress=True)


class EKFTracker:
    """Extended Kalman Filter Tracker with nonlinear measurement functions"""
    
    def __init__(self, state_transition_model, measurement_model, process_noise, 
                 measurement_noise, initial_state, initial_covariance, 
                 measurement_functions=None, measurement_jacobian=None):
        """
        Initialize the EKF Tracker.
        
        Args:
            state_transition_model: State transition matrix (A) n x n
            measurement_model: Linear measurement model matrix (H) m x n, or None if using nonlinear functions
            process_noise: Process noise covariance (Q) n x n
            measurement_noise: Measurement noise covariance (R) m x m
            initial_state: Initial state vector (n x 1)
            initial_covariance: Initial state covariance matrix (P) n x n
            measurement_functions: List of m functions, each takes state vector and returns scalar measurement
            measurement_jacobian: Function that takes state vector and returns Jacobian matrix (m x n)
                                 If None, jacobian computed numerically
        """
        self.state_transition_model = state_transition_model
        self.A = state_transition_model(0)  # n x n - state transition depends on the time step
        self.H = measurement_model       # m x n (used if measurement_functions is None)
        self.Q = process_noise           # n x n
        self.R = measurement_noise       # m x m
        self.state = initial_state.copy()  # n x 1
        self.P = initial_covariance.copy() # n x n
        
        # Nonlinear measurement model
        self.measurement_functions = measurement_functions  # List of m functions
        self.measurement_jacobian = measurement_jacobian    # Function returning m x n Jacobian
        
        self.is_linear = (measurement_functions is None)
    
    def _compute_measurement_jacobian(self, state):
        """Compute measurement Jacobian numerically using finite differences."""
        if self.measurement_jacobian is not None:
            return self.measurement_jacobian(state)
        
        # Numerical differentiation
        epsilon = 1e-8
        n = len(state)
        m = len(self.measurement_functions)
        H_k = np.zeros((m, n))
        
        measurement_at_state = np.array([f(state) for f in self.measurement_functions])
        
        for j in range(n):
            state_plus = state.copy()
            state_plus[j] += epsilon
            measurement_plus = np.array([f(state_plus) for f in self.measurement_functions])
            H_k[:, j] = (measurement_plus - measurement_at_state) / epsilon
        
        return H_k
    
    def _evaluate_measurements(self, state):
        """Evaluate nonlinear measurement functions at given state."""
        return np.array([f(state) for f in self.measurement_functions])
    
    def predict(self, dt):
        """Predict step: propagate state and covariance forward in time."""
        if callable(self.state_transition_model):
            self.A = self.state_transition_model(dt)
        self.state = self.A @ self.state
        self.P = self.A @ self.P @ self.A.T + self.Q

    
    def update(self, measurement):
        """
        Update step: correct state and covariance with measurement.
        Handles both linear and nonlinear measurement models.
        
        Args:
            measurement: Measurement vector (m x 1)
        """
        if self.is_linear:
            # Linear case: use H directly
            H_k = self.H
            predicted_measurement = H_k @ self.state
        else:
            # Nonlinear case: relinearize around current state
            H_k = self._compute_measurement_jacobian(self.state)
            predicted_measurement = self._evaluate_measurements(self.state)
        
        # Measurement residual
        measurement_residual = measurement - predicted_measurement
        
        # Innovation covariance
        S = H_k @ self.P @ H_k.T + self.R
        
        # Kalman gain
        K = self.P @ H_k.T @ np.linalg.pinv(S)
        
        # Update state
        self.state = self.state + (K @ measurement_residual)
        
        # Update covariance
        n = len(self.state)
        self.P = (np.eye(n) - K @ H_k) @ self.P
    
    def process(self,measurement,dt):
        self.predict(dt)
        self.update(measurement)

        return self.get_state()

    def get_state(self):
        """Return current state estimate."""
        return self.state.copy()
    
    def get_covariance(self):
        """Return current state covariance matrix."""
        return self.P.copy()
    



# ============================== Range Doppler Velocity EKF ============================


#handles range, doppler velocity, and angle measurements to estimate x, y, vx, and vy
def rda_measurement_functions():
    """
    Return measurement functions that convert from Range, Doppler, Angle to [x, y, vx, vy].
    
    State: [x, v_x, y, v_y]
    Measurements: [range, doppler_velocity, angle]
    
    Returns:
        List of 3 measurement functions
    """
    def range_meas(state):
        x, vx, y, vy = state
        return np.sqrt(x**2 + y**2)
    
    def doppler_meas(state):
        x, vx, y, vy = state
        r = np.sqrt(x**2 + y**2)
        if r < 1e-8:
            return 0.0
        # Doppler = radial velocity = (v · r_hat)
        # = (vx * x + vy * y) / r
        return (vx * x + vy * y) / r
    
    def angle_meas(state):
        x, vx, y, vy = state
        return np.arctan2(y, x)
    
    return [range_meas, doppler_meas, angle_meas]


def rda_measurement_jacobian():
    """
    Return Jacobian function for RDA measurements.
    
    H_k = ∂h/∂x where h = [range, doppler, angle]
    
    Returns:
        Function that computes 3x4 Jacobian matrix
    """
    def jacobian(state):
        x, vx, y, vy = state
        r = np.sqrt(x**2 + y**2)
        r_squared = r**2
        
        # Avoid singularity at origin
        if r < 1e-8:
            r = 1e-8
            r_squared = r**2
        
        H = np.zeros((3, 4))
        
        # Row 0: ∂range/∂state
        # range = sqrt(x^2 + y^2)
        H[0, 0] = x / r           # ∂range/∂x
        H[0, 1] = 0               # ∂range/∂vx
        H[0, 2] = y / r           # ∂range/∂y
        H[0, 3] = 0               # ∂range/∂vy
        
        # Row 1: ∂doppler/∂state
        # doppler = (vx*x + vy*y) / r
        numerator = vx * x + vy * y
        H[1, 0] = (vx * r - numerator * (x / r)) / r_squared      # ∂doppler/∂x
        H[1, 1] = x / r                                            # ∂doppler/∂vx
        H[1, 2] = (vy * r - numerator * (y / r)) / r_squared      # ∂doppler/∂y
        H[1, 3] = y / r                                            # ∂doppler/∂vy
        
        # Row 2: ∂angle/∂state
        # angle = arctan2(y, x)
        H[2, 0] = -y / r_squared   # ∂angle/∂x
        H[2, 1] = 0                # ∂angle/∂vx
        H[2, 2] = x / r_squared    # ∂angle/∂y
        H[2, 3] = 0                # ∂angle/∂vy
        
        return H
    
    return jacobian



def cartesian_to_rda(x, y, vx, vy):
    """
    Convert Cartesian state components to [range, doppler, angle].

    Args:
        x, y: position (m)
        vx, vy: velocity (m/s)

    Returns:
        np.array([range, doppler, angle])
    """
    r = np.hypot(x, y)
    angle = np.arctan2(y, x)

    if r < 1e-8:
        doppler = 0.0
    else:
        # radial velocity
        doppler = (vx * x + vy * y) / r

    return np.array([r, doppler, angle])


def rda_to_cartesian(range_meas, doppler_meas, angle_meas):
    """
    Convert Range-Doppler-Angle measurements to Cartesian state.
    
    Args:
        range_meas: Range in meters
        doppler_meas: Radial velocity (doppler velocity) in m/s
        angle_meas: Bearing angle in radians
        
    Returns:
        State vector [x, vx, y, vy]
    """
    # Convert polar to Cartesian position
    x = range_meas * np.cos(angle_meas)
    y = range_meas * np.sin(angle_meas)
    
    # Doppler is radial velocity along the range direction
    # v_radial = (vx * cos(angle) + vy * sin(angle))
    # We need to decompose this into vx and vy components
    # Assuming object is moving radially outward (or directly away):
    # vx = doppler_meas * cos(angle)
    # vy = doppler_meas * sin(angle)
    vx = doppler_meas * np.cos(angle_meas)
    vy = doppler_meas * np.sin(angle_meas)
    
    return np.array([x, vx, y, vy])


def default_rda_EKF(initial_state=None,
                    initial_covariance=None,
                    process_noise=None,
                    meas_funcs=None,
                    meas_jacobian=None,
                    measurement_noise=None):
    """
    Create an EKF tracker for Range-Doppler-Angle measurements.
    Converts RDA measurements to Cartesian state [x, vx, y, vy].
    """
    def state_transition_model(dt):
        return np.array([
            [1.0, dt, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, dt],
            [0.0, 0.0, 0.0, 1.0],
        ])

    if initial_state is None:
        initial_state = np.zeros(4)
    if initial_covariance is None:
        initial_covariance = np.eye(4)
    if process_noise is None:
        process_noise = 0.1 * np.eye(4)
    if meas_funcs is None:
        meas_funcs = rda_measurement_functions()
    if meas_jacobian is None:
        meas_jacobian = rda_measurement_jacobian()
    if measurement_noise is None:
        measurement_noise = np.array([ [0.1,  0.0,  0.0],         # range noise variance
            [0.0, 0.18,  0.0],         # doppler noise variance
            [0.0,  0.0, (np.pi/4)**2], # angle noise variance
        ])

    tracker = EKFTracker(
        state_transition_model=state_transition_model,
        measurement_model=None,
        process_noise=process_noise,
        measurement_noise=measurement_noise,
        initial_state=initial_state,
        initial_covariance=initial_covariance,
        measurement_functions=meas_funcs,
        measurement_jacobian=meas_jacobian
    )
    return tracker


def main():
    dt = 1.0

    measurements = np.array([
        [5.0, 4.5, 0.03],
        [9.5, 4.6, 0.03],
        [14.8, 5.4, 0.028],
        [18.3, 3.5, 0.027],
        [22.6, 4.4, 0.031],
    ])

    # Initialize from first measurement for easier startup
    init_state = rda_to_cartesian(*measurements[0])
    tracker = default_rda_EKF(initial_state=init_state)

    print("=" * 60)
    print("Range-Doppler-Angle EKF Tracker")
    print("=" * 60)
    print(f"Initial state from first measurement: {tracker.get_state()}")

    # Process remaining measurements
    for k, measurement in enumerate(measurements[1:], start=2):
        est_state = tracker.process(measurement, dt)
        filtered_measurement = cartesian_to_rda(*est_state)
        print(f"\nTimestep k={k}")
        print(f"RDA Measurement: range={measurement[0]:.3f}m, doppler={measurement[1]:.3f}m/s, angle={measurement[2]:.4f}rad")
        print(f"RDA Filtered Measurement: range={filtered_measurement[0]:.3f}m, doppler={filtered_measurement[1]:.3f}m/s, angle={filtered_measurement[2]:.4f}rad")

        print(f"Estimated State: x={est_state[0]:.3f}m, vx={est_state[1]:.3f}m/s, y={est_state[2]:.3f}m, vy={est_state[3]:.3f}m/s")

# ...existing code...

if __name__ == "__main__":
    main()