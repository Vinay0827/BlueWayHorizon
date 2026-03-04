import sys
import serial
import serial.tools.list_ports
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QFileDialog, QMessageBox, QLabel, QFrame,
                             QSizePolicy, QComboBox, QLineEdit, QScrollArea, QGridLayout)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

#  CONFIGURATION 
WINDOW_SIZE        = 60
ANIMATION_SPEED_MS = 33
LOGO_FILENAME      = "Logoblueway.jpeg"
DEFAULT_BAUD_RATE  = 9600

#  THEME  (exact match to LUNA ROBOT screenshot) 
COLOR_BG_MAIN  = "#121212"
COLOR_BG_CARD  = "#1E1E1E"
COLOR_BG_PLOT  = "#000000"
COLOR_TEXT     = "#FFFFFF"
COLOR_SUBTEXT  = "#AAAAAA"
COLOR_BORDER   = "#333333"
COLOR_ACCENT   = "#2563EB"
COLOR_GREEN    = "#00E676"
COLOR_RED      = "#FF5252"
COLOR_GRAY     = "#555555"

# Graph line colours – same palette as LUNA ROBOT
PAL_IMU  = ["#FF6B6B", "#4ECDC4", "#FFD166"]
PAL_QUAT = ["#A78BFA", "#60A5FA", "#34D399", "#F472B6"]
PAL_ACC  = ["#FB923C", "#FACC15", "#A3E635"]
PAL_GYRO = ["#38BDF8", "#E879F9", "#4ADE80"]
PAL_VIB  = ["#FF8FAB", "#9BD0F5", "#FFE08A"]


#  GRAPH CANVAS  – one figure with 5 stacked subplots
class FiveGraphCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(facecolor=COLOR_BG_CARD)
        # 5 vertically stacked axes
        self.axes = []
        for i in range(5):
            ax = self.fig.add_subplot(5, 1, i + 1)
            ax.set_facecolor(COLOR_BG_PLOT)
            for sp in ax.spines.values():
                sp.set_color("#444444")
            ax.grid(True, alpha=0.2, color="white", linestyle="--", linewidth=0.6)
            ax.tick_params(colors=COLOR_SUBTEXT, labelsize=7)
            self.axes.append(ax)

        self.fig.subplots_adjust(left=0.07, right=0.97,
                                  top=0.97, bottom=0.04,
                                  hspace=0.55)
        super().__init__(self.fig)
        self.setStyleSheet("background-color: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ── helper to re-style an axis after .clear() ──
    def _style(self, ax, title):
        ax.set_facecolor(COLOR_BG_PLOT)
        for sp in ax.spines.values():
            sp.set_color("#444444")
        ax.grid(True, alpha=0.2, color="white", linestyle="--", linewidth=0.6)
        ax.set_title(title, color=COLOR_TEXT, fontsize=8, fontweight="bold", pad=3)
        ax.tick_params(colors=COLOR_SUBTEXT, labelsize=7)

    def update_all(self, x, imu, quat, acc, gyro, vib):
        datasets = [
            (imu,  PAL_IMU,  ["Roll", "Pitch", "Yaw"],               "IMU  —  Roll / Pitch / Yaw  (°)"),
            (quat, PAL_QUAT, ["Quat W", "Quat X", "Quat Y", "Quat Z"], "Quaternion  —  W / X / Y / Z"),
            (acc,  PAL_ACC,  ["Accel X", "Accel Y", "Accel Z"],       "Accelerometer  —  X / Y / Z  (m/s²)"),
            (gyro, PAL_GYRO, ["Gyro X", "Gyro Y", "Gyro Z"],          "Gyroscope  —  X / Y / Z  (rad/s)"),
            (vib,  PAL_VIB,  ["Vib X", "Vib Y", "Vib Z"],             "Vibration  —  X / Y / Z"),
        ]
        for i, (series_list, colors, labels, title) in enumerate(datasets):
            ax = self.axes[i]
            ax.clear()
            self._style(ax, title)
            for j, y in enumerate(series_list):
                if y:
                    ax.plot(x, y, color=colors[j], linewidth=1.4,
                            label=labels[j], alpha=0.95)
            leg = ax.legend(loc="upper right", fontsize=6.5,
                            framealpha=0.45, facecolor=COLOR_BG_CARD,
                            edgecolor=COLOR_BORDER, labelcolor=COLOR_TEXT,
                            handlelength=1.2, borderpad=0.4)
        self.draw()


#  HELPER WIDGETS
def _card_frame():
    f = QFrame()
    f.setStyleSheet(f"""QFrame {{
        background-color: {COLOR_BG_CARD};
        border-radius: 12px;
        border: 1px solid {COLOR_BORDER};
    }}""")
    return f


def make_value_row(label_text, color):
    """Returns (row_widget, value_label) — one label:value line."""
    row = QHBoxLayout()
    lbl = QLabel(label_text + ":")
    lbl.setFont(QFont("Segoe UI", 10))
    lbl.setStyleSheet(f"color: {COLOR_SUBTEXT}; background: transparent; border: none;")
    val = QLabel("--")
    val.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    val.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    row.addWidget(lbl)
    row.addStretch()
    row.addWidget(val)
    return row, val


def make_section_card(title, rows_spec):
    """
    rows_spec: list of (label, color)
    Returns (card_frame, {label: val_label})
    """
    frame = _card_frame()
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 12, 18, 12)
    lay.setSpacing(6)

    hdr = QLabel(title)
    hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    hdr.setStyleSheet(f"color: {COLOR_TEXT}; background: transparent; border: none;")
    lay.addWidget(hdr)

    vals = {}
    for label, color in rows_spec:
        row_lay, val_lbl = make_value_row(label, color)
        lay.addLayout(row_lay)
        vals[label] = val_lbl

    return frame, vals


