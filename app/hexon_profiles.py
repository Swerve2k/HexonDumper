import json
import os
import re
import struct
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

DLL_NAME = "dxgi.dll"
BACKUP_NAME = "dxgi.dll.hexon-backup"
MARKER_RE = re.compile(rb"HEXON-PROXY-DLL:([0-9A-Za-z.\-]+)")

NOT_INSTALLED, CURRENT, OUTDATED, FOREIGN, NO_EXE = "not_installed", "current", "outdated", "foreign", "no_exe"

DEFAULT_SETTINGS = {"dump": True, "replace": True, "mips": True, "verbose": False, "min_dim": 64, "dump_gb": 4.0}

ANTICHEAT_FILES = {
    "battleye": "BattlEye", "beservice.exe": "BattlEye", "beservice_x64.exe": "BattlEye",
    "beclient.dll": "BattlEye", "beclient_x64.dll": "BattlEye",
    "easyanticheat": "Easy Anti-Cheat", "easyanticheat_eos": "Easy Anti-Cheat",
    "easyanticheat_setup.exe": "Easy Anti-Cheat", "easyanticheat_eos_setup.exe": "Easy Anti-Cheat",
    "gameguard": "GameGuard", "npggnt.des": "GameGuard",
    "xigncode": "XIGNCODE3", "x3.xem": "XIGNCODE3",
    "pnkbstra.exe": "PunkBuster", "pnkbstrb.exe": "PunkBuster",
    "vgc.exe": "Riot Vanguard", "faceit": "FACEIT",
}


def default_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "CELESTARR" / "Hexon"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "CELESTARR" / "Hexon"


def clean_settings(raw) -> dict:
    out = dict(DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return out
    for key in ("dump", "replace", "mips", "verbose"):
        if key in raw:
            out[key] = bool(raw[key])
    try:
        out["min_dim"] = max(4, min(8192, int(raw.get("min_dim", out["min_dim"]))))
        out["dump_gb"] = max(0.5, min(2000.0, float(raw.get("dump_gb", out["dump_gb"]))))
    except (TypeError, ValueError):
        pass
    return out


@dataclass
class Result:
    kind: str
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


@dataclass
class Profile:
    id: str
    name: str
    exe: str
    game_name: str = ""
    backup: str = ""
    settings: dict = field(default_factory=lambda: dict(DEFAULT_SETTINGS))

    @property
    def exe_path(self):
        p = Path(self.exe)
        return p if p.suffix.lower() == ".exe" and p.is_file() else None

    @property
    def game_dir(self) -> Path:
        return Path(self.exe).parent

    @property
    def hexon_dir(self) -> Path:
        return self.game_dir / "hexon"

    @property
    def dll_path(self) -> Path:
        return self.game_dir / DLL_NAME

    @property
    def backup_path(self):
        return self.game_dir / self.backup if self.backup else None

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "exe": self.exe, "game_name": self.game_name,
                "backup": self.backup, "settings": self.settings}

    @staticmethod
    def from_json(d):
        if not isinstance(d, dict) or not d.get("id") or not d.get("exe"):
            return None
        return Profile(id=str(d["id"]), name=str(d.get("name") or Path(d["exe"]).stem), exe=str(d["exe"]),
                       game_name=str(d.get("game_name") or ""), backup=str(d.get("backup") or ""),
                       settings=clean_settings(d.get("settings")))


def norm_path(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


class ProfileStore:
    def __init__(self, data_dir=None):
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        self.path = self.dir / "profiles.json"
        self.profiles = []
        self.active = ""

    def load(self):
        self.profiles, self.active = [], ""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.profiles = [p for p in (Profile.from_json(d) for d in data.get("profiles", [])) if p]
            self.active = str(data.get("active") or "")
        except (OSError, ValueError, AttributeError):
            try:
                self.path.replace(self.path.with_suffix(".json.bad"))
            except OSError:
                pass
            self.profiles, self.active = [], ""
        if self.profiles and not self.get(self.active):
            self.active = self.profiles[0].id

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"version": 1, "active": self.active,
                                   "profiles": [p.to_json() for p in self.profiles]}, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, pid):
        return next((p for p in self.profiles if p.id == pid), None)

    @property
    def current(self):
        return self.get(self.active)

    def by_exe(self, exe):
        key = norm_path(exe)
        return next((p for p in self.profiles if norm_path(p.exe) == key), None)

    def add(self, exe, name="", game_name="", settings=None):
        exe = Path(exe)
        if exe.suffix.lower() != ".exe" or not exe.is_file():
            raise ValueError("Pick the game's .exe file.")
        if self.by_exe(exe):
            raise ValueError(f"A profile for this game already exists ({self.by_exe(exe).name}).")
        p = Profile(id=uuid.uuid4().hex[:12], name=name.strip() or guess_game_name(exe), exe=str(exe),
                    game_name=game_name.strip(), settings=clean_settings(settings))
        self.profiles.append(p)
        self.active = p.id
        self.save()
        return p

    def remove(self, pid):
        self.profiles = [p for p in self.profiles if p.id != pid]
        if self.active == pid:
            self.active = self.profiles[0].id if self.profiles else ""
        self.save()


