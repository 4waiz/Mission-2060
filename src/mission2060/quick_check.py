import bosdyn.client
from bosdyn.client.robot_state import RobotStateClient
from src.mission2060.config import load_creds

def main():
    creds = load_creds()
    sdk = bosdyn.client.create_standard_sdk("MISSION2060-quickcheck")
    robot = sdk.create_robot(creds.host)

    if creds.user and creds.password:
        print(f"Authenticating as {creds.user}...")
        robot.authenticate(creds.user, creds.password)
    else:
        print("Connecting without authentication...")

    robot.time_sync.wait_for_sync()
    state_client = robot.ensure_client(RobotStateClient.default_service_name)
    state = state_client.get_robot_state()
    pct = state.power_state.locomotion_charge_percentage.value
    print(f"Connected to Spot @ {creds.host}. Battery ≈ {pct:.1f}%")

if __name__ == "__main__":
    main()