def make_onoff_card(title, channels):
    """
    channels: list of str names
    Returns (frame, {name: (indicator_lbl, text_lbl)})
    """
    frame = _card_frame()
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 12, 18, 12)
    lay.setSpacing(8)

    hdr = QLabel(title)
    hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    hdr.setStyleSheet(f"color: {COLOR_TEXT}; background: transparent; border: none;")
    lay.addWidget(hdr)

    row = QHBoxLayout()
    row.setSpacing(10)
    indicators = {}
    for name in channels:
        col = QVBoxLayout()
        col.setSpacing(4)

        ind = QLabel()
        ind.setFixedSize(44, 44)
        ind.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ind.setStyleSheet(f"background-color: {COLOR_GRAY}; border-radius: 6px; border: 2px solid {COLOR_BORDER};")

        txt = QLabel("--")
        txt.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        txt.setStyleSheet(f"color: {COLOR_GRAY}; background: transparent;")
        txt.setAlignment(Qt.AlignmentFlag.AlignCenter)

        nm = QLabel(name)
        nm.setFont(QFont("Segoe UI", 8))
        nm.setStyleSheet(f"color: {COLOR_SUBTEXT}; background: transparent;")
        nm.setAlignment(Qt.AlignmentFlag.AlignCenter)

        col.addWidget(ind)
        col.addWidget(txt)
        col.addWidget(nm)
        row.addLayout(col)
        indicators[name] = (ind, txt)

    lay.addLayout(row)
    return frame, indicators


def set_onoff(ind_lbl, txt_lbl, value):
    is_on = str(value).strip().upper() == "ON"
    if is_on:
        ind_lbl.setStyleSheet(f"background-color: {COLOR_GREEN}; border-radius: 6px; border: 2px solid {COLOR_GREEN};")
        txt_lbl.setText("ON")
        txt_lbl.setStyleSheet(f"color: {COLOR_GREEN}; background: transparent; font-weight: bold;")
    else:
        ind_lbl.setStyleSheet(f"background-color: {COLOR_RED}; border-radius: 6px; border: 2px solid {COLOR_RED};")
        txt_lbl.setText("OFF")
        txt_lbl.setStyleSheet(f"color: {COLOR_RED}; background: transparent; font-weight: bold;")


