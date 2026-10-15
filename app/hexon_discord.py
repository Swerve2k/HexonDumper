import threading
import time

try:
    import psutil
except Exception:
    psutil = None


class GameWatcher:

    def __init__(self, interval: float = 5.0):
        self.running = None
        self._name = ""
        self._interval = interval
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hexon-gamewatch", daemon=True)
        self._thread.start()

    def set_exe(self, exe_name: str):
        self._name = (exe_name or "").lower()
        self._wake.set()

    def shutdown(self):
        self._stop.set()
        self._wake.set()

    def _run(self):
        while not self._stop.is_set():
            name = self._name
            if psutil is None or not name:
                self.running = None
            else:
                try:
                    self.running = any((p.info["name"] or "").lower() == name
                                       for p in psutil.process_iter(["name"]))
                except Exception:
                    self.running = None
            self._wake.wait(self._interval)
            self._wake.clear()


class DiscordPresence:

    MIN_INTERVAL = 15.0
    RETRY_INTERVAL = 15.0
    _RECONNECT_ERRORS = {"InvalidPipe", "PipeClosed", "ConnectionTimeout", "DiscordNotFound"}

    def __init__(self, on_status=None):
        self._cv = threading.Condition()
        self._client_id = ""
        self._payload = None
        self._stop = False
        self._status_cb = on_status or (lambda text: None)
        self._last_status = None
        self._thread = threading.Thread(target=self._run, name="hexon-discord", daemon=True)
        self._thread.start()

    def configure(self, client_id: str, payload):
        with self._cv:
            self._client_id = (client_id or "").strip()
            self._payload = dict(payload) if payload else None
            self._cv.notify_all()

    def shutdown(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        self._thread.join(timeout=3)

    def _status(self, text: str):
        if text != self._last_status:
            self._last_status = text
            try:
                self._status_cb(text)
            except Exception:
                pass

    @staticmethod
    def _close(rpc, clear: bool):
        try:
            if clear:
                rpc.clear()
        except Exception:
            pass
        try:
            rpc.close()
        except Exception:
            pass

    def _run(self):
        try:
            from pypresence import Presence
        except Exception:
            Presence = None
        rpc = rpc_id = sent = None
        last_sent = 0.0
        next_try = 0.0

        while True:
            with self._cv:
                if self._stop:
                    break
                self._cv.wait(timeout=1.0)
                if self._stop:
                    break
                cid, payload = self._client_id, self._payload
            now = time.monotonic()

            if rpc is not None and (payload is None or cid != rpc_id):
                self._close(rpc, clear=(payload is None and cid == rpc_id))
                rpc = sent = None

            if not cid:
                self._status("Enter your Discord Client ID to enable it.")
                continue
            if payload is None:
                self._status("Off.")
                continue
            if Presence is None:
                self._status("pypresence is not installed (pip install pypresence).")
                continue

            if rpc is None:
                if now < next_try:
                    continue
                try:
                    rpc = Presence(cid)
                    rpc.connect()
                    rpc_id, sent, last_sent = cid, None, 0.0
                    self._status("Connected to Discord.")
                except Exception as e:
                    rpc = None
                    next_try = now + self.RETRY_INTERVAL
                    kind = type(e).__name__
                    if kind == "InvalidID":
                        self._status("Discord rejected that Client ID.")
                        next_try = now + 5.0
                    elif kind == "DiscordNotFound":
                        self._status("Waiting for Discord (is the desktop app running?).")
                    else:
                        self._status(f"Waiting for Discord ({kind}).")
                    continue

            if payload != sent and now - last_sent >= self.MIN_INTERVAL:
                try:
                    rpc.update(**payload)
                    sent, last_sent = dict(payload), now
                    self._status("Connected to Discord.")
                except Exception as e:
                    kind = type(e).__name__
                    if kind in self._RECONNECT_ERRORS or isinstance(e, OSError):
                        self._close(rpc, clear=False)
                        rpc = sent = None
                        next_try = now + self.RETRY_INTERVAL
                        self._status("Lost the connection to Discord, retrying...")
                    else:
                        sent, last_sent = dict(payload), now
                        self._status(f"Discord refused the status: {e}")

        if rpc is not None:
            self._close(rpc, clear=True)
