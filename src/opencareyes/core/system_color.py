"""Retire app-owned Gamma changes while Windows manages screen colour.

The compatibility surface lets display transactions keep controlling dimming.
It never reads or writes Gamma ramps, starts workers, or changes Night Light.
``current_temperature`` is a legacy neutral value, not a system measurement.
"""


class SystemManagedColor:
    managed_by_windows = True
    enabled = False
    current_temperature = 6500
    hdr_active = False
    capability_verified = False
    pending = False
    last_error_code = ""
    last_error_message = ""

    def enable(self, temperature: int = 6500) -> bool:
        return False

    def set_temperature(self, temperature: int) -> bool:
        return False

    def disable(self) -> bool:
        return True

    def refresh_screens(self, *_args) -> bool:
        return True

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        return True
