"""FakeMountClient — in-process stand-in for the real Alpaca mount.

Implements the `device.velocity_controller.MountClient` protocol (just
`method_sync`) enough for tracking tests:

- `scope_speed_move(speed, angle, dur_sec)` → sets a commanded rate that
  decays via a first-order lag plant (τ = 0.348 s, k_dc = 0.996 by
  default) over the next `dur_sec` seconds. After TTL, cmd falls to 0.
- `scope_get_horiz_coord` → integrates state forward to the current time
  and returns `[alt, az_wrapped]` with a synthetic firmware timestamp.

State is advanced lazily on each call using the wall clock (or an
injectable `time_fn`) so tests can drive it deterministically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from device.plant_models import FirstOrderLagModel


def _wrap_pm180(deg: float) -> float:
    return ((deg + 180.0) % 360.0) - 180.0


@dataclass
class FakeMountState:
    # Mount encoder position. `az` is wrapped to [-180, +180). `el` is raw.
    az_wrapped_deg: float = 0.0
    el_deg: float = 0.0
    # Per-axis simulated velocity (deg/s).
    v_az_degs: float = 0.0
    v_el_degs: float = 0.0
    # Active command (0 after TTL expiry).
    cmd_v_az_degs: float = 0.0
    cmd_v_el_degs: float = 0.0
    cmd_expire_t: float = 0.0
    last_advance_t: float = 0.0
    # Book-keeping for tests.
    commands_received: int = 0
    last_cmd: tuple[int, int, int] | None = None


class FakeMountClient:
    """In-memory mount simulator.

    Public methods exposed directly (beyond `method_sync`):
    - `set_position(az_deg, el_deg)` — teleport encoder for test setup.
    - `state` — read-only access to the live `FakeMountState`.
    """

    def __init__(
        self,
        tau_s: float = 0.348,
        k_dc: float = 0.996,
        substep_s: float = 0.05,
        time_fn=time.time,
    ) -> None:
        self._model = FirstOrderLagModel()
        self._model.tau = tau_s
        self._model.k_dc = k_dc
        self._substep_s = float(substep_s)
        self._time_fn = time_fn
        self.state = FakeMountState()
        self.state.last_advance_t = self._time_fn()

    # --------- test helpers ----------

    def set_position(self, az_deg: float = 0.0, el_deg: float = 0.0) -> None:
        self.state.az_wrapped_deg = _wrap_pm180(az_deg)
        self.state.el_deg = float(el_deg)
        self.state.v_az_degs = 0.0
        self.state.v_el_degs = 0.0
        self.state.cmd_v_az_degs = 0.0
        self.state.cmd_v_el_degs = 0.0
        self.state.cmd_expire_t = 0.0
        self.state.last_advance_t = self._time_fn()

    # --------- protocol ----------

    def method_sync(self, method: str, params=None):
        if method == "scope_get_horiz_coord":
            self._advance(self._time_fn())
            return {
                "result": [self.state.el_deg, self.state.az_wrapped_deg],
                "Timestamp": f"{self._time_fn():.6f}",
            }
        if method == "scope_speed_move":
            self._advance(self._time_fn())
            if params is None:
                params = {}
            speed = int(params.get("speed", 0))
            angle = int(params.get("angle", 0))
            dur = int(params.get("dur_sec", 0))
            self.state.commands_received += 1
            self.state.last_cmd = (speed, angle, dur)
            rad = np.radians(angle)
            # Firmware speed→rate ratio is 237 units per °/s (per Phase 1
            # sysid). Sign comes from the angle: 0° = +az, 90° = +el,
            # 180° = −az, 270° = −el.
            rate_total = speed / 237.0
            self.state.cmd_v_az_degs = rate_total * float(np.cos(rad))
            self.state.cmd_v_el_degs = rate_total * float(np.sin(rad))
            self.state.cmd_expire_t = self._time_fn() + dur
            return {"result": None}
        if method == "get_device_state":
            return {"result": {"mount": {"move_type": "none"}}}
        # Anything else is a no-op the fake doesn't need to model.
        return {"result": None}

    # --------- plant simulation ----------

    def _advance(self, t_now: float) -> None:
        """Integrate state forward from last_advance_t to t_now."""
        t = self.state.last_advance_t
        if t_now <= t:
            return
        while t < t_now:
            step = min(self._substep_s, t_now - t)
            cmd_az = self.state.cmd_v_az_degs if t < self.state.cmd_expire_t else 0.0
            cmd_el = self.state.cmd_v_el_degs if t < self.state.cmd_expire_t else 0.0
            v_az_next = self._model.predict_rate(self.state.v_az_degs, cmd_az, step)
            v_el_next = self._model.predict_rate(self.state.v_el_degs, cmd_el, step)
            # Trapezoidal position integration.
            dpos_az = 0.5 * (self.state.v_az_degs + v_az_next) * step
            dpos_el = 0.5 * (self.state.v_el_degs + v_el_next) * step
            new_az = _wrap_pm180(self.state.az_wrapped_deg + dpos_az)
            new_el = self.state.el_deg + dpos_el
            self.state.az_wrapped_deg = new_az
            self.state.el_deg = new_el
            self.state.v_az_degs = v_az_next
            self.state.v_el_degs = v_el_next
            t += step
        self.state.last_advance_t = t_now