KNOWN_GAMES = {"rainbowsix": "Rainbow Six Siege", "rainbowsix_vulkan": "Rainbow Six Siege",
               "rainbowsix_be": "Rainbow Six Siege"}


def guess_game_name(exe) -> str:
    stem = Path(exe).stem
    if stem.lower() in KNOWN_GAMES:
        return KNOWN_GAMES[stem.lower()]
    pretty = re.sub(r"[_\-]+", " ", stem)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", pretty).strip() or "Game"


def find_marker_version(path):
    try:
        with open(path, "rb") as f:
            m = MARKER_RE.search(f.read(8 << 20))
    except OSError:
        return None
    return m.group(1).decode("ascii") if m else None


def version_tuple(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v or "0"))


def dll_state(profile: Profile, core_dll) -> str:
    if not profile.exe_path:
        return NO_EXE
    target = profile.dll_path
    if not target.exists():
        return NOT_INSTALLED
    installed = find_marker_version(target)
    if installed is None:
        return FOREIGN
    bundled = find_marker_version(core_dll) if core_dll else None
    if bundled and version_tuple(installed) < version_tuple(bundled):
        return OUTDATED
    return CURRENT


def _install_error(e: OSError) -> str:
    if isinstance(e, PermissionError):
        return ("Windows refused to write to the game folder. Close the game if it's running; if the game is in a "
                "protected folder, run Hexon as administrator.")
    return f"Couldn't install: {e}"


def install(profile: Profile, core_dll, replace_foreign=False) -> Result:
    if not profile.exe_path:
        return Result("error", "This profile's game exe can't be found.")
    if not core_dll or not Path(core_dll).is_file():
        return Result("error", "Hexon's proxy DLL is missing. Reinstall Hexon.")
    state = dll_state(profile, core_dll)
    if state == CURRENT:
        return Result("skipped", "Already installed.")
    target = profile.dll_path
    fresh = target.with_name(DLL_NAME + ".hexon-new")
    backup = None
    try:
        profile.hexon_dir.mkdir(exist_ok=True)
        fresh.write_bytes(Path(core_dll).read_bytes())
        if state == FOREIGN:
            if not replace_foreign:
                fresh.unlink(missing_ok=True)
                return Result("confirm", "The game folder already has a dxgi.dll that isn't Hexon's.")
            backup = target.with_name(BACKUP_NAME)
            n = 1
            while backup.exists():
                n += 1
                backup = target.with_name(f"{BACKUP_NAME}{n}")
            os.replace(target, backup)
            profile.backup = backup.name
        try:
            os.replace(fresh, target)
        except OSError:
            if backup is not None and backup.exists() and not target.exists():
                os.replace(backup, target)
                profile.backup = ""
            raise
    except OSError as e:
        try:
            fresh.unlink(missing_ok=True)
        except OSError:
            pass
        return Result("error", _install_error(e))
    if state == FOREIGN:
        return Result("ok", f"Installed. The original dxgi.dll was kept as {profile.backup} and comes back on uninstall.")
    return Result("ok", "Updated." if state == OUTDATED else "Installed.")


def uninstall(profile: Profile) -> Result:
    target = profile.dll_path
    if target.exists() and find_marker_version(target) is None:
        return Result("skipped", "The dxgi.dll in the game folder isn't Hexon's, so it was left alone.")
    try:
        if target.exists():
            target.unlink()
        bp = profile.backup_path
        if bp and bp.exists():
            os.replace(bp, target)
            profile.backup = ""
            return Result("ok", "Removed Hexon and restored the game's original dxgi.dll.")
        profile.backup = ""
    except OSError as e:
        if isinstance(e, PermissionError):
            return Result("error", "Couldn't remove dxgi.dll. Close the game and try again.")
        return Result("error", f"Couldn't remove dxgi.dll: {e}")
    return Result("ok", "Removed Hexon from the game. Your dumps and replacements were kept.")


