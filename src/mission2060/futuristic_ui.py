from __future__ import annotations
import sys, time, math
from typing import Dict, List, Optional, Set

import numpy as np
import cv2

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QPixmap, QImage, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QGridLayout, QFrame, QProgressBar
)

# ---- Your existing modules
from .config import load_creds
from .spot_session import SpotSession
from . import drive
from .camera import fetch_bgr, list_sources, DEFAULT_SOURCES
from .docking import dock, undock
from bosdyn.client.robot_state import RobotStateClient   # NEW

NEON = "#00FFD5"
ACCENT = "#14F1FF"
BG = "#0B1321"
FG = "#D8EEFF"

def bgr_to_qpix(bgr: np.ndarray) -> QPixmap:
    if bgr is None or bgr.size == 0:
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        qimg = QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QImage.Format_BGR888)
        return QPixmap.fromImage(qimg)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3*w, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())

def draw_overlay(pix: QPixmap, lines: List[str]) -> QPixmap:
    qp = QPixmap(pix)
    p = QPainter(qp)
    p.setRenderHint(QPainter.Antialiasing, True)
    # translucent background panel
    panel = QColor(8, 18, 32, 120)
    p.fillRect(8, 8, int(qp.width()*0.45), 48, panel)
    pen = QPen(QColor(ACCENT)); pen.setWidth(1)
    p.setPen(pen)
    p.drawRect(8, 8, int(qp.width()*0.45), 48)
    p.setPen(QColor(NEON))
    p.setFont(QFont("Consolas", 10, QFont.DemiBold))
    y = 26
    for s in lines:
        p.drawText(16, y, s)
        y += 16
    p.end()
    return qp

class CameraWorker(QObject):
    """Grabs frames in a thread; emits per-source pixmaps + metrics."""
    frame = Signal(str, QPixmap, float, float)  # name, pix, latency_ms, fps
    sources_ready = Signal(list)

    def __init__(self, session: SpotSession, source_names: List[str], fps: int = 12):
        super().__init__()
        self.session = session
        self.source_names = source_names
        self.fps = fps
        self._running = False
        self._last_ts: Dict[str, float] = {}
        self._fps_ema: Dict[str, float] = {}
        self._alpha = 0.35
        self.primary: Optional[str] = None

    @QtCore.Slot(str)
    def set_primary(self, name: str):
            self.primary = name
    
    @QtCore.Slot()
    def start(self):
        self._running = True
        try:
            names = list_sources(self.session.image_client)
            if names:
                self.source_names = names
        except Exception:
            pass
        self.sources_ready.emit(self.source_names)

        period = 1.0 / max(1, self.fps)
        idx = 0
        while self._running and self.source_names:
            if self.primary:
                name = self.primary
                t0 = time.time()
                try:
                    bgr = fetch_bgr(self.session.image_client, source=name, jpeg_quality=60)
                    latency_ms = (time.time() - t0) * 1000.0
                    now = time.time()
                    if name in self._last_ts:
                        dt = max(1e-6, now - self._last_ts[name]); inst = 1.0/dt
                        self._fps_ema[name] = self._alpha*inst + (1-self._alpha)*self._fps_ema.get(name, inst)
                    self._last_ts[name] = now
                    self.frame.emit(name, bgr_to_qpix(bgr), latency_ms, self._fps_ema.get(name, 0.0))
                except Exception:
                    self.frame.emit(name, bgr_to_qpix(np.zeros((720,960,3),np.uint8)), 0.0, 0.0)
            # 2) update exactly one thumbnail per loop
            name = self.source_names[idx % len(self.source_names)]
            t0 = time.time()
            try:
                bgr = fetch_bgr(self.session.image_client, source=name, jpeg_quality=60)
                latency_ms = (time.time() - t0) * 1000.0
                # FPS per source (EMA)
                now = time.time()
                if name in self._last_ts:
                    dt = max(1e-6, now - self._last_ts[name])
                    inst = 1.0 / dt
                    ema = self._fps_ema.get(name, inst)
                    ema = self._alpha * inst + (1.0 - self._alpha) * ema
                    self._fps_ema[name] = ema
                self._last_ts[name] = now
                fps_val = self._fps_ema.get(name, 0.0)
                self.frame.emit(name, bgr_to_qpix(bgr), latency_ms, fps_val)
            except Exception:
                # emit a labeled blank frame
                h, w = 720, 960
                blk = np.zeros((h, w, 3), dtype=np.uint8)
                cv2.putText(blk, f"{name} N/A", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 100, 100), 2, cv2.LINE_AA)
                self.frame.emit(name, bgr_to_qpix(blk), 0.0, 0.0)
            time.sleep(period)
            idx += 1

    @QtCore.Slot()
    def stop(self):
        self._running = False

