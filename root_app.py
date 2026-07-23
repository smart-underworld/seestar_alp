#
# Start frontend and pass in ALP for it to manage
#
import os
import subprocess
import threading
import time
import warnings
from pathlib import Path

import sdnotify
import waitress
from flask import Flask, Response
from flask_cors import CORS, cross_origin
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from device.app import DeviceMain  # type: ignore
from device.config import Config  # type: ignore
from device import log  # type: ignore
from device import telescope  # type: ignore


def _ensure_v2_ui_built():
    """Auto-build the Svelte UI if dist/ is missing or source is newer than dist."""
    base = Path(__file__).parent
    dist_dir = base / "front_v2" / "ui" / "dist"
    src_dir = base / "front_v2" / "ui" / "src"
    script = base / "scripts" / "build_ui.sh"

    if not script.exists():
        return  # packaged install — dist should already be present

    if not dist_dir.exists():
        print(
            "v2 UI dist/ not found — building now (this may take ~30 s on first run)…"
        )
        subprocess.run(["bash", str(script)], check=True)
        return

    if src_dir.exists():
        dist_mtime = max(
            (f.stat().st_mtime for f in dist_dir.rglob("*") if f.is_file()), default=0
        )
        src_mtime = max(
            (f.stat().st_mtime for f in src_dir.rglob("*") if f.is_file()), default=0
        )
        if src_mtime > dist_mtime:
            print("v2 UI source changed — rebuilding…")
            ui_dir = base / "front_v2" / "ui"
            node_modules = ui_dir / "node_modules"
            if node_modules.exists():
                # node_modules present — skip npm ci, just rebuild
                subprocess.run(["npm", "run", "build"], cwd=str(ui_dir), check=True)
            else:
                subprocess.run(["bash", str(script)], check=True)


_frontend = getattr(Config, "frontend", "classic")
if _frontend == "v2":
    _ensure_v2_ui_built()
    try:
        from front_v2.app import FrontMainV2 as FrontMain
        from front.app import get_live_status
    except ImportError as _e:
        warnings.warn(
            f"frontend = 'v2' selected but v2 deps not installed ({_e}). "
            "Falling back to classic. Run: pip install -e '.[v2]'",
            stacklevel=1,
        )
        from front.app import FrontMain, get_live_status  # type: ignore[assignment]
else:
    from front.app import FrontMain, get_live_status  # type: ignore[assignment]


class AppRunner:
    def __init__(self, log, name, app_main):
        self.name = name
        self.logger = log
        self.thread = None
        self.app_main = app_main()

    def start(self):
        self.logger.info(f"Starting {self.name}")
        self.thread = threading.Thread(target=self.runner, args=(1,), daemon=True)
        self.thread.name = f"{self.name}MainThread"
        self.thread.start()

    def get_imager(self, device_num: int):
        return self.app_main.get_imager(device_num)

    def runner(self, name):
        self.logger.info(f"Seestar{self.name} %s: starting", name)
        self.app_main.start()
        self.logger.info(f"Seestar{self.name} %s: finishing", name)

    def join(self):
        self.thread.join()

    def reload(self):
        self.logger.setLevel(Config.log_level)
        for handler in self.logger.handlers:
            handler.setLevel(Config.log_level)
        self.app_main.reload()


class ConfigChangeHandler(FileSystemEventHandler):
    def __init__(self, path, alp, front):
        self.path = path
        self.alp = alp
        self.front = front
        self.last_restart = time.time()

    def on_modified(self, event):
        if event.src_path == self.path:
            # print(f'ConfigChangeHandler event type: {event.event_type}  path : {event.src_path}')
            Config.load_toml()
            self.alp.reload()
            self.front.reload()
        # else:
        #    print(f"ConfigChangeHandler Ignoring event type: {event.event_type}  path : {event.src_path}")


if __name__ == "__main__":
    n = sdnotify.SystemdNotifier()

    if Config.rtsp_udp:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp"
    # We want to initialize ALP logger
    logger = log.init_logging()

    logger.info("Starting ALP web server")
    main = AppRunner(logger, "ALP", DeviceMain)
    main.start()
    time.sleep(1)

    logger.info("Starting Front web server")
    front = AppRunner(logger, "Front", FrontMain)
    front.start()

    event_handler = ConfigChangeHandler(Config.path_to_dat, main, front)
    observer = Observer()
    observer.schedule(
        event_handler, path=os.path.dirname(Config.path_to_dat), recursive=True
    )
    observer.start()

    time.sleep(1)

    logger.info("Setting up imaging web server")
    app = Flask(__name__)
    CORS(app, supports_credentials=True)

    @cross_origin()
    @app.route("/<dev_num>/vid/status")
    def vid_status(dev_num):
        return Response(
            telescope.get_seestar_imager(int(dev_num)).get_video_status(),
            mimetype="text/event-stream",
        )

    @cross_origin()
    @app.route("/<dev_num>/live/status")
    def live_status(dev_num):
        return Response(get_live_status(int(dev_num)), mimetype="text/event-stream")

    @cross_origin()
    @app.route("/<dev_num>/events")
    def live_events(dev_num):
        return Response(
            telescope.get_seestar_device(int(dev_num)).get_events(),
            mimetype="text/event-stream",
        )

    @cross_origin()
    @app.route("/<dev_num>/vid")
    def vid(dev_num):
        return Response(
            telescope.get_seestar_imager(int(dev_num)).get_frame(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    n.notify("READY=1")
    print("Startup Complete")

    # telescope.telescopes()

    waitress.serve(
        app, host=Config.ip_address, port=Config.imgport, threads=15, channel_timeout=30
    )
