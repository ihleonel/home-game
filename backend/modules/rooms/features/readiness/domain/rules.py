from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessChange:
    value: bool
    changed: bool


def readiness_change(current_value, requested_value):
    """Represent a readiness request without depending on persistence details."""
    return ReadinessChange(requested_value, current_value != requested_value)
