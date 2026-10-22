import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, QSize, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from hexon_discord import DiscordPresence, GameWatcher
from hexon_profiles import (CURRENT, FOREIGN, INDEX_NAME, NO_EXE, NOT_INSTALLED, OUTDATED, ProfileStore, atomic_copy,
                            bitness_problem, detect_anticheat, dll_state, guess_game_name, install as install_dll,
                            last_launch_summary, read_ini, uninstall as uninstall_dll, write_ini)

VERSION = "2.0.0-dev.2"
DISCORD_APP_ID = "1558850044126568501"
DISCORD_LARGE_IMAGE = "hexon"
DISCORD_BUTTON = {"label": "Get Hexon", "url": "https://github.com/Swerve2k/HexonDumper"}
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(__file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
EXE_DIR = Path(sys.executable).parent if FROZEN else APP_DIR
ASSETS = RES_DIR / "assets"
LOGO = ASSETS / "logo.ico"
CHECK = ASSETS / "check.png"
_WORKER_EXE = "hexon-preview.exe" if sys.platform == "win32" else "hexon-preview"
WORKER_CMD = [str(EXE_DIR / _WORKER_EXE)] if FROZEN else [sys.executable, str(APP_DIR / "hexon_preview.py")]


def find_core_dll():
    for cand in (RES_DIR / "core" / "dxgi.dll", APP_DIR.parent / "build" / "Release" / "dxgi.dll",
                 APP_DIR.parent / "prebuilt" / "dxgi.dll", APP_DIR / "dxgi.dll"):
        if cand.is_file():
            return cand
    return None
GB = 1024 ** 3

FAMILY = {}
for _name, _codes in {
    "RGBA8": (27, 28, 29), "BGRA8": (87, 90, 91), "R8": (60, 61), "RG8": (48, 49),
    "BC1": (70, 71, 72), "BC2": (73, 74, 75), "BC3": (76, 77, 78), "BC4": (79, 80, 81),
    "BC5": (82, 83, 84), "BC6H": (94, 95, 96), "BC7": (97, 98, 99),
    "RGBA16": (9, 10, 11), "RG16": (33, 34, 35), "R16": (53, 54, 56), "A8": (65,),
    "RGB10A2": (23, 24), "R11G11B10": (26,),
}.items():
    for _c in _codes:
        FAMILY[_c] = _name

FOURCC_FAMILY = {b"DXT1": "BC1", b"DXT3": "BC2", b"DXT5": "BC3", b"ATI1": "BC4", b"BC4U": "BC4",
                 b"ATI2": "BC5", b"BC5U": "BC5"}

TEXCONV_FORMAT = {
    28: "R8G8B8A8_UNORM", 29: "R8G8B8A8_UNORM_SRGB", 87: "B8G8R8A8_UNORM", 91: "B8G8R8A8_UNORM_SRGB",
    61: "R8_UNORM", 49: "R8G8_UNORM", 65: "A8_UNORM", 56: "R16_UNORM", 54: "R16_FLOAT", 35: "R16G16_UNORM",
    34: "R16G16_FLOAT", 11: "R16G16B16A16_UNORM", 10: "R16G16B16A16_FLOAT", 24: "R10G10B10A2_UNORM",
    26: "R11G11B10_FLOAT", 71: "BC1_UNORM", 72: "BC1_UNORM_SRGB", 74: "BC2_UNORM", 75: "BC2_UNORM_SRGB",
    77: "BC3_UNORM", 78: "BC3_UNORM_SRGB", 80: "BC4_UNORM", 81: "BC4_SNORM", 83: "BC5_UNORM", 84: "BC5_SNORM",
    95: "BC6H_UF16", 96: "BC6H_SF16", 98: "BC7_UNORM", 99: "BC7_UNORM_SRGB",
}
FAMILY_TEXCONV = {
    "RGBA8": "R8G8B8A8_UNORM", "BGRA8": "B8G8R8A8_UNORM", "R8": "R8_UNORM", "RG8": "R8G8_UNORM", "A8": "A8_UNORM",
    "R16": "R16_UNORM", "RG16": "R16G16_UNORM", "RGBA16": "R16G16B16A16_UNORM", "RGB10A2": "R10G10B10A2_UNORM",
    "R11G11B10": "R11G11B10_FLOAT", "BC1": "BC1_UNORM", "BC2": "BC2_UNORM", "BC3": "BC3_UNORM", "BC4": "BC4_UNORM",
    "BC5": "BC5_UNORM", "BC6H": "BC6H_UF16", "BC7": "BC7_UNORM",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff"}
TAB_PROFILES, TAB_TEXTURES, TAB_CHANGED, TAB_SETTINGS, TAB_LOG = range(5)
TAB_ACTIVITY = ["Setting up the game", "Browsing textures", "Reviewing replaced textures",
                "Tweaking settings", "Reading the log"]

NAME_RE = re.compile(r"^([0-9a-f]{16})_(\d+)x(\d+)_([A-Za-z0-9]+)\.dds$")
MAX_ROWS = 3000

QSS = """
* { font-family: 'Segoe UI', sans-serif; font-size: 13px; color: #e4e6ec; }
QMainWindow, QWidget { background: #14151a; }
QTabWidget::pane { border: 1px solid #262833; border-radius: 6px; top: -1px; }
QTabBar::tab { background: transparent; padding: 8px 18px; color: #8b90a0; border: none; }
QTabBar::tab:selected { color: #e4e6ec; border-bottom: 2px solid #6c8cff; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {
    background: #1b1d25; border: 1px solid #262833; border-radius: 6px; padding: 5px;
    selection-background-color: #6c8cff; selection-color: #0d0e12; }
QComboBox QAbstractItemView { background: #1b1d25; selection-background-color: #6c8cff; selection-color: #0d0e12; }
QTableWidget { gridline-color: #20222b; alternate-background-color: #181a21; }
QListWidget::item { border-radius: 6px; padding: 4px; color: #aeb3c2; }
QListWidget::item:selected { background: #232736; border: 1px solid #6c8cff; color: #e4e6ec; }
QHeaderView::section { background: #1b1d25; color: #8b90a0; border: none; padding: 6px; }
QPushButton { background: #1f222c; border: 1px solid #2c2f3b; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { border-color: #6c8cff; }
QPushButton:disabled { color: #5b6070; }
QPushButton#primary { background: #6c8cff; color: #0d0e12; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #8aa3ff; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #2c2f3b; background: #1b1d25; }
QCheckBox::indicator:checked { background: #6c8cff; border-color: #6c8cff; image: url(CHECK_URL); }
QProgressBar { background: #1b1d25; border: 1px solid #262833; border-radius: 4px; max-height: 8px; }
QProgressBar::chunk { background: #6c8cff; border-radius: 3px; }
QSplitter::handle { background: transparent; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #2c2f3b; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3a3e4e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: #2c2f3b; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QLabel#section { color: #8b90a0; font-size: 11px; letter-spacing: 2px; padding-top: 10px; }
QLabel#muted { color: #8b90a0; }
QLabel#warn { color: #e0a458; }
QLabel#preview { background: #1b1d25; border: 1px solid #262833; border-radius: 8px; color: #5b6070; }
"""


def stylesheet() -> str:
    return QSS.replace("CHECK_URL", CHECK.as_posix())


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dir_size(path: Path) -> int:
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.is_file(follow_symlinks=False):
                    total += e.stat().st_size
    except OSError:
        pass
    return total


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def read_dds_header(path: Path) -> dict:
    with open(path, "rb") as f:
        head = f.read(148)
    if len(head) < 128 or head[:4] != b"DDS ":
        raise ValueError(f"{Path(path).name} is not a DDS file.")

    def u32(o):
        return int.from_bytes(head[o:o + 4], "little")

    height, width = u32(12), u32(16)
    mips = u32(28) if (u32(8) & 0x20000 and u32(28)) else 1
    pf_flags, fourcc = u32(80), head[84:88]
    dxgi, fam = None, None
    if pf_flags & 0x4 and fourcc == b"DX10":
        if len(head) < 148:
            raise ValueError("The DDS header is truncated.")
        if u32(140) > 1:
            raise ValueError("Texture arrays and cubemaps are not supported.")
        dxgi = u32(128)
        fam = FAMILY.get(dxgi)
    elif pf_flags & 0x4:
        fam = FOURCC_FAMILY.get(fourcc)
    elif pf_flags & 0x40 and u32(88) == 32:
        masks = (u32(92), u32(96), u32(100))
        fam = {(0xFF0000, 0xFF00, 0xFF): "BGRA8", (0xFF, 0xFF00, 0xFF0000): "RGBA8"}.get(masks)
    if not fam or not width or not height:
        raise ValueError("This DDS pixel format is not supported (use BC1-BC7, RGBA8 or BGRA8).")
    return {"w": width, "h": height, "family": fam, "mips": mips, "dxgi": dxgi}


def read_dds_info(path: Path):
    d = read_dds_header(path)
    return d["w"], d["h"], d["family"]


def scan_dds(path: Path):
    n = total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.endswith(".dds"):
                    n += 1
                    total += e.stat().st_size
    except OSError:
        pass
    return n, total


class PreviewService(QObject):

    MAX_CACHE_MB = 400

    def __init__(self, parent=None):
        super().__init__(parent)
        loc = QStandardPaths.writableLocation(QStandardPaths.CacheLocation) or str(Path.home() / ".hexon-cache")
        self.cache = Path(loc) / "previews"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.enabled = True
        self.error = ""
        self._proc = None
        self._ready = False
        self._buf = b""
        self._queue = []
        self._inflight = None
        self._seq = 0
        self._failures = 0
        self._prune()

    def request(self, src: Path, px: int, cb, group=None, prio=1):
        if not self.enabled:
            cb(None)
            return
        try:
            dst = self._dst(src, px)
        except OSError:
            cb(None)
            return
        if dst.exists():
            pm = QPixmap(str(dst))
            cb(pm if not pm.isNull() else None)
            return
        if group:
            self._queue = [q for q in self._queue if q["group"] != group]
        for q in self._queue + ([self._inflight] if self._inflight else []):
            if q["dst"] == dst:
                q["cbs"].append(cb)
                return
        self._seq += 1
        self._queue.append({"id": self._seq, "src": src, "dst": dst, "px": px, "cbs": [cb], "group": group, "prio": prio})
        self._pump()

    def clear_cache(self):
        for f in self.cache.glob("*.jpg"):
            try:
                f.unlink()
            except OSError:
                pass

    def shutdown(self):
        if self._proc:
            self._proc.blockSignals(True)
            self._proc.kill()
            self._proc.waitForFinished(500)
            self._proc = None

    def _dst(self, src: Path, px: int) -> Path:
        st = src.stat()
        key = hashlib.sha1(f"{src.name}|{st.st_mtime_ns}|{st.st_size}|{px}".encode()).hexdigest()[:24]
        return self.cache / f"{key}.jpg"

    def _prune(self):
        try:
            files = [(f.stat().st_mtime, f.stat().st_size, f) for f in self.cache.glob("*.jpg")]
        except OSError:
            return
        total, limit = sum(s for _, s, _ in files), self.MAX_CACHE_MB << 20
        if total <= limit:
            return
        for _, size, f in sorted(files, key=lambda t: t[0]):
            try:
                f.unlink()
                total -= size
            except OSError:
                pass
            if total <= limit * 0.7:
                break

    def _start(self) -> bool:
        if self._failures >= 3 or not Path(WORKER_CMD[-1]).exists():
            if not Path(WORKER_CMD[-1]).exists():
                self.error = "The preview helper is missing"
            return False
        p = QProcess(self)
        p.setProgram(WORKER_CMD[0])
        p.setArguments(WORKER_CMD[1:])
        p.readyReadStandardOutput.connect(self._on_out)
        p.finished.connect(self._on_finished)
        p.errorOccurred.connect(self._on_error)
        if sys.platform == "win32":
            try:
                p.setCreateProcessArgumentsModifier(lambda args: setattr(args, "flags", args.flags | 0x08000000))
            except Exception:
                pass
        p.start()
        self._proc, self._ready, self._buf = p, False, b""
        return True

    def _pump(self):
        if self._inflight or not self._queue:
            return
        if self._proc is None and not self._start():
            self._fail_all()
            return
        if not self._ready:
            return
        item = max(self._queue, key=lambda q: (q["prio"], q["id"]))
        self._queue.remove(item)
        self._inflight = item
        msg = {"id": item["id"], "src": str(item["src"]), "dst": str(item["dst"]), "px": item["px"]}
        self._proc.write((json.dumps(msg) + "\n").encode())

    def _on_out(self):
        self._buf += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("ready"):
                self._ready, self._failures, self.error = True, 0, ""
                self._pump()
            elif msg.get("fatal"):
                self.error = msg["fatal"]
                self._failures = 99
            else:
                self._finish(msg)

    def _finish(self, msg):
        item = self._inflight
        if not item or item["id"] != msg.get("id"):
            return
        self._inflight = None
        pm = QPixmap(str(item["dst"])) if msg.get("ok") else None
        for cb in item["cbs"]:
            cb(pm if pm is not None and not pm.isNull() else None)
        self._pump()

    def _on_finished(self, *_):
        self._proc, was_ready = None, self._ready
        self._ready = False
        if not was_ready:
            self._failures += 1
        if self._inflight:
            item, self._inflight = self._inflight, None
            for cb in item["cbs"]:
                cb(None)
        self._pump()

    def _on_error(self, err):
        if err == QProcess.FailedToStart:
            self.error = "Could not start the preview worker (is Python reachable?)"
            self._proc, self._ready, self._failures = None, False, 99
            if self._inflight:
                item, self._inflight = self._inflight, None
                self._queue.insert(0, item)
            self._fail_all()

    def _fail_all(self):
        queue, self._queue = self._queue, []
        for q in queue:
            for cb in q["cbs"]:
                cb(None)


class PreviewBox(QLabel):
    def __init__(self, size: int):
        super().__init__()
        self.setObjectName("preview")
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)

    def message(self, text: str):
        self.setPixmap(QPixmap())
        self.setText(text)

    def image(self, pm, fail_text="No preview"):
        if pm is None or pm.isNull():
            self.message(fail_text)
            return
        self.setText("")
        self.setPixmap(pm.scaled(self.size() - QSize(10, 10), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class Hexon(QMainWindow):
    discord_status = Signal(str)

    def __init__(self, first_run=True, data_dir=None):
        super().__init__()
        self.setWindowTitle("Hexon")
        if LOGO.exists():
            self.setWindowIcon(QIcon(str(LOGO)))
        self.resize(1040, 700)
        self.setAcceptDrops(True)
        self.cfg = QSettings("CELESTARR", "Hexon")
        self.store = ProfileStore(data_dir)
        self.store.load()
        self.core_dll = find_core_dll()
        self._rpc_text = ""
        self.discord_status.connect(self._on_discord_status)
        self.previews = PreviewService(self)
        self.watcher = GameWatcher()
        self.discord = DiscordPresence(on_status=self.discord_status.emit)
        self._started = int(time.time())
        self._textures = []
        self._changed_gen = 0
        self._loading = True
        self._converting = False
        self._tex_dirty = False
        self._dump_count = self._rep_count = self._usage_bytes = 0
        self._last_running = None
        self._sel_timer = QTimer(self, singleShot=True, interval=140)
        self._sel_timer.timeout.connect(self._show_selected_preview)
        self._chg_timer = QTimer(self, singleShot=True, interval=140)
        self._chg_timer.timeout.connect(self._show_changed_preview)

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 12, 18, 14)

        head = QHBoxLayout()
        logo = QLabel()
        if LOGO.exists():
            logo.setPixmap(QIcon(str(LOGO)).pixmap(QSize(32, 32)))
        head.addWidget(logo)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(240)
        self.profile_combo.activated.connect(self._on_profile_chosen)
        head.addSpacing(12)
        head.addWidget(self.profile_combo)
        head.addStretch(1)
        self.header_status = QLabel("")
        self.header_status.setObjectName("muted")
        head.addWidget(self.header_status)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_profile_tab(), "Profiles")
        self.tabs.addTab(self._build_tex_tab(), "Textures")
        self.tabs.addTab(self._build_changed_tab(), "Changed")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.log_tab = self._build_log_tab()
        self.tabs.addTab(self.log_tab, "Log")
        self.tabs.currentChanged.connect(self._on_tab)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1500)
        self.live = QTimer(self)
        self.live.timeout.connect(self._live_tick)
        self.live.start(5000)

        self._load_app_settings()
        self._migrate_legacy_exe()
        self._rebuild_profile_combo()
        self._loading = False
        self._on_profile_changed()
        if first_run:
            QTimer.singleShot(250, self._first_run)

    def _build_profile_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.pf_hint = QLabel("Each game you mod gets its own profile: its own exe, its own dumps and replacements, and its own settings.")
        self.pf_hint.setObjectName("muted")
        self.pf_hint.setWordWrap(True)
        v.addWidget(self.pf_hint)

        f = QFormLayout()
        f.setVerticalSpacing(12)
        self.pf_name = QLineEdit()
        self.pf_name.editingFinished.connect(self._rename_profile)
        f.addRow("Profile name", self.pf_name)
        self.pf_exe = QLineEdit()
        self.pf_exe.setReadOnly(True)
        b_exe = QPushButton("Change…")
        b_exe.clicked.connect(self._change_exe)
        r = QHBoxLayout()
        r.addWidget(self.pf_exe, 1)
        r.addWidget(b_exe)
        f.addRow("Game exe", r)
        self.pf_game = QLineEdit()
        self.pf_game.setPlaceholderText("Detected from the exe")
        self.pf_game.editingFinished.connect(self._profile_game_changed)
        f.addRow("Game name (Discord)", self.pf_game)
        self.pf_status = QLabel("")
        self.pf_status.setWordWrap(True)
        f.addRow("Status", self.pf_status)
        r2 = QHBoxLayout()
        self.btn_install = QPushButton("Install")
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(self._install)
        self.btn_uninstall = QPushButton("Uninstall")
        self.btn_uninstall.clicked.connect(self._uninstall)
        r2.addWidget(self.btn_install)
        r2.addWidget(self.btn_uninstall)
        r2.addStretch(1)
        f.addRow("", r2)
        self.pf_launch = QLabel("")
        self.pf_launch.setObjectName("muted")
        self.pf_launch.setWordWrap(True)
        f.addRow("", self.pf_launch)
        self.pf_warn = QLabel("")
        self.pf_warn.setObjectName("warn")
        self.pf_warn.setWordWrap(True)
        f.addRow("", self.pf_warn)
        v.addLayout(f)

        v.addStretch(1)
        row = QHBoxLayout()
        self.btn_new = QPushButton("Add game…")
        self.btn_new.clicked.connect(self._add_profile)
        self.btn_delete = QPushButton("Delete profile…")
        self.btn_delete.clicked.connect(self._delete_profile)
        b_game = QPushButton("Open game folder")
        b_game.clicked.connect(self._open_game_dir)
        b_hex = QPushButton("Open Hexon folder")
        b_hex.clicked.connect(lambda: self._open(""))
        for b in (self.btn_new, self.btn_delete, b_game, b_hex):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.pf_widgets = (self.pf_name, b_exe, self.pf_game, self.btn_delete, b_game, b_hex)
        return w

    def _build_tex_tab(self):
        w = QWidget()
        outer = QHBoxLayout(w)
        split = QSplitter()
        outer.addWidget(split)

        left = QWidget()
        v = QVBoxLayout(left)
        v.setContentsMargins(0, 0, 8, 0)
        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter (hash, size, format e.g. BC7 or 2048)")
        self.filter.textChanged.connect(self._fill_table)
        self.sort_combo = QComboBox()
        for label in ("Newest first", "Largest first", "Name"):
            self.sort_combo.addItem(label)
        self.sort_combo.currentIndexChanged.connect(self._fill_table)
        b_ref = QPushButton("Refresh")
        b_ref.clicked.connect(self._refresh_tex)
        b_dump = QPushButton("Dump folder")
        b_dump.clicked.connect(lambda: self._open("dump"))
        top.addWidget(self.filter, 1)
        top.addWidget(self.sort_combo)
        top.addWidget(b_ref)
        top.addWidget(b_dump)
        v.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Texture", "Size", "Format", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._sel_timer.start)
        v.addWidget(self.table, 1)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        v.addWidget(self.count)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        self.tex_preview = PreviewBox(320)
        rv.addWidget(self.tex_preview, 0, Qt.AlignHCenter)
        self.tex_info = QLabel("")
        self.tex_info.setObjectName("muted")
        self.tex_info.setAlignment(Qt.AlignHCenter)
        self.tex_info.setWordWrap(True)
        rv.addWidget(self.tex_info)
        b1 = QPushButton("Replace with file…")
        b1.setObjectName("primary")
        b1.clicked.connect(self._replace)
        b2 = QPushButton("Remove replacement")
        b2.clicked.connect(self._unreplace)
        b3 = QPushButton("Open dumped file")
        b3.clicked.connect(self._open_selected)
        for b in (b1, b2, b3):
            rv.addWidget(b)
        tip = QLabel("Tip: drop a .dds or an image onto the window to replace the selected texture.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        tip.setAlignment(Qt.AlignHCenter)
        rv.addWidget(tip)
        rv.addStretch(1)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setSizes([620, 360])
        return w

    def _build_changed_tab(self):
        w = QWidget()
        outer = QHBoxLayout(w)
        split = QSplitter()
        outer.addWidget(split)

        left = QWidget()
        v = QVBoxLayout(left)
        v.setContentsMargins(0, 0, 8, 0)
        self.changed_list = QListWidget()
        self.changed_list.setViewMode(QListWidget.IconMode)
        self.changed_list.setIconSize(QSize(128, 128))
        self.changed_list.setGridSize(QSize(148, 172))
        self.changed_list.setResizeMode(QListWidget.Adjust)
        self.changed_list.setMovement(QListWidget.Static)
        self.changed_list.setWordWrap(True)
        self.changed_list.setUniformItemSizes(True)
        self.changed_list.itemSelectionChanged.connect(self._chg_timer.start)
        v.addWidget(self.changed_list, 1)
        self.changed_count = QLabel("")
        self.changed_count.setObjectName("muted")
        v.addWidget(self.changed_count)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        pair = QHBoxLayout()
        for attr, title in (("chg_orig", "Original"), ("chg_new", "Replacement")):
            col = QVBoxLayout()
            lab = QLabel(title)
            lab.setObjectName("muted")
            lab.setAlignment(Qt.AlignHCenter)
            box = PreviewBox(230)
            setattr(self, attr, box)
            col.addWidget(lab)
            col.addWidget(box)
            pair.addLayout(col)
        rv.addLayout(pair)
        self.chg_info = QLabel("")
        self.chg_info.setObjectName("muted")
        self.chg_info.setAlignment(Qt.AlignHCenter)
        self.chg_info.setWordWrap(True)
        rv.addWidget(self.chg_info)
        b1 = QPushButton("Remove replacement")
        b1.clicked.connect(self._chg_remove)
        b2 = QPushButton("Replace folder")
        b2.clicked.connect(lambda: self._open("replace"))
        rv.addWidget(b1)
        rv.addWidget(b2)
        rv.addStretch(1)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setSizes([520, 480])
        return w

    def _build_settings_tab(self):
        page = QWidget()
        f = QFormLayout(page)
        f.setVerticalSpacing(10)
        f.setContentsMargins(4, 0, 14, 12)
        self.settings_for = QLabel("")
        self.settings_for.setObjectName("muted")
        self.settings_for.setWordWrap(True)
        f.addRow(self.settings_for)

        def section(text):
            lab = QLabel(text.upper())
            lab.setObjectName("section")
            f.addRow(lab)

        def note(text):
            lab = QLabel(text)
            lab.setObjectName("muted")
            lab.setWordWrap(True)
            f.addRow(lab)

        def line(placeholder=""):
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            return e

        def check(text, on=True):
            c = QCheckBox(text)
            c.setChecked(on)
            return c

        section("Texture dumping")
        self.chk_dump = check("Dump textures while the game runs")
        f.addRow(self.chk_dump)
        self.spin_gb = QDoubleSpinBox()
        self.spin_gb.setRange(0.5, 2000.0)
        self.spin_gb.setSingleStep(0.5)
        self.spin_gb.setDecimals(1)
        self.spin_gb.setSuffix(" GB")
        self.spin_gb.setValue(4.0)
        f.addRow("Dump limit on this PC", self.spin_gb)
        self.usage_bar = QProgressBar()
        self.usage_bar.setTextVisible(False)
        self.usage_label = QLabel("")
        self.usage_label.setObjectName("muted")
        f.addRow("", self.usage_bar)
        f.addRow("", self.usage_label)
        b_clear = QPushButton("Clear dump folder…")
        b_clear.clicked.connect(self._clear_dump)
        f.addRow("", b_clear)
        self.spin_min = QSpinBox()
        self.spin_min.setRange(4, 8192)
        self.spin_min.setValue(64)
        self.spin_min.setSuffix(" px")
        f.addRow("Don't dump textures smaller than", self.spin_min)
        note("This only limits what gets dumped. Replacements apply to textures of any size.")

        section("Replacements")
        self.chk_rep = check("Apply replacements")
        f.addRow(self.chk_rep)
        self.chk_mips = check("Apply mip chains (experimental)")
        self.chk_mips.setToolTip("When a replacement DDS has mip levels, the smaller levels of that texture are replaced too.")
        f.addRow(self.chk_mips)
        self.texconv_edit = line("Optional: path to texconv.exe (lets you replace with PNG / JPG)")
        b_tc = QPushButton("Browse")
        b_tc.clicked.connect(self._browse_texconv)
        r_tc = QHBoxLayout()
        r_tc.addWidget(self.texconv_edit, 1)
        r_tc.addWidget(b_tc)
        f.addRow("texconv", r_tc)
        self.texconv_status = QLabel("")
        self.texconv_status.setObjectName("muted")
        self.texconv_status.setWordWrap(True)
        f.addRow("", self.texconv_status)
        self.chk_genmips = check("Generate a mip chain when converting images")
        f.addRow(self.chk_genmips)
        note("Game options apply the next time the game starts.")

        section("Previews")
        self.chk_prev = check("Show texture previews")
        f.addRow(self.chk_prev)
        self.combo_px = QComboBox()
        for label, px in (("Small (256 px)", 256), ("Medium (384 px)", 384), ("Large (512 px)", 512)):
            self.combo_px.addItem(label, px)
        self.combo_px.setCurrentIndex(1)
        f.addRow("Preview quality", self.combo_px)
        b_cache = QPushButton("Clear preview cache")
        b_cache.clicked.connect(self._clear_cache)
        f.addRow("", b_cache)
        note("Previews are decoded in a background process at low priority and cached.")

        section("Discord Rich Presence")
        self.chk_rpc = check("Show my status on Discord while Hexon is open")
        f.addRow(self.chk_rpc)
        self.rpc_status = QLabel("")
        self.rpc_status.setObjectName("muted")
        self.rpc_status.setWordWrap(True)
        f.addRow("", self.rpc_status)
        note("What to show:")
        self.chk_rpc_game = check("Game I'm modding")
        self.chk_rpc_tab = check("What I'm doing (current tab)")
        self.chk_rpc_dumped = check("Textures dumped")
        self.chk_rpc_replaced = check("Textures replaced")
        self.chk_rpc_usage = check("Dump disk usage")
        self.chk_rpc_running = check("Whether the game is running")
        self.chk_rpc_elapsed = check("Time since Hexon opened")
        for c in (self.chk_rpc_game, self.chk_rpc_tab, self.chk_rpc_dumped, self.chk_rpc_replaced,
                  self.chk_rpc_usage, self.chk_rpc_running, self.chk_rpc_elapsed):
            f.addRow(c)

        section("Interface")
        self.chk_log = check("Show Log tab", False)
        f.addRow(self.chk_log)
        self.chk_verbose = check("Verbose logging in the game (for troubleshooting)", False)
        f.addRow(self.chk_verbose)
        b_data = QPushButton("Open Hexon data folder")
        b_data.clicked.connect(self._open_data_dir)
        f.addRow("", b_data)
        about = QLabel(f"Hexon {VERSION}")
        about.setObjectName("muted")
        f.addRow(about)

        self._persist = {
            "show_log": (self.chk_log, False), "previews": (self.chk_prev, True),
            "texconv": (self.texconv_edit, ""), "genmips": (self.chk_genmips, True),
            "rpc_enabled": (self.chk_rpc, True),
            "rpc_game": (self.chk_rpc_game, True), "rpc_tab": (self.chk_rpc_tab, True),
            "rpc_dumped": (self.chk_rpc_dumped, True), "rpc_replaced": (self.chk_rpc_replaced, True),
            "rpc_usage": (self.chk_rpc_usage, True), "rpc_running": (self.chk_rpc_running, True),
            "rpc_elapsed": (self.chk_rpc_elapsed, True),
        }
        for w, _ in self._persist.values():
            (w.toggled if isinstance(w, QCheckBox) else w.editingFinished).connect(self._settings_changed)
        for sig in (self.chk_dump.toggled, self.chk_rep.toggled, self.chk_mips.toggled, self.chk_verbose.toggled,
                    self.spin_gb.valueChanged, self.spin_min.valueChanged, self.combo_px.currentIndexChanged):
            sig.connect(self._settings_changed)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _build_log_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        v.addWidget(self.log)
        return w

    def profile(self):
        return self.store.current

    def exe(self):
        p = self.profile()
        return p.exe_path if p else None

    def hexon_dir(self):
        p = self.profile()
        return p.hexon_dir if p and p.exe_path else None

    def _open(self, sub):
        d = self.hexon_dir()
        if d:
            target = d / sub if sub else d
            target.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_game_dir(self):
        p = self.profile()
        if p and p.game_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.game_dir)))

    def _open_data_dir(self):
        self.store.dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.dir)))

    def _migrate_legacy_exe(self):
        legacy = self.cfg.value("exe", "", type=str)
        if legacy and not self.store.profiles and Path(legacy).suffix.lower() == ".exe" and Path(legacy).is_file():
            try:
                self.store.add(legacy, settings=read_ini(Path(legacy).parent))
            except ValueError:
                pass
        self.cfg.remove("exe")

    def _rebuild_profile_combo(self):
        c = self.profile_combo
        c.blockSignals(True)
        c.clear()
        for p in self.store.profiles:
            c.addItem(p.name, p.id)
        c.addItem("+  Add game…", None)
        idx = next((i for i, p in enumerate(self.store.profiles) if p.id == self.store.active), -1)
        c.setCurrentIndex(idx if idx >= 0 else c.count() - 1)
        c.blockSignals(False)

    def _on_profile_chosen(self, index):
        pid = self.profile_combo.itemData(index)
        if pid is None:
            self._add_profile()
            self._rebuild_profile_combo()
            return
        if pid != self.store.active:
            self.store.active = pid
            self.store.save()
            self._on_profile_changed()

    def _apply_profile_settings(self):
        p = self.profile()
        was, self._loading = self._loading, True
        try:
            s = p.settings if p else {}
            self.chk_dump.setChecked(s.get("dump", True))
            self.chk_rep.setChecked(s.get("replace", True))
            self.chk_mips.setChecked(s.get("mips", True))
            self.chk_verbose.setChecked(s.get("verbose", False))
            self.spin_min.setValue(int(s.get("min_dim", 64)))
            self.spin_gb.setValue(float(s.get("dump_gb", 4.0)))
        finally:
            self._loading = was

    def _collect_profile_settings(self):
        return {"dump": self.chk_dump.isChecked(), "replace": self.chk_rep.isChecked(), "mips": self.chk_mips.isChecked(),
                "verbose": self.chk_verbose.isChecked(), "min_dim": self.spin_min.value(), "dump_gb": self.spin_gb.value()}

    def _on_profile_changed(self):
        p = self.profile()
        has = p is not None
        for w in (self.chk_dump, self.chk_rep, self.chk_mips, self.chk_verbose, self.spin_min, self.spin_gb):
            w.setEnabled(has)
        for w in self.pf_widgets:
            w.setEnabled(has)
        self._apply_profile_settings()
        was, self._loading = self._loading, True
        self.pf_name.setText(p.name if p else "")
        self.pf_exe.setText(p.exe if p else "")
        self.pf_game.setText(p.game_name if p else "")
        self._loading = was
        self.settings_for.setText(f"Dump and replace options below apply to the profile: {p.name}." if p
                                  else "Add a game on the Profiles tab to change these options.")
        self.watcher.set_exe(Path(p.exe).name if p else "")
        self._rebuild_profile_combo()
        self._update_status()
        self._refresh_tex()
        self._refresh_changed()
        self._update_usage()
        self._push_presence()

    def _update_status(self):
        p = self.profile()
        running = bool(self.watcher.running)
        if not p:
            self.pf_status.setText("No game yet. Use Add game… to create your first profile.")
            self.pf_launch.setText("")
            self.pf_warn.setText("")
            self.btn_install.setEnabled(False)
            self.btn_uninstall.setEnabled(False)
            self.header_status.setText("")
            return
        state = dll_state(p, self.core_dll)
        text = {NOT_INSTALLED: "Hexon is not installed in this game.", CURRENT: "Hexon is installed.",
                OUTDATED: "Hexon is installed, but an update is available.",
                FOREIGN: "The game folder already has a different dxgi.dll (another mod such as ReShade).",
                NO_EXE: "The game exe can't be found. Use Change… to point to it."}[state]
        if self.core_dll is None:
            text += " Hexon's proxy DLL is missing from this installation, so it can't be installed. Reinstall Hexon."
        if running:
            text += " The game is running, so close it before installing or removing."
        self.pf_status.setText(text)
        self.btn_install.setText("Update" if state == OUTDATED else "Install")
        self.btn_install.setEnabled(state in (NOT_INSTALLED, OUTDATED, FOREIGN) and not running and self.core_dll is not None)
        self.btn_uninstall.setEnabled(state in (CURRENT, OUTDATED) and not running)
        self.header_status.setText({CURRENT: "Installed", OUTDATED: "Update available", NOT_INSTALLED: "Not installed",
                                    FOREIGN: "Not installed", NO_EXE: "Exe missing"}[state] + ("  ·  game running" if running else ""))
        self.pf_launch.setText(last_launch_summary(p)[1] if state in (CURRENT, OUTDATED) else "")
        found = detect_anticheat(p.game_dir) if state != NO_EXE else []
        self.pf_warn.setText(("Anti-cheat found in this game: " + ", ".join(found) + ". Using Hexon with online anti-cheat can get "
                              "your account banned.") if found else "")

    def _ask(self, title, text, yes="Continue", default_yes=False):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        y = box.addButton(yes, QMessageBox.AcceptRole)
        n = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(y if default_yes else n)
        box.exec()
        return box.clickedButton() is y

    def _install(self):
        p = self.profile()
        if not p:
            return
        if self.watcher.running:
            QMessageBox.information(self, "Hexon", "Close the game first, then try again.")
            return
        state = dll_state(p, self.core_dll)
        if state == NOT_INSTALLED or state == FOREIGN:
            found = detect_anticheat(p.game_dir)
            if found and not self._ask(
                    "Anti-cheat detected",
                    f"This game folder contains {', '.join(found)}.\n\nHexon changes what the game draws from inside the game "
                    "process. With online anti-cheat that can get your account banned.\n\nOnly continue for an offline or "
                    "unprotected copy of the game."):
                return
        res = install_dll(p, self.core_dll)
        if res.kind == "confirm":
            if not self._ask("Replace dxgi.dll?",
                             "The game folder already contains a dxgi.dll that isn't Hexon's, probably from another mod "
                             "such as ReShade.\n\nHexon can replace it. Your original is kept as dxgi.dll.hexon-backup and "
                             "is put back when you uninstall Hexon from this game (that mod won't work while Hexon is installed).",
                             yes="Replace it"):
                return
            res = install_dll(p, self.core_dll, replace_foreign=True)
        if res.kind == "error":
            QMessageBox.warning(self, "Hexon", res.message)
        else:
            try:
                write_ini(p)
            except OSError as e:
                QMessageBox.warning(self, "Hexon", f"Installed, but couldn't write the settings file: {e}")
            self.store.save()
        self._update_status()
        if res.kind == "ok":
            self.pf_status.setText(self.pf_status.text() + "  " + res.message)

    def _uninstall(self):
        p = self.profile()
        if not p:
            return
        res = uninstall_dll(p)
        self.store.save()
        if res.kind == "error":
            QMessageBox.warning(self, "Hexon", res.message)
        self._update_status()
        if res.kind != "error":
            self.pf_status.setText(self.pf_status.text() + "  " + res.message)

    def _first_run(self):
        if self.cfg.value("notice_accepted", "", type=str) != VERSION.split(".")[0]:
            if not self._ask_notice():
                self.close()
                return
            self.cfg.setValue("notice_accepted", VERSION.split(".")[0])
        if not self.store.profiles:
            self._add_profile()

    def _ask_notice(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Before you start")
        box.setText("Hexon replaces game textures by hooking DirectX 12 inside the game's process.\n\n"
                    "Only use it with offline or unprotected games. In games with anti-cheat (BattlEye, Easy Anti-Cheat and "
                    "similar) it can get your account banned. You use Hexon at your own risk.")
        ok = box.addButton("I understand", QMessageBox.AcceptRole)
        box.addButton("Quit", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is ok

    def _pick_exe(self, title):
        path, _ = QFileDialog.getOpenFileName(self, title, "", "Games (*.exe)")
        if not path:
            return None
        problem = bitness_problem(path)
        if problem:
            QMessageBox.warning(self, "Hexon", problem)
            return None
        return Path(path)

    def _add_profile(self):
        exe = self._pick_exe("Choose the game's .exe")
        if not exe:
            return
        try:
            p = self.store.add(exe, settings=read_ini(exe.parent))
        except ValueError as e:
            QMessageBox.warning(self, "Hexon", str(e))
            return
        self._on_profile_changed()
        self.tabs.setCurrentIndex(TAB_PROFILES)
        if dll_state(p, self.core_dll) in (NOT_INSTALLED, FOREIGN) and self.core_dll:
            if QMessageBox.question(self, "Hexon", f"Install Hexon into {p.name} now?") == QMessageBox.Yes:
                self._install()

    def _delete_profile(self):
        p = self.profile()
        if not p:
            return
        if QMessageBox.question(self, "Hexon", f"Delete the profile \"{p.name}\"?\n\nIf Hexon is installed in that game it is "
                                "removed first. Your dumped and replaced textures stay in the game's hexon folder.") != QMessageBox.Yes:
            return
        if dll_state(p, self.core_dll) in (CURRENT, OUTDATED):
            res = uninstall_dll(p)
            if res.kind == "error":
                QMessageBox.warning(self, "Hexon", res.message)
                return
        self.store.remove(p.id)
        self._on_profile_changed()

    def _rename_profile(self):
        p = self.profile()
        name = self.pf_name.text().strip()
        if self._loading or not p or not name or name == p.name:
            return
        p.name = name
        self.store.save()
        self._on_profile_changed()

    def _profile_game_changed(self):
        p = self.profile()
        if self._loading or not p or self.pf_game.text().strip() == p.game_name:
            return
        p.game_name = self.pf_game.text().strip()
        self.store.save()
        self._push_presence()

    def _change_exe(self):
        p = self.profile()
        if not p:
            return
        if dll_state(p, self.core_dll) in (CURRENT, OUTDATED):
            QMessageBox.information(self, "Hexon", "Uninstall Hexon from the current game first, then change the exe.")
            return
        exe = self._pick_exe("Choose the game's .exe")
        if not exe:
            return
        other = self.store.by_exe(exe)
        if other and other.id != p.id:
            QMessageBox.warning(self, "Hexon", f"The profile \"{other.name}\" already uses that exe.")
            return
        p.exe = str(exe)
        self.store.save()
        self._on_profile_changed()

    def _load_app_settings(self):
        for key, (w, default) in self._persist.items():
            if isinstance(w, QCheckBox):
                w.setChecked(self.cfg.value(key, default, type=bool))
            else:
                w.setText(self.cfg.value(key, default, type=str))
        idx = self.combo_px.findData(self.cfg.value("preview_px", 384, type=int))
        self.combo_px.setCurrentIndex(idx if idx >= 0 else 1)
        self._apply_effects()
        self._refresh_texconv_status()

    def _save_app_settings(self):
        for key, (w, _) in self._persist.items():
            self.cfg.setValue(key, w.isChecked() if isinstance(w, QCheckBox) else w.text().strip())
        self.cfg.setValue("preview_px", self.combo_px.currentData())

    def _apply_effects(self):
        self.tabs.setTabVisible(self.tabs.indexOf(self.log_tab), self.chk_log.isChecked())
        self.previews.enabled = self.chk_prev.isChecked()

    def _settings_changed(self, *_):
        if self._loading:
            return
        self._save_app_settings()
        self._apply_effects()
        p = self.profile()
        if p:
            p.settings = self._collect_profile_settings()
            self.store.save()
            if p.exe_path:
                try:
                    write_ini(p)
                except OSError:
                    pass
        self._update_usage()
        self._refresh_texconv_status()
        self._show_selected_preview()
        self._show_changed_preview()
        self._push_presence()

    def _update_usage(self):
        d = self.hexon_dir()
        if not d:
            self.usage_bar.setValue(0)
            self.usage_label.setText("Select the game exe to see dump usage.")
            return
        used, limit = dir_size(d / "dump"), self.spin_gb.value() * GB
        self.usage_bar.setValue(int(min(100, used / limit * 100)))
        self.usage_label.setText(f"{human(used)} used of {self.spin_gb.value():.1f} GB"
                                 + ("  (limit reached, no new dumps)" if used >= limit else ""))

    def _clear_dump(self):
        d = self.hexon_dir()
        if not d or not (d / "dump").exists():
            return
        if QMessageBox.question(self, "Hexon", "Delete every dumped texture? Your replacements are kept.") != QMessageBox.Yes:
            return
        for f in [*(d / "dump").glob("*.dds"), d / "dump" / INDEX_NAME]:
            try:
                f.unlink()
            except OSError:
                pass
        self._refresh_tex()
        self._update_usage()

    def _clear_cache(self):
        self.previews.clear_cache()
        self._refresh_changed()
        self._show_selected_preview()

    def _on_tab(self, i):
        w = self.tabs.widget(i)
        if w is self.tabs.widget(TAB_TEXTURES) and self._tex_dirty:
            self._refresh_tex()
        elif w is self.tabs.widget(TAB_CHANGED):
            self._refresh_changed()
        elif w is self.tabs.widget(TAB_SETTINGS):
            self._update_usage()
            self._refresh_texconv_status()
        self._push_presence()

    def _rep_dir(self):
        d = self.hexon_dir()
        return d / "replace" if d else None

    def _rep_names(self):
        r = self._rep_dir()
        try:
            return {p.name for p in r.glob("*.dds")} if r and r.exists() else set()
        except OSError:
            return set()

    def _refresh_tex(self):
        d = self.hexon_dir()
        self._textures = []
        if d and (d / "dump").exists():
            with os.scandir(d / "dump") as it:
                for e in it:
                    m = NAME_RE.match(e.name)
                    if not m:
                        continue
                    st = e.stat()
                    self._textures.append({
                        "name": e.name, "hash": m.group(1), "size": f"{m.group(2)}x{m.group(3)}",
                        "fmt": m.group(4), "bytes": st.st_size, "mtime": st.st_mtime,
                        "px": int(m.group(2)) * int(m.group(3)),
                        "search": f"{m.group(1)} {m.group(2)}x{m.group(3)} {m.group(4)}".lower()})
        self._dump_count = len(self._textures)
        self._usage_bytes = sum(t["bytes"] for t in self._textures)
        self._tex_dirty = False
        self._fill_table()

    def _fill_table(self, *_):
        needle = self.filter.text().strip().lower()
        rep = self._rep_names()
        self._rep_count = len(rep)
        sel = self._selected_name()
        scroll = self.table.verticalScrollBar().value()
        rows = [t for t in self._textures if not needle or needle in t["search"]]
        mode = self.sort_combo.currentIndex()
        rows.sort(key=(lambda t: -t["mtime"]) if mode == 0 else (lambda t: (-t["px"], t["name"])) if mode == 1
                  else (lambda t: t["name"]))
        shown = rows[:MAX_ROWS]
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(len(shown))
        keep_row = None
        for i, t in enumerate(shown):
            if t["name"] == sel:
                keep_row = i
            for c, text in enumerate((t["hash"], t["size"], t["fmt"], "Replaced" if t["name"] in rep else "")):
                it = QTableWidgetItem(text)
                it.setData(Qt.UserRole, t["name"])
                self.table.setItem(i, c, it)
        if keep_row is not None:
            self.table.selectRow(keep_row)
        self.table.verticalScrollBar().setValue(scroll)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        extra = f"  (showing first {MAX_ROWS}, use the filter to narrow)" if len(rows) > MAX_ROWS else ""
        self.count.setText(f"{len(rows):,} matching / {len(self._textures):,} dumped{extra}")
        self._show_selected_preview()

    def _selected_name(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 and self.table.selectedItems() else None
        return it.data(Qt.UserRole) if it else None

    def _show_selected_preview(self):
        name, d = self._selected_name(), self.hexon_dir()
        if not name or not d:
            self.tex_preview.message("Select a texture")
            self.tex_info.setText("")
            return
        m = NAME_RE.match(name)
        src = d / "dump" / name
        try:
            size = human(src.stat().st_size)
        except OSError:
            size = "?"
        status = ""
        if (d / "replace" / name).exists():
            try:
                n = read_dds_header(d / "replace" / name)["mips"]
                status = f"  ·  replaced ({n} mip level{'s' if n != 1 else ''})"
            except (ValueError, OSError):
                status = "  ·  replaced (file unreadable)"
        self.tex_info.setText(f"{m.group(2)}x{m.group(3)}  {m.group(4)}  ·  {size}{status}\n{m.group(1)}")
        if not self.previews.enabled:
            self.tex_preview.message("Previews are off (Settings)")
            return
        self.tex_preview.message("Loading…")

        def done(pm, name=name):
            if self._selected_name() == name:
                self.tex_preview.image(pm, self.previews.error or "No preview")
        self.previews.request(src, self.combo_px.currentData(), done, group="sel")

    def _replace(self):
        name = self._selected_name()
        if not name or not self.hexon_dir():
            QMessageBox.information(self, "Hexon", "Select a texture first.")
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "Choose a replacement (DDS or image)", "",
            "Textures (*.dds *.png *.jpg *.jpeg *.tga *.bmp *.tif *.tiff);;DDS (*.dds);;"
            "Images (*.png *.jpg *.jpeg *.tga *.bmp *.tif *.tiff)")
        if src:
            self._replace_with_file(name, Path(src))

    def _apply_dds(self, name: str, src: Path):
        d = self.hexon_dir()
        m = NAME_RE.match(name)
        w, h, fam = int(m.group(2)), int(m.group(3)), m.group(4)
        try:
            hdr = read_dds_header(src)
        except (ValueError, OSError) as e:
            return str(e)
        if (hdr["w"], hdr["h"], hdr["family"]) != (w, h, fam):
            return (f"{src.name} must be {w}x{h} {fam}, but it is {hdr['w']}x{hdr['h']} {hdr['family']}. "
                    "Use an image instead and Hexon can resize and convert it (needs texconv).")
        dest = d / "replace" / name
        try:
            if not (dest.exists() and src.resolve() == dest.resolve()):
                atomic_copy(src, dest)
        except OSError as e:
            return f"Couldn't copy {src.name}: {e}"
        return None

    def _replace_with_file(self, name: str, src: Path):
        if self._converting:
            QMessageBox.information(self, "Hexon", "Still converting the previous image, one moment.")
            return
        ext = src.suffix.lower()
        if ext == ".dds":
            err = self._apply_dds(name, src)
            if err:
                QMessageBox.warning(self, "Hexon", err)
            self._after_replace()
        elif ext in IMAGE_EXTS:
            self._convert_image(name, src)
        else:
            QMessageBox.information(self, "Hexon", "Use a .dds file or an image (png, jpg, tga, bmp, tif).")

    def _after_replace(self):
        self._fill_table()
        if self.tabs.currentIndex() == TAB_CHANGED:
            self._refresh_changed()
        self._push_presence()

    def _texconv_path(self):
        p = self.texconv_edit.text().strip().strip('"')
        if p and Path(p).is_file():
            return Path(p)
        local = EXE_DIR / "texconv.exe"
        found = str(local) if local.exists() else shutil.which("texconv")
        return Path(found) if found else None

    def _refresh_texconv_status(self):
        tc = self._texconv_path()
        self.texconv_status.setText(
            f"Found: {tc}" if tc else "Not found. Download texconv.exe from github.com/microsoft/DirectXTex/releases "
                                      "and browse to it, or put it in the Hexon folder.")

    def _browse_texconv(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select texconv.exe", self.texconv_edit.text(), "texconv (texconv*);;All files (*)")
        if p:
            self.texconv_edit.setText(p)
            self._settings_changed()

    def _convert_image(self, name: str, src: Path):
        tc = self._texconv_path()
        if not tc:
            QMessageBox.information(
                self, "Hexon",
                "Replacing with an image needs texconv (Microsoft's DirectXTex tool).\n\n"
                "Download texconv.exe from github.com/microsoft/DirectXTex/releases, then set its path in "
                "Settings > Replacements (or put it in the Hexon folder).\n\nOr convert the image yourself and pick the .dds.")
            return
        d = self.hexon_dir()
        m = NAME_RE.match(name)
        w, h, fam = int(m.group(2)), int(m.group(3)), m.group(4)
        try:
            code = read_dds_header(d / "dump" / name)["dxgi"]
        except (ValueError, OSError):
            code = None
        fmt = TEXCONV_FORMAT.get(code) or FAMILY_TEXCONV.get(fam)
        if not fmt:
            QMessageBox.warning(self, "Hexon", f"Don't know how to convert to {fam}.")
            return
        tmp = Path(tempfile.mkdtemp(prefix="hexon_"))
        args = ["-nologo", "-y", "-f", fmt, "-m", "0" if self.chk_genmips.isChecked() else "1",
                "-w", str(w), "-h", str(h), "-dx10", "-o", str(tmp)]
        if fmt.endswith("_SRGB"):
            args.append("-srgb")
        args.append(str(src))

        proc = QProcess(self)
        proc.setProgram(str(tc))
        proc.setArguments(args)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        if sys.platform == "win32":
            try:
                proc.setCreateProcessArgumentsModifier(lambda a: setattr(a, "flags", a.flags | 0x08000000))
            except Exception:
                pass
        state = {"done": False}

        def finish(error_text=None):
            if state["done"]:
                return
            state["done"] = True
            self._converting = False
            out = bytes(proc.readAllStandardOutput()).decode(errors="replace").strip()
            produced = tmp / (src.stem + ".dds")
            err = error_text
            if err is None and (proc.exitStatus() != QProcess.NormalExit or proc.exitCode() != 0 or not produced.exists()):
                err = "texconv could not convert this image.\n\n" + out[-600:]
            if err is None:
                err = self._apply_dds(name, produced)
            shutil.rmtree(tmp, ignore_errors=True)
            proc.deleteLater()
            if err:
                QMessageBox.warning(self, "Hexon", err)
            self._after_replace()

        proc.finished.connect(lambda *_: finish())
        proc.errorOccurred.connect(lambda e: finish(f"Couldn't start texconv ({tc})") if e == QProcess.FailedToStart else None)
        self._converting = True
        self.tex_info.setText(f"Converting {src.name} to {w}x{h} {fmt}…")
        proc.start()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in IMAGE_EXTS | {".dds"}
                                          for u in e.mimeData().urls() if u.isLocalFile()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        d = self.hexon_dir()
        files = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        files = [f for f in files if f.suffix.lower() in IMAGE_EXTS | {".dds"}]
        if not files or not d:
            return
        e.acceptProposedAction()
        named = [f for f in files if f.suffix.lower() == ".dds" and NAME_RE.match(f.name) and (d / "dump" / f.name).exists()]
        if named and len(named) == len(files):
            errs = [err for f in named if (err := self._apply_dds(f.name, f))]
            self._after_replace()
            msg = f"Replaced {len(named) - len(errs)} of {len(named)} texture(s)."
            if errs:
                msg += "\n\n" + "\n".join(errs[:8])
            QMessageBox.information(self, "Hexon", msg)
            return
        if len(files) != 1:
            QMessageBox.information(self, "Hexon", "Drop one file at a time, or several .dds files that are already named like the dumped textures.")
            return
        name = self._selected_name()
        if not name:
            self.tabs.setCurrentIndex(TAB_TEXTURES)
            QMessageBox.information(self, "Hexon", "Select a texture in the list first, then drop the file.")
            return
        self._replace_with_file(name, files[0])

    def _unreplace(self):
        self._remove_replacement(self._selected_name())

    def _remove_replacement(self, name):
        d = self.hexon_dir()
        if name and d and (d / "replace" / name).exists():
            (d / "replace" / name).unlink()
            self._fill_table()
            self._refresh_changed()

    def _open_selected(self):
        name, d = self._selected_name(), self.hexon_dir()
        if name and d:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d / "dump" / name)))

    def _refresh_changed(self):
        self._changed_gen += 1
        gen = self._changed_gen
        self.changed_list.clear()
        r = self._rep_dir()
        files = []
        if r and r.exists():
            files = [p for p in r.glob("*.dds") if NAME_RE.match(p.name)]
            files.sort(key=lambda p: -p.stat().st_mtime)
        placeholder = QPixmap(128, 128)
        placeholder.fill(Qt.transparent)
        for p in files:
            m = NAME_RE.match(p.name)
            item = QListWidgetItem(QIcon(placeholder), f"{m.group(1)[:8]}…\n{m.group(2)}x{m.group(3)} {m.group(4)}")
            item.setData(Qt.UserRole, p.name)
            item.setTextAlignment(Qt.AlignHCenter)
            self.changed_list.addItem(item)

            def done(pm, item=item, gen=gen):
                if gen == self._changed_gen and pm is not None:
                    try:
                        item.setIcon(QIcon(pm))
                    except RuntimeError:
                        pass
            self.previews.request(p, 128, done, prio=0)
        self.changed_count.setText(f"{len(files)} replaced texture{'s' if len(files) != 1 else ''}")
        self.chg_orig.message("")
        self.chg_new.message("")
        self.chg_info.setText("Select a replaced texture to compare." if files else
                              "Nothing replaced yet. Pick a texture in the Textures tab and use Replace with DDS.")

    def _changed_name(self):
        it = self.changed_list.currentItem()
        return it.data(Qt.UserRole) if it and self.changed_list.selectedItems() else None

    def _show_changed_preview(self):
        name, d = self._changed_name(), self.hexon_dir()
        if not name or not d:
            return
        m = NAME_RE.match(name)
        mips = ""
        try:
            n = read_dds_header(d / "replace" / name)["mips"]
            mips = f"  ·  {n} mip level{'s' if n != 1 else ''}"
        except (ValueError, OSError):
            pass
        self.chg_info.setText(f"{m.group(2)}x{m.group(3)}  {m.group(4)}{mips}\n{m.group(1)}")
        if not self.previews.enabled:
            self.chg_orig.message("Previews are off (Settings)")
            self.chg_new.message("Previews are off (Settings)")
            return
        for box, src, group in ((self.chg_orig, d / "dump" / name, "chg_o"), (self.chg_new, d / "replace" / name, "chg_n")):
            if not src.exists():
                box.message("Not in the dump folder" if box is self.chg_orig else "Missing")
                continue
            box.message("Loading…")

            def done(pm, box=box, name=name):
                if self._changed_name() == name:
                    box.image(pm, self.previews.error or "No preview")
            self.previews.request(src, 256, done, group=group)

    def _chg_remove(self):
        self._remove_replacement(self._changed_name())

    def _game_name(self) -> str:
        p = self.profile()
        if not p:
            return ""
        return p.game_name or guess_game_name(p.exe)

    def _presence_payload(self):
        if not self.chk_rpc.isChecked():
            return None

        def clip(text, n=120):
            text = " ".join(str(text).split())
            return text[:n]

        game = self._game_name()
        if self.chk_rpc_game.isChecked() and game:
            details = f"Modding {game}"
        else:
            details = "Using Hexon"

        running = self.watcher.running
        parts = []
        if self.chk_rpc_tab.isChecked():
            parts.append(TAB_ACTIVITY[min(self.tabs.currentIndex(), len(TAB_ACTIVITY) - 1)])
        if self.chk_rpc_dumped.isChecked():
            parts.append(f"{self._dump_count:,} dumped")
        if self.chk_rpc_replaced.isChecked():
            parts.append(f"{self._rep_count:,} replaced")
        if self.chk_rpc_usage.isChecked():
            parts.append(f"{self._usage_bytes / GB:.1f} / {self.spin_gb.value():.1f} GB")
        if self.chk_rpc_running.isChecked() and running:
            parts.append("Game running")

        payload = {"details": clip(details) if len(details) >= 2 else "Using Hexon",
                   "large_image": DISCORD_LARGE_IMAGE,
                   "large_text": f"Hexon {VERSION}"}
        state = clip(" · ".join(parts))
        if len(state) >= 2:
            payload["state"] = state
        if self.chk_rpc_elapsed.isChecked():
            payload["start"] = self._started
        payload["buttons"] = [dict(DISCORD_BUTTON)]
        return payload

    def _push_presence(self):
        self.discord.configure(DISCORD_APP_ID, self._presence_payload())

    def _on_discord_status(self, text: str):
        self._rpc_text = text
        self._refresh_rpc_label()

    def _refresh_rpc_label(self):
        if hasattr(self, "rpc_status"):
            self.rpc_status.setText(self._rpc_text)

    def _live_tick(self):
        running = self.watcher.running
        if running != self._last_running:
            self._last_running = running
            self._update_status()
        d = self.hexon_dir()
        if d:
            count, size = scan_dds(d / "dump")
            self._usage_bytes = size
            self._rep_count = scan_dds(d / "replace")[0]
            if count != self._dump_count:
                self._dump_count = count
                if self.tabs.currentIndex() == TAB_TEXTURES:
                    self._refresh_tex()
                else:
                    self._tex_dirty = True
            if self.tabs.currentIndex() == TAB_SETTINGS:
                self._update_usage()
        self._push_presence()

    def _tick(self):
        if not self.chk_log.isChecked() or self.tabs.currentWidget() is not self.log_tab:
            return
        d = self.hexon_dir()
        lf = d / "hexon.log" if d else None
        if lf and lf.exists():
            lines = lf.read_text(errors="replace").splitlines()[-300:]
            text = "\n".join(lines)
            if text != self.log.toPlainText():
                self.log.setPlainText(text)
                self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def closeEvent(self, e):
        self.previews.shutdown()
        self.discord.shutdown()
        self.watcher.shutdown()
        super().closeEvent(e)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CELESTARR.Hexon")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setOrganizationName("CELESTARR")
    app.setApplicationName("Hexon")
    if LOGO.exists():
        app.setWindowIcon(QIcon(str(LOGO)))
    app.setStyleSheet(stylesheet())
    win = Hexon()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
