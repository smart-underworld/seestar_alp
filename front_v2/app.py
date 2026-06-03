"""
front_v2/app.py — FrontMainV2

FastAPI + Uvicorn frontend server.  Satisfies the same AppRunner interface as
front/app.py's FrontMain:  start() blocks, reload() is safe to call from the
watchdog ConfigChangeHandler thread.

Activated via config.toml: [webui_settings] frontend = "v2"
"""

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from device.config import Config  # type: ignore
from device.log import get_logger  # type: ignore

from front_v2.api.router_device import router as device_router
from front_v2.api.router_settings import router as settings_router
from front_v2.api.router_goto import router as goto_router
from front_v2.api.router_image import router as image_router
from front_v2.api.router_schedule import router as schedule_router
from front_v2.ws import bridge

logger = logging.getLogger(__name__)

_UI_BUILD_DIR = Path(__file__).parent / "ui" / "dist"


def build_app() -> FastAPI:
    app = FastAPI(
        title="Seestar ALP v2",
        description="FastAPI backend for the seestar_alp v2 Svelte frontend",
        version="2.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(device_router)
    app.include_router(settings_router)
    app.include_router(goto_router)
    app.include_router(image_router)
    app.include_router(schedule_router)

    @app.websocket("/ws/{dev_num}")
    async def ws_endpoint(websocket: WebSocket, dev_num: int):
        await bridge.handle_ws(websocket, dev_num)

    @app.on_event("startup")
    async def on_startup():
        import asyncio
        bridge.set_event_loop(asyncio.get_running_loop())
        # Pre-start pump threads for all configured devices.
        for seestar in Config.seestars:
            bridge.start_pump(seestar["device_num"])

    # Serve the compiled Svelte SPA if the build directory exists.
    if _UI_BUILD_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_UI_BUILD_DIR), html=True), name="spa")
    else:
        @app.get("/")
        def index():
            return {
                "message": "v2 API is running. Svelte UI not built yet.",
                "hint": "Run: cd front_v2/ui && npm install && npm run build",
                "docs": "/docs",
            }

    return app


class FrontMainV2:
    def __init__(self):
        self._server: uvicorn.Server | None = None

    def start(self):
        """Start Uvicorn — blocks until the server stops (matches AppRunner contract)."""
        global logger
        logger = get_logger()

        host = Config.ip_address if Config.ip_address != "0.0.0.0" else "0.0.0.0"
        port = Config.uiport

        app = build_app()

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

        logger.info("==STARTUP== v2 frontend serving on http://%s:%d", host, port)
        logger.info("v2 API docs: http://%s:%d/docs", host, port)

        self._server.run()

    def reload(self):
        """Called by ConfigChangeHandler — re-reads log level only."""
        global logger
        logger = get_logger()
        logger.debug("FrontMainV2 got reload")