class NeonKey(QPushButton):
    def __init__(self, label: str, keycode: int, parent=None):
        super().__init__(label, parent)
        self.keycode = keycode
        self.setCheckable(True)
        self.setFixedSize(64, 64)
        self.setStyleSheet(f"""
            QPushButton {{
                color: {NEON};
                background: rgba(8,18,32,0.8);
                border: 2px solid {NEON};
                border-radius: 10px;
                font: 700 18px 'Consolas';
            }}
            QPushButton:checked {{
                color: {BG};
                background: {NEON};
                border: 2px solid {ACCENT};
            }}
        """)

class DialWidget(QWidget):
    def __init__(self, label="PROCESSING", parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 120)
        self._t = 0.0
        self._label = label
        self.timer = QTimer(self); self.timer.timeout.connect(self._tick); self.timer.start(40)

    def _tick(self): self._t += 0.04; self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        w, h = self.width(), self.height(); cx, cy = w/2, h/2
        pen = QtGui.QPen(QtGui.QColor(NEON)); pen.setWidth(2); p.setPen(pen); p.setBrush(Qt.NoBrush)
        r = min(w, h) * 0.42; p.drawEllipse(QtCore.QPointF(cx, cy), r, r)
        for i in range(36):
            ang = (i*10 + (self._t*180/math.pi)*4) % 360; rad = math.radians(ang)
            x1 = cx + (r-8)*math.cos(rad); y1 = cy + (r-8)*math.sin(rad)
            x2 = cx + (r)*math.cos(rad);   y2 = cy + (r)*math.sin(rad)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
        p.setPen(QtGui.QPen(QtGui.QColor(FG))); p.setFont(QFont("Consolas", 10, QFont.Medium))
        p.drawText(self.rect(), Qt.AlignCenter, self._label)

class FuturisticUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MISSION2060 – Spot Command Console")
        self.resize(1500, 950)
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {BG}; color: {FG}; font: 12px 'Consolas'; }}
            QLabel#title {{ color: {NEON}; font: 700 18px 'Consolas'; }}
            QFrame#line {{ border: 1px solid rgba(20,241,255,0.2); }}
        """)

        creds = load_creds()
        self.creds = creds
        self.session = SpotSession(creds)
        # Robot state client for battery %
        self.state_client: RobotStateClient = self.session.robot.ensure_client(RobotStateClient.default_service_name)

        # ---- Layout
        root = QWidget(); self.setCentralWidget(root)
        root_layout = QVBoxLayout(root); root_layout.setSpacing(8); root_layout.setContentsMargins(12, 12, 12, 12)

        topbar = QHBoxLayout()
        title = QLabel(f"MISSION2060  •  User: {creds.user or 'guest'}  •  Host: {creds.host}"); title.setObjectName("title")
        topbar.addWidget(title); topbar.addStretch(1)
        self.battery = QProgressBar(); self.battery.setFixedWidth(220); self.battery.setRange(0,100); self.battery.setFormat("%p%")
        topbar.addWidget(QLabel("Battery")); topbar.addWidget(self.battery)
        self.estop_label = QLabel("E-STOP: ALLOW"); topbar.addSpacing(10); topbar.addWidget(self.estop_label)
        root_layout.addLayout(topbar)

        self.main_view = QLabel(); self.main_view.setMinimumHeight(420); self.main_view.setAlignment(Qt.AlignCenter)
        self.main_view.setFrameShape(QFrame.StyledPanel)
        self.main_view.setStyleSheet(f"border: 2px solid {NEON}; border-radius: 12px;")
        root_layout.addWidget(self.main_view)

        cams_row = QHBoxLayout(); cams_row.setSpacing(8)
        self.thumb_labels: Dict[str, QLabel] = {}
        for name in ["frontleft_fisheye_image","frontright_fisheye_image","left_fisheye_image","right_fisheye_image"]:
            lbl = QLabel(name); lbl.setAlignment(Qt.AlignCenter)
            lbl.setMinimumSize(320, 200)
            lbl.setFrameShape(QFrame.StyledPanel); lbl.setStyleSheet("border: 1px solid rgba(255,255,255,0.15); border-radius: 8px;")
            lbl.mousePressEvent = self._make_promoter(name)
            self.thumb_labels[name] = lbl
            cams_row.addWidget(lbl)
        root_layout.addLayout(cams_row)

        root_layout.addWidget(self._hline())

        bottom = QHBoxLayout()
        # ---- Key pad
        pad = self._build_keypad(); bottom.addLayout(pad); bottom.addSpacing(20)
        # ---- Actions
        actions = self._build_actions(); bottom.addLayout(actions); bottom.addSpacing(20)
        # ---- Fun dials
        dials = QVBoxLayout(); dials.addWidget(DialWidget("SCANNER ONLINE")); dials.addWidget(DialWidget("FUSION CORE"))
        bottom.addLayout(dials)
        root_layout.addLayout(bottom)

        # Keyboard handling + drive loop
        self.setFocusPolicy(Qt.StrongFocus)
        self.active_keys: Set[int] = set()
        self.speed, self.strafe, self.yaw, self.cmd_duration = 0.6, 0.4, 0.8, 0.4

        self.drive_timer = QTimer(self); self.drive_timer.timeout.connect(self._drive_tick); self.drive_timer.start(50)

        # Battery/status timer – reads real % from RobotStateClient
        self.status_timer = QTimer(self); self.status_timer.timeout.connect(self._status_tick); self.status_timer.start(1500)

        # Camera worker thread
        try:
            names = list_sources(self.session.image_client)
            if not names: names = DEFAULT_SOURCES[:]
        except Exception:
            names = DEFAULT_SOURCES[:]
        spotcam = [n for n in names if any(k in n.lower() for k in ["spot_cam","pano","spherical","ptz","360"])]
        if spotcam:
            names = spotcam + [n for n in names if n not in spotcam]
        self.main_source = names[0]
        self.camera_thread = QtCore.QThread(self)
        self.camera_worker = CameraWorker(self.session, names, fps=8)
        self.camera_worker.moveToThread(self.camera_thread)
        self.camera_worker.frame.connect(self._update_frame)      # now includes metrics
        self.camera_worker.sources_ready.connect(self._set_sources)
        self.camera_thread.started.connect(self.camera_worker.start)
        self.camera_thread.start()

    # ---------- UI helpers ----------
    def _hline(self):
        line = QFrame(); line.setObjectName("line"); line.setFrameShape(QFrame.HLine); return line

    def _make_promoter(self, name: str):
        def on_click(evt): 
            self.main_source = name
            try: self.camera_worker.set_primary(name)
            except Exception: pass
        return on_click

    def _build_keypad(self):
        def neon(label, key): 
            b = NeonKey(label, key); 
            b.pressed.connect(lambda k=key,b=b: self._on_virtual_key(k, True))
            b.released.connect(lambda k=key,b=b: self._on_virtual_key(k, False))
            return b
        lay = QVBoxLayout(); lay.addWidget(QLabel("Manual Drive (WASD + Q/E)"))
        r1 = QHBoxLayout(); r1.addWidget(neon("Q", Qt.Key_Q)); r1.addWidget(neon("W", Qt.Key_W)); r1.addWidget(neon("E", Qt.Key_E)); lay.addLayout(r1)
        r2 = QHBoxLayout(); r2.addWidget(neon("A", Qt.Key_A)); r2.addWidget(neon("S", Qt.Key_S)); r2.addWidget(neon("D", Qt.Key_D)); lay.addLayout(r2)
        return lay

    def _build_actions(self):
        lay = QVBoxLayout()
        def btn(text, fn):
            b = QPushButton(text); b.setCursor(Qt.PointingHandCursor); b.setFixedWidth(220)
            b.setStyleSheet("QPushButton{"+f"border:2px solid {ACCENT};color:{ACCENT};background:rgba(10,25,40,0.8);padding:10px 12px;border-radius:12px;font:700 14px 'Consolas';"+"}"
                            "QPushButton:hover{background:rgba(20,241,255,0.15);} QPushButton:pressed{background:"+ACCENT+";color:"+BG+";}")
            b.clicked.connect(fn); lay.addWidget(b)
        btn("Stand (1)", self.cmd_stand); btn("Sit (2)", self.cmd_sit)
        btn("E-Stop CUT (K)", self.cmd_estop_cut); btn("E-Stop ALLOW (L)", self.cmd_estop_allow)
        btn("Undock (U)", self.cmd_undock); btn("Dock (P)", self.cmd_dock) 
        btn("Release Lease (R)", self.cmd_release_lease)
        btn("Re-acquire Lease (T)", self.cmd_reacquire_lease)
        lay.addStretch(1); return lay

    # ---------- Keyboard ----------
    def keyPressEvent(self, e: QtGui.QKeyEvent):
        if e.isAutoRepeat(): return
        key = e.key()
        # action hotkeys
        if key == Qt.Key_1: self.cmd_stand(); return
        if key == Qt.Key_2: self.cmd_sit(); return
        if key == Qt.Key_K: self.cmd_estop_cut(); return
        if key == Qt.Key_L: self.cmd_estop_allow(); return
        if key == Qt.Key_P: self.cmd_dock(); return
        if key == Qt.Key_U: self.cmd_undock(); return
        if key == Qt.Key_R: self.cmd_release_lease(); return
        if key == Qt.Key_T: self.cmd_reacquire_lease(); return
        self._on_virtual_key(key, True)

    def keyReleaseEvent(self, e: QtGui.QKeyEvent):
        if e.isAutoRepeat(): return
        self._on_virtual_key(e.key(), False)

    def _on_virtual_key(self, keycode: int, down: bool):
        mapping = {Qt.Key_W:"W", Qt.Key_A:"A", Qt.Key_S:"S", Qt.Key_D:"D", Qt.Key_Q:"Q", Qt.Key_E:"E"}
        if down: self.active_keys.add(keycode)
        else: self.active_keys.discard(keycode)

    # ---------- Robot commands ----------
    def _drive_tick(self):
        vx = (self.speed if Qt.Key_W in self.active_keys else 0.0) + (-self.speed if Qt.Key_S in self.active_keys else 0.0)
        vy = (+self.strafe if Qt.Key_A in self.active_keys else 0.0) + (-self.strafe if Qt.Key_D in self.active_keys else 0.0)
        yaw = (+self.yaw if Qt.Key_Q in self.active_keys else 0.0) + (-self.yaw if Qt.Key_E in self.active_keys else 0.0)
        if vx or vy or yaw:
            end_time = time.time() + self.cmd_duration
            drive.velocity(self.session.command_client, end_time, vx=vx, vy=vy, yaw_rate=yaw)

    def cmd_stand(self): drive.stand(self.session.command_client)
    def cmd_sit(self): drive.sit(self.session.command_client)
    def cmd_estop_cut(self): self.session.estop_keepalive.stop(); self.estop_label.setText("E-STOP: CUT")
    def cmd_estop_allow(self): self.session.estop_keepalive.allow(); self.estop_label.setText("E-STOP: ALLOW")
    def cmd_dock(self):
        if self.creds.dock_id is None: self._toast("Set SPOT_DOCK_ID in .env to dock."); return
        dock(self.session.robot, self.creds.dock_id)
    def cmd_undock(self): undock(self.session.robot)
    def cmd_release_lease(self):
        try:
            self.session.lease_keepalive.shutdown()
            self._toast("Lease released")
        except Exception as e:
            self._toast(f"Lease release failed: {e}")
    def cmd_reacquire_lease(self):
        from bosdyn.client.lease import LeaseKeepAlive
        try:
            self.session.lease_keepalive = LeaseKeepAlive(self.session.lease_client, must_acquire=True, return_at_exit=True)
            self._toast("Lease re-acquired")
        except Exception as e:
            self._toast(f"Lease acquire failed: {e}")

    # ---------- Status + camera ----------
    def _status_tick(self):
        try:
            state = self.state_client.get_robot_state()
            # Prefer locomotion battery; fall back to average of packs.
            pct = None
            try:
                pct = state.power_state.locomotion_charge_percentage.value
            except Exception:
                pass
            if pct is None or pct == 0.0:
                vals = [b.charge_percentage.value for b in getattr(state, "battery_states", []) if hasattr(b, "charge_percentage")]
                if vals: pct = sum(vals)/len(vals)
            if pct is not None:
                self.battery.setValue(int(round(pct)))
                self.battery.setFormat(f"{pct:.0f}%")
        except Exception:
            pass

    @QtCore.Slot(str, QPixmap, float, float)
    def _update_frame(self, source: str, pix: QPixmap, latency_ms: float, fps: float):
        lines = [source, f"{latency_ms:.0f} ms  |  {fps:.1f} fps" if fps > 0 else "—"]
        painted = draw_overlay(pix, lines)

        if source == self.main_source:
            self.main_view.setPixmap(painted.scaled(self.main_view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lbl = self.thumb_labels.get(source)
        if lbl:
            lbl.setPixmap(painted.scaled(lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @QtCore.Slot(list)
    def _set_sources(self, names: List[str]):
        # relabel thumbnails if robot has different names
        keys = list(self.thumb_labels.keys())
        for i, name in enumerate(names[:4]):
            lbl = list(self.thumb_labels.values())[i]
            lbl.setToolTip(name)
            lbl.mousePressEvent = self._make_promoter(name)

    def _toast(self, text: str):
        QtWidgets.QToolTip.setFont(QFont("Consolas", 11))
        QtWidgets.QToolTip.showText(self.mapToGlobal(QtCore.QPoint(20,20)), text, self, QtCore.QRect(0,0,200,60), 2000)

    def closeEvent(self, e: QtGui.QCloseEvent):
        try:
            self.camera_worker.stop()
            self.camera_thread.quit(); self.camera_thread.wait(800)
        except Exception:
            pass
        super().closeEvent(e)

def main():
    app = QApplication(sys.argv)
    ui = FuturisticUI(); ui.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
