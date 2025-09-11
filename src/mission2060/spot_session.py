from __future__ import annotations
import logging
import time
from contextlib import AbstractContextManager

import bosdyn.client
from bosdyn.client.robot import Robot
from bosdyn.client.estop import EstopClient, EstopEndpoint, EstopKeepAlive
from bosdyn.client.lease import LeaseClient, LeaseKeepAlive
from bosdyn.client.robot_command import RobotCommandClient, blocking_stand, blocking_sit
from bosdyn.client.image import ImageClient
from bosdyn.client.docking import DockingClient
from bosdyn.client.util import setup_logging

from .config import SpotCredentials

LOG = logging.getLogger("mission2060")

class SpotSession(AbstractContextManager):
    """
    Manages a full Spot control session:
      - SDK init, robot object, auth
      - time sync
      - Estop endpoint + keepalive (allow/stop)
      - Lease keepalive
      - Power on & stand on entry; safe sit & power off on exit
    """

    def __init__(self, creds: SpotCredentials, app_name: str = "MISSION2060"):
        setup_logging()
        self._creds = creds
        self._app_name = app_name

        self.sdk = bosdyn.client.create_standard_sdk(app_name)
        self.robot: Robot = self.sdk.create_robot(creds.host)

        # Authenticate and start time sync.
        # Authenticate if creds provided, then time sync
        if creds.user and creds.password:
            self.robot.authenticate(creds.user, creds.password)
        else:
            LOG.info("No credentials provided — skipping authentication.")
        self.robot.time_sync.wait_for_sync()

        # E-Stop endpoint: single-endpoint config + keepalive. :contentReference[oaicite:4]{index=4}
        self.estop_client = self.robot.ensure_client(EstopClient.default_service_name)
        self.estop_endpoint = EstopEndpoint(self.estop_client, f"{app_name}-estop", estop_timeout=9.0)
        self.estop_endpoint.force_simple_setup()
        self.estop_keepalive = EstopKeepAlive(self.estop_endpoint)
        self.estop_keepalive.allow()  # Allow motor power (E-Stop NONE). :contentReference[oaicite:5]{index=5}

        # Lease keepalive (acquire & retain; return at exit). :contentReference[oaicite:6]{index=6}
        self.lease_client = self.robot.ensure_client(LeaseClient.default_service_name)
        self.lease_keepalive = LeaseKeepAlive(self.lease_client, must_acquire=True, return_at_exit=True)

        # Service clients (created after lease wallet is active to propagate wallet to clients).
        self.command_client: RobotCommandClient = self.robot.ensure_client(RobotCommandClient.default_service_name)
        self.image_client: ImageClient = self.robot.ensure_client(ImageClient.default_service_name)
        self.docking_client: DockingClient = self.robot.ensure_client(DockingClient.default_service_name)

        # Power on & stand. Helpers block until done. :contentReference[oaicite:7]{index=7}
        if not self.robot.is_powered_on():
            LOG.info("Powering on motors...")
            self.robot.power_on(timeout_sec=20)
        LOG.info("Commanding stand...")
        blocking_stand(self.command_client, timeout_sec=10)

    # Context manager support:
    def __enter__(self) -> "SpotSession":
        return self

    def __exit__(self, exc_type, exc, tb):
        self.shutdown()
        # Swallow exceptions here or re-raise depending on your preference
        return False

    def shutdown(self):
        LOG.info("Shutting down: sit, power off, stop keepalives.")
        try:
            blocking_sit(self.command_client, timeout_sec=10)  # :contentReference[oaicite:8]{index=8}
        except Exception as e:
            LOG.warning("Sit failed: %r", e)
        try:
            self.robot.power_off(cut_immediately=False, timeout_sec=20)  # :contentReference[oaicite:9]{index=9}
        except Exception as e:
            LOG.warning("Power off failed: %r", e)
        try:
            self.estop_keepalive.shutdown()  # stop periodic E-Stop check-ins. :contentReference[oaicite:10]{index=10}
        except Exception as e:
            LOG.warning("E-Stop keepalive shutdown failed: %r", e)
        try:
            self.lease_keepalive.shutdown()  # stop lease retain thread. :contentReference[oaicite:11]{index=11}
        except Exception as e:
            LOG.warning("Lease keepalive shutdown failed: %r", e)
