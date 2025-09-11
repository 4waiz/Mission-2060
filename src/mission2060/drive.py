from __future__ import annotations
import time
from typing import Optional

from bosdyn.client.robot_command import RobotCommandBuilder, RobotCommandClient, blocking_stand, blocking_sit

def stand(command_client: RobotCommandClient, timeout: float = 10.0):
    """Stand and wait until standing."""
    blocking_stand(command_client, timeout_sec=timeout)  # :contentReference[oaicite:12]{index=12}

def sit(command_client: RobotCommandClient, timeout: float = 10.0):
    """Sit and wait until sitting."""
    blocking_sit(command_client, timeout_sec=timeout)  # :contentReference[oaicite:13]{index=13}

def stop(command_client: RobotCommandClient):
    """Issue a stop command (minimal motion)."""
    cmd = RobotCommandBuilder.stop_command()  # :contentReference[oaicite:14]{index=14}
    command_client.robot_command(cmd)

def velocity(command_client: RobotCommandClient, end_time_secs: float, vx: float, vy: float, yaw_rate: float):
    """
    Send a body-frame SE2 velocity for a short duration.
    Positive x = forward (m/s), positive y = left (m/s), positive yaw = left/CCW (rad/s).
    The 'end_time_secs' is LOCAL time; the client converts it to robot time using timesync. :contentReference[oaicite:15]{index=15}
    """
    cmd = RobotCommandBuilder.synchro_velocity_command(v_x=vx, v_y=vy, v_rot=yaw_rate)  # :contentReference[oaicite:16]{index=16}
    command_client.robot_command(cmd, end_time_secs=end_time_secs)  # wrapper handles timesync conversion. :contentReference[oaicite:17]{index=17}
