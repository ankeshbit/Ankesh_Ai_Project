import sys
import math
import random
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QFrame, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QPainterPath

class NovaCoreWidget(QWidget):
    """Movie-accurate holographic AI core visualizer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 400)
        
        self.status = "IDLE"
        self.angle_outer = 0.0
        self.angle_inner = 0.0
        
        self.pulse = 0.0
        self.pulse_dir = 1
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(16)  # ~60 FPS

    def set_status(self, status: str):
        self.status = status.upper()

    def update_animation(self):
        # Rotation speeds based on state
        speed_multiplier = 1.0
        if self.status in ["LISTENING", "PROCESSING"]:
            speed_multiplier = 3.0
        elif self.status == "SPEAKING":
            speed_multiplier = 1.5

        self.angle_outer = (self.angle_outer + 1.5 * speed_multiplier) % 360
        self.angle_inner = (self.angle_inner - 2.5 * speed_multiplier) % 360
        
        # Pulse amplitude
        if self.status == "SPEAKING":
            # Erratic pulse for speaking
            self.pulse = random.uniform(0.5, 1.0)
        else:
            # Smooth breathing pulse for idle/listening
            self.pulse += 0.02 * speed_multiplier * self.pulse_dir
            if self.pulse >= 1.0:
                self.pulse = 1.0
                self.pulse_dir = -1
            elif self.pulse <= 0.2:
                self.pulse = 0.2
                self.pulse_dir = 1
                
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Center and sizing
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = min(cx, cy) - 40

        # Colors based on state
        if self.status == "LISTENING":
            base_color = QColor(0, 100, 255)  # Electric Blue
            glow_color = QColor(0, 150, 255, 100)
        elif self.status == "PROCESSING":
            base_color = QColor(255, 150, 0)  # Orange/Amber
            glow_color = QColor(255, 200, 0, 100)
        else:
            base_color = QColor(0, 255, 255)  # Cyan
            glow_color = QColor(0, 255, 255, 80)

        # Draw HUD crosshairs around the core
        pen = QPen(base_color, 2)
        painter.setPen(pen)
        offset = 20
        # Top Left
        painter.drawLine(int(cx - radius - offset), int(cy - radius), int(cx - radius), int(cy - radius))
        painter.drawLine(int(cx - radius - offset), int(cy - radius), int(cx - radius - offset), int(cy - radius + offset))
        # Top Right
        painter.drawLine(int(cx + radius), int(cy - radius), int(cx + radius + offset), int(cy - radius))
        painter.drawLine(int(cx + radius + offset), int(cy - radius), int(cx + radius + offset), int(cy - radius + offset))
        # Bottom Left
        painter.drawLine(int(cx - radius - offset), int(cy + radius), int(cx - radius), int(cy + radius))
        painter.drawLine(int(cx - radius - offset), int(cy + radius), int(cx - radius - offset), int(cy + radius - offset))
        # Bottom Right
        painter.drawLine(int(cx + radius), int(cy + radius), int(cx + radius + offset), int(cy + radius))
        painter.drawLine(int(cx + radius + offset), int(cy + radius), int(cx + radius + offset), int(cy + radius - offset))

        # --- CORE ---
        painter.translate(cx, cy)
        
        # Outer dashed rotating ring
        painter.rotate(self.angle_outer)
        dash_pen = QPen(base_color, 3)
        dash_pen.setDashPattern([4, 6])
        painter.setPen(dash_pen)
        painter.drawEllipse(QPointF(0, 0), radius, radius)
        painter.rotate(-self.angle_outer)

        # Inner solid rotating ring with arcs
        painter.rotate(self.angle_inner)
        solid_pen = QPen(base_color, 1.5)
        painter.setPen(solid_pen)
        inner_rad = radius * 0.75
        painter.drawArc(QRectF(-inner_rad, -inner_rad, inner_rad*2, inner_rad*2), 0, 16 * 120)
        painter.drawArc(QRectF(-inner_rad, -inner_rad, inner_rad*2, inner_rad*2), 16 * 180, 16 * 120)
        painter.rotate(-self.angle_inner)

        # Pulsing Center Glow
        pulse_rad = inner_rad * 0.5 + (inner_rad * 0.3 * self.pulse)
        grad = QRadialGradient(0, 0, pulse_rad)
        grad.setColorAt(0.0, base_color)
        grad.setColorAt(0.6, glow_color)
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QPointF(0, 0), pulse_rad, pulse_rad)

        painter.end()


class NovaGUI(QWidget):
    """
    Frameless holographic AI UI without scrolling chat logs. 
    Focuses entirely on the immersive voice visualizer.
    """
    sig_text_submit = pyqtSignal(str) # Kept for main.py compatibility
    sig_shutdown = pyqtSignal()

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.init_ui()
        self._drag_pos = None

    def init_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(800, 800)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Glass Panel
        self.bg_frame = QFrame(self)
        self.bg_frame.setStyleSheet("""
            QFrame {
                background: rgba(5, 5, 8, 200);
                border: 1px solid rgba(0, 255, 255, 15);
                border-radius: 30px;
            }
        """)
        bg_layout = QVBoxLayout(self.bg_frame)
        
        # --- TOP CLOSE BTN ---
        top_layout = QHBoxLayout()
        top_layout.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: rgba(255, 255, 255, 50);
                border-radius: 15px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { color: rgba(255, 0, 0, 200); }
        """)
        close_btn.clicked.connect(self.close_app)
        top_layout.addWidget(close_btn)
        bg_layout.addLayout(top_layout)

        # --- SUBTITLE & STATUS ---
        self.status_label = QLabel("SYSTEM IDLE")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.status_label.setStyleSheet("color: rgba(0, 255, 255, 180); background: transparent; letter-spacing: 8px;")
        bg_layout.addWidget(self.status_label)

        # --- HOLOGRAPHIC CORE ---
        self.core = NovaCoreWidget()
        bg_layout.addWidget(self.core)

        # --- CAPTIONS (Optional replacement for Chat Log) ---
        self.caption_label = QLabel("")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption_label.setWordWrap(True)
        self.caption_label.setFont(QFont("Inter", 12))
        self.caption_label.setStyleSheet("color: rgba(255, 255, 255, 100); background: transparent;")
        self.caption_label.setFixedHeight(60)
        bg_layout.addWidget(self.caption_label)

        main_layout.addWidget(self.bg_frame)

    def add_message(self, role: str, text: str):
        """
        Instead of a scrolling chat log, we just show subtitles at the bottom.
        We keep this method signature because main.py invokes it.
        """
        if role == "user":
            self.caption_label.setStyleSheet("color: rgba(0, 200, 255, 150); background: transparent;")
            self.caption_label.setText(f"[You]: {text}")
        elif role == "bot" or role == "system":
            self.caption_label.setStyleSheet("color: rgba(255, 255, 255, 200); background: transparent;")
            self.caption_label.setText(text)

    def set_status(self, status: str):
        self.status_label.setText(f"SYSTEM {status.upper()}")
        self.core.set_status(status)

    def close_app(self):
        self.sig_shutdown.emit()

    # Enable Window Dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

