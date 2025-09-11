from __future__ import annotations
from bosdyn.client.docking import blocking_dock_robot, blocking_undock, get_dock_id
from bosdyn.client.robot import Robot

def dock(robot: Robot, dock_id: int, timeout: float = 30.0):
    """Dock to a known station id (integer). Blocks until done or raises."""
    # blocking helper takes control and docks the robot. :contentReference[oaicite:20]{index=20}
    return blocking_dock_robot(robot, dock_id, timeout=timeout)

def undock(robot: Robot, timeout: float = 20.0):
    """Undock from the current dock. Blocks until done or raises."""
    return blocking_undock(robot, timeout=timeout)  # :contentReference[oaicite:21]{index=21}

def current_dock_id(robot: Robot) -> int | None:
    """Return the dock ID Spot is currently docked at (or None)."""
    return get_dock_id(robot)  # :contentReference[oaicite:22]{index=22}
