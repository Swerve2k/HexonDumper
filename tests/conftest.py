import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from helpers import make_game


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtCore import QStandardPaths
    from PySide6.QtWidgets import QApplication
    QStandardPaths.setTestModeEnabled(True)
    app = QApplication.instance() or QApplication([])
    yield app


def pump(qapp, until=None, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if until is None or until():
            return True
        time.sleep(0.01)
    return until is None


class Ui:
    def __init__(self, qapp, win, box, game_exe, data_dir):
        self.qapp, self.win, self.box, self.exe, self.data_dir = qapp, win, box, game_exe, data_dir
        self.game = game_exe.parent
        self.hexon = self.game / "hexon"

    def pump(self, until=None, timeout=10.0):
        return pump(self.qapp, until, timeout)

    def messages(self, kind=None):
        return [t for k, t in self.box.log if kind is None or k == kind]


@pytest.fixture
def ui_factory(qapp, tmp_path, monkeypatch):
    import hexon_app
    from hexon_profiles import ProfileStore
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    made = []

    def make(settings_text="", profile_settings=None, game_name="", with_profile=True):
        ini = tmp_path / f"qsettings{len(made)}.ini"
        ini.write_text("[General]\nrpc_enabled=false\npreviews=false\nnotice_accepted=2\n" + settings_text)

        class TempSettings(QSettings):
            def __init__(self, *a):
                super().__init__(str(ini), QSettings.Format.IniFormat)

        class Box(QMessageBox):
            log = []
            answer = True

            @staticmethod
            def information(parent, title, text, *a, **k):
                Box.log.append(("information", text))
                return QMessageBox.Ok

            @staticmethod
            def warning(parent, title, text, *a, **k):
                Box.log.append(("warning", text))
                return QMessageBox.Ok

            @staticmethod
            def critical(parent, title, text, *a, **k):
                Box.log.append(("critical", text))
                return QMessageBox.Ok

            @staticmethod
            def question(parent, title, text, *a, **k):
                Box.log.append(("question", text))
                return QMessageBox.Yes if Box.answer else QMessageBox.No

            def exec(self):
                Box.log.append(("ask", self.text()))
                role = QMessageBox.AcceptRole if Box.answer else QMessageBox.RejectRole
                self._picked = next((b for b in self.buttons() if self.buttonRole(b) == role), None)
                return 0

            def clickedButton(self):
                return getattr(self, "_picked", None)

        monkeypatch.setattr(hexon_app, "QSettings", TempSettings)
        monkeypatch.setattr(hexon_app, "QMessageBox", Box)
        data_dir = tmp_path / f"data{len(made)}"
        exe = make_game(tmp_path / f"game{len(made)}")
        if with_profile:
            store = ProfileStore(data_dir)
            store.add(exe, game_name=game_name, settings=profile_settings)
            store.save()
        win = hexon_app.Hexon(first_run=False, data_dir=data_dir)
        ui = Ui(qapp, win, Box, exe, data_dir)
        made.append(ui)
        ui.pump(timeout=0.05)
        return ui

    yield make
    for ui in made:
        ui.win.close()
        ui.pump(timeout=0.05)
        ui.win.deleteLater()
    pump(qapp, timeout=0.05)
