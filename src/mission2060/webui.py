from __future__ import annotations
import asyncio, time
from typing import Dict, List
import numpy as np, cv2

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import load_creds
from .spot_session import SpotSession
from . import drive
from .camera import fetch_bgr, list_sources, DEFAULT_SOURCES
from .docking import dock, undock

app = FastAPI()
app.mount("/ui", StaticFiles(directory="ui"), name="ui")
env = Environment(loader=FileSystemLoader("ui"), autoescape=select_autoescape())

creds = load_creds()
session = SpotSession(creds)  # powers on + stand
image_sources: List[str] = []
primary_source: str = ""
lock = asyncio.Lock()

def choose_sources():
    global image_sources, primary_source
    try:
        names = list_sources(session.image_client)
    except Exception:
        names = DEFAULT_SOURCES[:]
    # prefer Spot CAM if present
    spotcam = [n for n in names if any(k in n.lower() for k in ["spot_cam","pano","spherical","ptz","360"])]
    if spotcam:
        names = spotcam + [n for n in names if n not in spotcam]
    image_sources = names[:]
    primary_source = image_sources[0] if image_sources else ""

choose_sources()

def mjpeg_gen(source: str, quality: int = 60, fps: int = 12):
    period = 1.0 / max(1, fps)
    while True:
        t0 = time.time()
        try:
            bgr = fetch_bgr(session.image_client, source=source, jpeg_quality=quality)
        except Exception:
            bgr = np.zeros((720,960,3), np.uint8)
            cv2.putText(bgr, f"{source} N/A", (20,60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 2)
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        frame = buf.tobytes() if ok else b""
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        yield boundary
        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)

@app.get("/")
async def index():
    tmpl = env.get_template("index.html")
    return HTMLResponse(tmpl.render(
        sources=image_sources[:4],
        primary=primary_source,
        user=creds.user or "guest",
        host=creds.host
    ))

@app.get("/stream/{name}")
async def stream(name: str):
    return StreamingResponse(mjpeg_gen(name), media_type="multipart/x-mixed-replace; boundary=frame")

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            t = data.get("type")
            if t == "velocity":
                vx, vy, yaw, dur = data["vx"], data["vy"], data["yaw"], data.get("dur", 0.3)
                end_time = time.time() + dur
                drive.velocity(session.command_client, end_time, vx=vx, vy=vy, yaw_rate=yaw)
            elif t == "action":
                a = data.get("name")
                if a == "stand": drive.stand(session.command_client)
                elif a == "sit": drive.sit(session.command_client)
                elif a == "estop_cut": session.estop_keepalive.stop()
                elif a == "estop_allow": session.estop_keepalive.allow()
                elif a == "dock": 
                    if creds.dock_id is not None: dock(session.robot, creds.dock_id)
                elif a == "undock": undock(session.robot)
                elif a == "release_lease":
                    session.lease_keepalive.shutdown()
                elif a == "reacquire_lease":
                    from bosdyn.client.lease import LeaseKeepAlive
                    session.lease_keepalive = LeaseKeepAlive(session.lease_client, must_acquire=True, return_at_exit=True)
            elif t == "promote":
                global primary_source
                name = data.get("name")
                if name in image_sources: primary_source = name
            await websocket.send_json({"ok": True})
    except WebSocketDisconnect:
        pass
