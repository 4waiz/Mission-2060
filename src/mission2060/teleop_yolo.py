from __future__ import annotations
import argparse
import logging
import time
import cv2
import numpy as np
from .config import load_creds
from .spot_session import SpotSession
from . import drive
from .camera import fetch_bgr, list_sources, DEFAULT_SOURCES
from .docking import dock, undock, current_dock_id

LOG = logging.getLogger("mission2060.teleop")

def overlay_hud(img: np.ndarray, lines: list[str]) -> np.ndarray:
    y = 24
    for s in lines:
        cv2.putText(img, s, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv2.LINE_AA)
        y += 22
    return img

def main():
    parser = argparse.ArgumentParser(description="MISSION2060 teleop with camera and optional YOLO.")
    parser.add_argument("--speed", type=float, default=0.6, help="linear speed m/s")
    parser.add_argument("--strafe", type=float, default=0.4, help="strafe speed m/s")
    parser.add_argument("--yaw", type=float, default=0.8, help="yaw rate rad/s")
    parser.add_argument("--cmd-dur", type=float, default=0.5, help="velocity command duration seconds")
    parser.add_argument("--no-yolo", action="store_true", help="disable YOLO detection overlay")
    parser.add_argument("--source", default="frontleft_fisheye_image", help="starting image source")
    args = parser.parse_args()

    creds = load_creds()
    logging.basicConfig(level=logging.INFO)

    model = None 
    yolo_on = False 
    if not args.no_yolo: 
        try: 
            from ultralytics import YOLO 
            model = YOLO("yolov8n.pt") 
            yolo_on = True 
        except Exception as e: 
            LOG.warning("YOLO disabled (%r)", e)

    with SpotSession(creds) as session:
        # Gather image sources and choose one
        try:
            sources = list_sources(session.image_client)
        except Exception:
            sources = DEFAULT_SOURCES[:]  # fallback known names
        if args.source in sources:
            idx = sources.index(args.source)
        else:
            idx = 0
        source = sources[idx]

        print("\nControls:")
        print("  WASD = move, Q/E = rotate, SPACE = stop")
        print("  1 = stand, 2 = sit")
        print("  K = E-Stop CUT, L = allow power, O = power off/exit")
        print("  U = undock, P = dock (needs SPOT_DOCK_ID in .env)")
        print("  C = cycle camera, Y = toggle YOLO, Esc/X = exit\n")

        while True:
            # Fetch an image for the GUI
            frame = None
            try:
                frame = fetch_bgr(session.image_client, source=source, jpeg_quality=80)
            except Exception as e:
                LOG.warning("Image fetch failed from '%s': %r", source, e)
                frame = np.zeros((720, 960, 3), dtype=np.uint8)

            disp = frame.copy()

            # YOLO overlay
            if yolo_on and disp is not None:
                try:
                    # YOLO expects RGB; convert BGR->RGB
                    results = model.predict(cv2.cvtColor(disp, cv2.COLOR_BGR2RGB), verbose=False)
                    disp = results[0].plot()  # returns BGR visualization
                except Exception as e:
                    LOG.warning("YOLO inference failed: %r", e)
                    yolo_on = False

            # HUD
            docked_id = None
            try:
                docked_id = current_dock_id(session.robot)
            except Exception:
                pass

            lines = [
                f"Source: {source}   |   YOLO: {'ON' if yolo_on else 'OFF'}",
                "W/S=Fwd/Back  A/D=Left/Right  Q/E=Rotate  SPACE=Stop",
                "1=Stand  2=Sit   K=E‑Stop CUT  L=Allow  O=PowerOff/Exit",
                f"U=Undock  P=Dock  (DockId={creds.dock_id if creds.dock_id is not None else 'unset'}; Current={docked_id})",
                "C=Next camera  Y=Toggle YOLO  Esc/X=Exit",
            ]
            disp = overlay_hud(disp, lines)

            cv2.imshow("MISSION2060 – Spot Teleop", disp)
            key = cv2.waitKey(1) & 0xFF

            now = time.time()
            end_time = now + float(args.cmd_dur)

            if key == ord('w'):
                drive.velocity(session.command_client, end_time, vx=args.speed,  vy=0.0,            yaw_rate=0.0)
            elif key == ord('s'):
                drive.velocity(session.command_client, end_time, vx=-args.speed, vy=0.0,            yaw_rate=0.0)
            elif key == ord('a'):
                drive.velocity(session.command_client, end_time, vx=0.0,        vy=+args.strafe,   yaw_rate=0.0)
            elif key == ord('d'):
                drive.velocity(session.command_client, end_time, vx=0.0,        vy=-args.strafe,   yaw_rate=0.0)
            elif key == ord('q'):
                drive.velocity(session.command_client, end_time, vx=0.0,        vy=0.0,            yaw_rate=+args.yaw)
            elif key == ord('e'):
                drive.velocity(session.command_client, end_time, vx=0.0,        vy=0.0,            yaw_rate=-args.yaw)
            elif key == 32:  # SPACE
                drive.stop(session.command_client)
            elif key == ord('1'):
                drive.stand(session.command_client)
            elif key == ord('2'):
                drive.sit(session.command_client)
            elif key == ord('k'):
                # E-Stop CUT (motors off immediately). :contentReference[oaicite:23]{index=23}
                session.estop_keepalive.stop()
            elif key == ord('l'):
                # Allow motors on (NONE level). :contentReference[oaicite:24]{index=24}
                session.estop_keepalive.allow()
            elif key == ord('o'):
                # Safe exit path
                cv2.destroyAllWindows()
                break
            elif key == ord('u'):
                try:
                    undock(session.robot)
                except Exception as e:
                    LOG.error("Undock failed: %r", e)
            elif key == ord('p'):
                if creds.dock_id is None:
                    LOG.error("Set SPOT_DOCK_ID in .env before docking.")
                else:
                    try:
                        dock(session.robot, creds.dock_id)
                    except Exception as e:
                        LOG.error("Dock failed: %r", e)
            elif key == ord('c'):
                idx = (sources.index(source) + 1) % len(sources)
                source = sources[idx]
            elif key == ord('y'):
                yolo_on = not yolo_on
                if yolo_on and model is None:
                    try:
                        model = YOLO("yolov8n.pt")
                    except Exception as e:
                        yolo_on = False
                        LOG.error("Failed to load YOLO: %r", e)
            elif key in (27, ord('x')):  # ESC or X
                cv2.destroyAllWindows()
                break

if __name__ == "__main__":
    main()