def settings_ini_text(settings: dict) -> str:
    s = clean_settings(settings)
    return ("[hexon]\n"
            f"dump={int(s['dump'])}\n"
            f"replace={int(s['replace'])}\n"
            f"min_dim={s['min_dim']}\n"
            "max_dumps=1000000\n"
            f"max_dump_mb={int(s['dump_gb'] * 1024)}\n"
            f"verbose={int(s['verbose'])}\n"
            f"mips={int(s['mips'])}\n")


def write_ini(profile: Profile):
    profile.hexon_dir.mkdir(parents=True, exist_ok=True)
    (profile.hexon_dir / "hexon.ini").write_text(settings_ini_text(profile.settings), encoding="utf-8")


def read_ini(game_dir):
    ini = Path(game_dir) / "hexon" / "hexon.ini"
    if not ini.is_file():
        return None
    try:
        vals = dict(l.strip().split("=", 1) for l in ini.read_text(encoding="utf-8").splitlines() if "=" in l)
        return clean_settings({
            "dump": vals.get("dump", "1") != "0", "replace": vals.get("replace", "1") != "0",
            "mips": vals.get("mips", "1") != "0", "verbose": vals.get("verbose", "0") != "0",
            "min_dim": vals.get("min_dim", 64), "dump_gb": int(vals.get("max_dump_mb", 4096)) / 1024})
    except (OSError, ValueError):
        return None


def detect_anticheat(game_dir) -> list:
    found = set()

    def check(name):
        low = name.lower()
        hit = ANTICHEAT_FILES.get(low)
        if not hit and (low.startswith("easyanticheat") or low.startswith("battleye")):
            hit = "Easy Anti-Cheat" if low.startswith("easy") else "BattlEye"
        if hit:
            found.add(hit)

    try:
        with os.scandir(game_dir) as top:
            for e in top:
                check(e.name)
                if e.is_dir(follow_symlinks=False) and e.name.lower() not in ("hexon", "content", "data"):
                    try:
                        with os.scandir(e.path) as sub:
                            for s in sub:
                                check(s.name)
                    except OSError:
                        pass
    except OSError:
        pass
    return sorted(found)


def pe_machine(path):
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        if head[:2] != b"MZ" or len(head) < 0x40:
            return None
        off = struct.unpack_from("<I", head, 0x3C)[0]
        if off + 6 > len(head) or head[off:off + 4] != b"PE\0\0":
            return None
        return struct.unpack_from("<H", head, off + 4)[0]
    except (OSError, struct.error):
        return None


def bitness_problem(path):
    m = pe_machine(path)
    if m is None or m == 0x8664:
        return None
    return {0x14C: "This is a 32-bit game. Hexon only works with 64-bit DirectX 12 games.",
            0xAA64: "This is an ARM64 game. Hexon only works with x64 DirectX 12 games."}.get(
        m, "This doesn't look like a 64-bit Windows game exe.")


def last_launch_summary(profile: Profile):
    log = profile.hexon_dir / "hexon.log"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "never", "Hexon hasn't run in this game yet."
    start = max((i for i, l in enumerate(lines) if "started (" in l), default=None)
    if start is None:
        return "never", "Hexon hasn't run in this game yet."
    tail = "\n".join(lines[start:])
    if "D3D12 hooks installed" in tail:
        return "hooked", "Last launch: Hexon hooked DirectX 12 successfully."
    if "FAILED" in tail:
        return "failed", "Last launch: Hexon loaded but couldn't hook DirectX 12 (see Log)."
    return "no_dx12", ("Last launch: Hexon loaded, but the game never created a DirectX 12 device. "
                       "This may be the wrong exe, or not a DirectX 12 game.")


def remove_all(data_dir=None) -> int:
    store = ProfileStore(data_dir)
    store.load()
    errors = 0
    for p in store.profiles:
        if p.exe_path is None and not p.game_dir.exists():
            continue
        if uninstall(p).kind == "error":
            errors += 1
    store.save()
    return 1 if errors else 0