#  MAIN WINDOW
class DroneDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.live_data   = []
        self.serial_port = None
        self.is_connected = False

        self.setWindowTitle("SATELLITE TELEMETRY DASHBOARD  —  IMU | ACCEL | GYRO | VIBRATION | GPS | COMMS")
        self.resize(1560, 940)
        self.setStyleSheet(f"QMainWindow {{ background-color: {COLOR_BG_MAIN}; }}")

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(18, 18, 18, 18)
        self.main_layout.setSpacing(10)

        self._build_header()
        self._build_content()
        self._build_footer()

        self.timer = QTimer()
        self.timer.timeout.connect(self._read_serial)

    # ── HEADER 
    def _build_header(self):
        header = QFrame()
        header.setFixedHeight(80)
        header.setStyleSheet(f"""QFrame {{
            background-color: {COLOR_BG_CARD};
            border-radius: 10px;
            border: 1px solid {COLOR_BORDER};
        }}""")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(15, 10, 15, 10)

        # Logo — height fixed at 58px, width auto-fits the image (no empty sides)
        logo = QLabel()
        logo.setStyleSheet(
            "QLabel { background-color: transparent; padding: 0px; margin: 0px; }")
        logo.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        try:
            px = QPixmap(LOGO_FILENAME)
            if not px.isNull():
                scaled = px.scaledToHeight(58, Qt.TransformationMode.SmoothTransformation)
                logo.setPixmap(scaled)
                logo.setFixedSize(scaled.width(), scaled.height())
                lay.addWidget(logo)
            else:
                logo.setVisible(False)
        except:
            logo.setVisible(False)

        lay.addStretch()
        title = QLabel("SATELLITE TELEMETRY DATA ACQUISITION")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; background: transparent;")
        lay.addWidget(title)
        lay.addStretch()

        # System mode pill
        self.lbl_mode = QLabel("MODE: --")
        self.lbl_mode.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_mode.setStyleSheet(f"""
            background-color: {COLOR_ACCENT};
            color: white;
            padding: 5px 16px;
            border-radius: 14px;
        """)
        lay.addWidget(self.lbl_mode)
        lay.addSpacing(10)

        self.lbl_err = QLabel("ERR: 0")
        self.lbl_err.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_err.setStyleSheet(f"""
            background-color: {COLOR_GREEN};
            color: #000;
            padding: 5px 14px;
            border-radius: 14px;
        """)
        lay.addWidget(self.lbl_err)

        self.main_layout.addWidget(header)

    # ── CONTENT 
    def _build_content(self):
        content = QHBoxLayout()
        content.setSpacing(12)

        # ── LEFT: graph card 
        graph_card = QFrame()
        graph_card.setStyleSheet(f"""QFrame {{
            background-color: {COLOR_BG_CARD};
            border-radius: 12px;
            border: 1px solid {COLOR_BORDER};
        }}""")
        gc_lay = QVBoxLayout(graph_card)
        gc_lay.setContentsMargins(8, 8, 8, 8)

        self.graphs = FiveGraphCanvas()
        gc_lay.addWidget(self.graphs)
        content.addWidget(graph_card, stretch=62)

        # ── RIGHT: scrollable stats 
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: {COLOR_BG_MAIN}; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLOR_BORDER}; border-radius: 3px;
            }}
        """)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        right_lay = QVBoxLayout(inner)
        right_lay.setContentsMargins(0, 0, 4, 0)
        right_lay.setSpacing(10)

        # ── Packet / System card 
        f, v = make_section_card("System Info", [
            ("Packet ID",  "#AAAAAA"),
            ("Timestamp",  "#AAAAAA"),
        ])
        right_lay.addWidget(f)
        self.v_pid  = v["Packet ID"]
        self.v_ts   = v["Timestamp"]

        # ── Power card 
        f, v = make_section_card("⚡  Power", [
            ("Battery Voltage", "#FBBF24"),
            ("Battery Current", "#FB923C"),
            ("MCU Temp",        "#FF5252"),
        ])
        right_lay.addWidget(f)
        self.v_batt_v = v["Battery Voltage"]
        self.v_batt_i = v["Battery Current"]
        self.v_mcu    = v["MCU Temp"]

        # ── IMU current values card (like original) 
        f, v = make_section_card("IMU Current Values", [
            ("Roll",  "#FF6B6B"),
            ("Pitch", "#4ECDC4"),
            ("Yaw",   "#FFD166"),
        ])
        right_lay.addWidget(f)
        self.v_roll  = v["Roll"]
        self.v_pitch = v["Pitch"]
        self.v_yaw   = v["Yaw"]

        # ── Quaternion card ────────────────────────────────────────────────────
        f, v = make_section_card("Quaternion", [
            ("Quat W", "#A78BFA"),
            ("Quat X", "#60A5FA"),
            ("Quat Y", "#34D399"),
            ("Quat Z", "#F472B6"),
        ])
        right_lay.addWidget(f)
        self.v_qw = v["Quat W"]
        self.v_qx = v["Quat X"]
        self.v_qy = v["Quat Y"]
        self.v_qz = v["Quat Z"]

        # ── Environment card 
        f, v = make_section_card("🌡  Environment", [
            ("Pressure",    "#60A5FA"),
            ("Altitude",    "#34D399"),
            ("Temperature", "#F87171"),
            ("Humidity",    "#818CF8"),
        ])
        right_lay.addWidget(f)
        self.v_pres = v["Pressure"]
        self.v_alt  = v["Altitude"]
        self.v_temp = v["Temperature"]
        self.v_hum  = v["Humidity"]

        # ── GPS card 
        f, v = make_section_card("📡  GPS", [
            ("Latitude",    "#4ADE80"),
            ("Longitude",   "#4ADE80"),
            ("GPS Altitude","#A78BFA"),
            ("GPS Speed",   "#38BDF8"),
            ("Satellites",  "#FFD166"),
        ])
        right_lay.addWidget(f)
        self.v_lat  = v["Latitude"]
        self.v_lon  = v["Longitude"]
        self.v_galt = v["GPS Altitude"]
        self.v_spd  = v["GPS Speed"]
        self.v_sat  = v["Satellites"]

        # ── Comms card 
        f, v = make_section_card("📶  Comms", [
            ("LoRa RSSI",    "#F472B6"),
            ("LoRa SNR",     "#C084FC"),
            ("LTE Signal",   "#67E8F9"),
        ])
        right_lay.addWidget(f)
        self.v_rssi = v["LoRa RSSI"]
        self.v_snr  = v["LoRa SNR"]
        self.v_lte  = v["LTE Signal"]

        # ── Camera ON/OFF card (green/red, same as LUNA ROBOT linear sensor) ──
        f, inds = make_onoff_card("📷  Camera Status",
                                  ["Camera 1", "Camera 2", "Camera 3"])
        right_lay.addWidget(f)
        self.cam_inds = inds   # {"Camera 1": (ind_lbl, txt_lbl), ...}

        right_lay.addStretch()
        scroll.setWidget(inner)
        content.addWidget(scroll, stretch=38)

        self.main_layout.addLayout(content, stretch=1)

    # ── FOOTER 
    def _build_footer(self):
        footer = QFrame()
        footer.setFixedHeight(70)
        footer.setStyleSheet(f"""QFrame {{
            background-color: {COLOR_BG_CARD};
            border-radius: 10px;
            border: 1px solid {COLOR_BORDER};
        }}""")
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(20, 10, 20, 10)
        lay.setSpacing(12)

        def _lbl(text):
            l = QLabel(text)
            l.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {COLOR_TEXT}; background: transparent;")
            return l

        def _input(default, w=100):
            e = QLineEdit(default)
            e.setFixedWidth(w)
            e.setFont(QFont("Segoe UI", 10))
            e.setStyleSheet(f"""QLineEdit {{
                background-color: {COLOR_BG_MAIN};
                color: {COLOR_TEXT};
                padding: 6px 10px;
                border: 1px solid {COLOR_BORDER};
                border-radius: 5px;
            }}""")
            return e

        def _btn(text, bg, fg="#FFFFFF"):
            b = QPushButton(text)
            b.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            b.setFixedHeight(42)
            b.setStyleSheet(f"""QPushButton {{
                background-color: {bg};
                color: {fg};
                font-weight: bold;
                padding: 0 22px;
                border-radius: 5px;
                border: none;
            }}
            QPushButton:disabled {{
                background-color: {COLOR_GRAY};
                color: #888;
            }}""")
            return b

        # PORT
        lay.addWidget(_lbl("PORT:"))
        self.combo_ports = QComboBox()
        self.combo_ports.setFont(QFont("Segoe UI", 10))
        self.combo_ports.setFixedHeight(42)
        self.combo_ports.setMinimumWidth(160)
        self.combo_ports.setStyleSheet(f"""QComboBox {{
            background-color: {COLOR_BG_MAIN};
            color: {COLOR_TEXT};
            padding: 6px 10px;
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {COLOR_BG_CARD};
            color: {COLOR_TEXT};
            selection-background-color: {COLOR_ACCENT};
        }}""")
        self._refresh_ports()
        lay.addWidget(self.combo_ports)

        # Refresh ports button
        btn_refresh = _btn("↻", COLOR_GRAY)
        btn_refresh.setFixedWidth(42)
        btn_refresh.clicked.connect(self._refresh_ports)
        lay.addWidget(btn_refresh)

        # BAUD
        lay.addWidget(_lbl("BAUD:"))
        self.input_baud = _input(str(DEFAULT_BAUD_RATE), 110)
        lay.addWidget(self.input_baud)

        # CONNECT / DISCONNECT
        self.btn_connect = _btn("CONNECT", COLOR_ACCENT)
        self.btn_connect.clicked.connect(self._toggle_connection)
        lay.addWidget(self.btn_connect)

        # Status
        self.lbl_status = QLabel("Disconnected")
        self.lbl_status.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_status.setStyleSheet(f"color: {COLOR_RED}; font-weight: bold; margin-left: 10px; background: transparent;")
        lay.addWidget(self.lbl_status)

        lay.addStretch()

        # EXPORT CSV
        btn_export = _btn("📥  EXPORT CSV", COLOR_GREEN, "#000000")
        btn_export.clicked.connect(self._export_csv)
        lay.addWidget(btn_export)

        self.main_layout.addWidget(footer)

    # ── PORT HELPERS 
    def _refresh_ports(self):
        self.combo_ports.clear()
        for p in serial.tools.list_ports.comports():
            self.combo_ports.addItem(p.device)

    def _toggle_connection(self):
        if not self.is_connected:
            try:
                port = self.combo_ports.currentText()
                baud = int(self.input_baud.text())
                if not port:
                    return
                self.serial_port = serial.Serial(port, baud, timeout=1)
                self.is_connected = True
                self.live_data = []

                self.btn_connect.setText("DISCONNECT")
                self.btn_connect.setStyleSheet(f"""QPushButton {{
                    background-color: {COLOR_RED};
                    color: white;
                    font-weight: bold;
                    padding: 0 22px;
                    border-radius: 5px;
                    border: none;
                }}""")
                self.lbl_status.setText(f"Connected to {port}")
                self.lbl_status.setStyleSheet(f"color: {COLOR_GREEN}; font-weight: bold; margin-left: 10px; background: transparent;")
                self.combo_ports.setEnabled(False)
                self.input_baud.setEnabled(False)
                self.timer.start(ANIMATION_SPEED_MS)

            except Exception as e:
                QMessageBox.critical(self, "Connection Error", str(e))
        else:
            self.timer.stop()
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
            self.is_connected = False

            self.btn_connect.setText("CONNECT")
            self.btn_connect.setStyleSheet(f"""QPushButton {{
                background-color: {COLOR_ACCENT};
                color: white;
                font-weight: bold;
                padding: 0 22px;
                border-radius: 5px;
                border: none;
            }}""")
            self.lbl_status.setText("Disconnected")
            self.lbl_status.setStyleSheet(f"color: {COLOR_RED}; font-weight: bold; margin-left: 10px; background: transparent;")
            self.combo_ports.setEnabled(True)
            self.input_baud.setEnabled(True)

    # ── SERIAL READ 
    def _read_serial(self):
        """
        Expected CSV line from drone (tab OR comma separated), matching the
        columns in the sample CSV.  Column order:
        Timestamp, Packet_ID, System_Mode, Battery_Voltage, Battery_Current,
        MCU_Temp, IMU_Roll, IMU_Pitch, IMU_Yaw, IMU_Quat_W, IMU_Quat_X,
        IMU_Quat_Y, IMU_Quat_Z, Accel_X, Accel_Y, Accel_Z, Gyro_X, Gyro_Y,
        Gyro_Z, Vibration_X, Vibration_Y, Vibration_Z, Pressure_hPa,
        Altitude_m, Temperature_C, Humidity_percent, GPS_Latitude,
        GPS_Longitude, GPS_Altitude, GPS_Speed, GPS_Satellites, LoRa_RSSI,
        LoRa_SNR, LTE_Signal_Strength, Camera1_Status, Camera2_Status,
        Camera3_Status, Error_Code
        """
        if not (self.serial_port and self.serial_port.is_open):
            return
        try:
            while self.serial_port.in_waiting > 0:
                raw = self.serial_port.readline().decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                # Accept tab or comma separated
                sep = "\t" if "\t" in raw else ","
                parts = raw.split(sep)
                if len(parts) < 38:
                    continue
                try:
                    row = {
                        "Timestamp":           parts[0].strip(),
                        "Packet_ID":           parts[1].strip(),
                        "System_Mode":         parts[2].strip(),
                        "Battery_Voltage":     float(parts[3]),
                        "Battery_Current":     float(parts[4]),
                        "MCU_Temp":            float(parts[5]),
                        "IMU_Roll":            float(parts[6]),
                        "IMU_Pitch":           float(parts[7]),
                        "IMU_Yaw":             float(parts[8]),
                        "IMU_Quat_W":          float(parts[9]),
                        "IMU_Quat_X":          float(parts[10]),
                        "IMU_Quat_Y":          float(parts[11]),
                        "IMU_Quat_Z":          float(parts[12]),
                        "Accel_X":             float(parts[13]),
                        "Accel_Y":             float(parts[14]),
                        "Accel_Z":             float(parts[15]),
                        "Gyro_X":              float(parts[16]),
                        "Gyro_Y":              float(parts[17]),
                        "Gyro_Z":              float(parts[18]),
                        "Vibration_X":         float(parts[19]),
                        "Vibration_Y":         float(parts[20]),
                        "Vibration_Z":         float(parts[21]),
                        "Pressure_hPa":        float(parts[22]),
                        "Altitude_m":          float(parts[23]),
                        "Temperature_C":       float(parts[24]),
                        "Humidity_percent":    float(parts[25]),
                        "GPS_Latitude":        float(parts[26]),
                        "GPS_Longitude":       float(parts[27]),
                        "GPS_Altitude":        float(parts[28]),
                        "GPS_Speed":           float(parts[29]),
                        "GPS_Satellites":      int(float(parts[30])),
                        "LoRa_RSSI":           float(parts[31]),
                        "LoRa_SNR":            float(parts[32]),
                        "LTE_Signal_Strength": float(parts[33]),
                        "Camera1_Status":      parts[34].strip(),
                        "Camera2_Status":      parts[35].strip(),
                        "Camera3_Status":      parts[36].strip(),
                        "Error_Code":          int(float(parts[37])),
                    }
                    self.live_data.append(row)
                    self._update_ui(row)
                except (ValueError, IndexError):
                    pass   # skip malformed line
        except Exception as e:
            print(f"Serial error: {e}")

    # ── UI UPDATE 
    def _update_ui(self, row):
        # ── Stat labels 
        self.v_pid.setText(str(row["Packet_ID"]))
        self.v_ts.setText(str(row["Timestamp"])[-8:])

        self.v_batt_v.setText(f"{row['Battery_Voltage']:.2f} V")
        self.v_batt_i.setText(f"{row['Battery_Current']:.2f} A")
        self.v_mcu.setText(f"{row['MCU_Temp']:.1f} °C")

        self.v_roll.setText(f"{row['IMU_Roll']:.2f} °")
        self.v_pitch.setText(f"{row['IMU_Pitch']:.2f} °")
        self.v_yaw.setText(f"{row['IMU_Yaw']:.2f} °")

        self.v_qw.setText(f"{row['IMU_Quat_W']:.3f}")
        self.v_qx.setText(f"{row['IMU_Quat_X']:.3f}")
        self.v_qy.setText(f"{row['IMU_Quat_Y']:.3f}")
        self.v_qz.setText(f"{row['IMU_Quat_Z']:.3f}")

        self.v_pres.setText(f"{row['Pressure_hPa']:.1f} hPa")
        self.v_alt.setText(f"{row['Altitude_m']:.1f} m")
        self.v_temp.setText(f"{row['Temperature_C']:.1f} °C")
        self.v_hum.setText(f"{row['Humidity_percent']:.1f} %")

        self.v_lat.setText(f"{row['GPS_Latitude']:.6f}")
        self.v_lon.setText(f"{row['GPS_Longitude']:.6f}")
        self.v_galt.setText(f"{row['GPS_Altitude']:.1f} m")
        self.v_spd.setText(f"{row['GPS_Speed']:.2f} m/s")
        self.v_sat.setText(str(row["GPS_Satellites"]))

        self.v_rssi.setText(f"{row['LoRa_RSSI']:.0f} dBm")
        self.v_snr.setText(f"{row['LoRa_SNR']:.1f} dB")
        self.v_lte.setText(f"{row['LTE_Signal_Strength']:.0f} dBm")

        # ── Camera ON/OFF indicators 
        for key, col_name in [("Camera 1", "Camera1_Status"),
                               ("Camera 2", "Camera2_Status"),
                               ("Camera 3", "Camera3_Status")]:
            ind, txt = self.cam_inds[key]
            set_onoff(ind, txt, row[col_name])

        # ── Mode / Error pill 
        self.lbl_mode.setText(f"MODE: {row['System_Mode']}")
        err = row["Error_Code"]
        if err == 0:
            self.lbl_err.setText("ERR: OK")
            self.lbl_err.setStyleSheet(f"background-color: {COLOR_GREEN}; color: #000; padding: 5px 14px; border-radius: 14px;")
        else:
            self.lbl_err.setText(f"ERR: {err}")
            self.lbl_err.setStyleSheet(f"background-color: {COLOR_RED}; color: white; padding: 5px 14px; border-radius: 14px;")

        # ── Graphs 
        start = max(0, len(self.live_data) - WINDOW_SIZE)
        buf   = self.live_data[start:]
        x     = list(range(len(buf)))

        def col(k):
            try:    return [float(r[k]) for r in buf]
            except: return [0.0] * len(buf)

        self.graphs.update_all(
            x,
            imu  = [col("IMU_Roll"),   col("IMU_Pitch"),  col("IMU_Yaw")],
            quat = [col("IMU_Quat_W"), col("IMU_Quat_X"), col("IMU_Quat_Y"), col("IMU_Quat_Z")],
            acc  = [col("Accel_X"),    col("Accel_Y"),    col("Accel_Z")],
            gyro = [col("Gyro_X"),     col("Gyro_Y"),     col("Gyro_Z")],
            vib  = [col("Vibration_X"),col("Vibration_Y"),col("Vibration_Z")],
        )

    # ── EXPORT 
    def _export_csv(self):
        if not self.live_data:
            QMessageBox.warning(self, "No Data", "No data received yet.")
            return
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV",
                                              f"satellite_telemetry_{ts}.csv",
                                              "CSV Files (*.csv)")
        if path:
            try:
                pd.DataFrame(self.live_data).to_csv(path, index=False)
                QMessageBox.information(self, "Exported",
                                        f"Saved {len(self.live_data)} rows to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save:\n{e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DroneDashboard()
    win.show()
    sys.exit(app.exec())