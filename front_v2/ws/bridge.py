"""
WebSocket event bridge: telescope sync generators → async fan-out to browser tabs.

One pump thread per device drains the telescope's get_events() generator and
puts normalised JSON dicts into an asyncio.Queue.  The async WS handler reads
from that queue and writes to every connected WebSocket for that device.

MJPEG video intentionally stays on the Flask/waitress imgport — it is NOT
routed through this bridge.
"""

import asyncio
import json
import logging
import threading
from collections import defaultdict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Per-device asyncio queues: device_num → asyncio.Queue
_queues: dict[int, asyncio.Queue] = {}
_queues_lock = threading.Lock()

# Per-device connected WebSocket sets: device_num → set[WebSocket]
_connections: dict[int, set[WebSocket]] = defaultdict(set)
_connections_lock = asyncio.Lock()

# Per-device pump threads: device_num → threading.Thread
_pump_threads: dict[int, threading.Thread] = {}

# The running event loop — set when FrontMainV2.start() creates it.
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def get_or_create_queue(device_num: int) -> asyncio.Queue:
    with _queues_lock:
        if device_num not in _queues:
            _queues[device_num] = asyncio.Queue(maxsize=256)
        return _queues[device_num]


# ---------------------------------------------------------------------------
# Pump thread: runs in a daemon thread, drains the sync generator
# ---------------------------------------------------------------------------


def _pump(device_num: int) -> None:
    """Drain telescope.get_seestar_device(device_num).get_events() in a thread."""
    from device import telescope  # local import — avoids circular at module load

    logger.info("WS bridge: pump starting for device %d", device_num)
    queue = get_or_create_queue(device_num)

    while True:
        try:
            dev = telescope.get_seestar_device(device_num)
        except (KeyError, Exception):
            # Device not yet registered — wait and retry.
            import time

            time.sleep(1)
            continue

        try:
            for raw in dev.get_events():
                if _loop is None or _loop.is_closed():
                    break
                # raw is SSE bytes: b"data: ...\n\n"
                # Parse out the JSON payload sitting after "data: "
                msg = _parse_sse_frame(raw)
                if msg is None:
                    continue
                try:
                    _loop.call_soon_threadsafe(_enqueue_nowait, queue, device_num, msg)
                except RuntimeError:
                    break
        except Exception as exc:
            logger.warning("WS bridge: pump error for device %d: %s", device_num, exc)
            import time

            time.sleep(1)


def _enqueue_nowait(queue: asyncio.Queue, device_num: int, msg: dict) -> None:
    try:
        queue.put_nowait(msg)
    except asyncio.QueueFull:
        # Drop oldest event rather than blocking the pump thread.
        try:
            queue.get_nowait()
            queue.put_nowait(msg)
        except Exception:
            pass


def _parse_sse_frame(raw: bytes) -> dict[str, Any] | None:
    """
    Extract the JSON payload from an SSE frame produced by get_events().

    The generator yields frames like:
        b"data: <pre>2024-01-01 12:00:00.0: {...}</pre>\\n\\n"
        b"event: focusMove\\ndata: 1234\\n\\n"

    We look for the first "data: " line that contains a {...} JSON object.
    Named events (focusMove, temp, etc.) are re-emitted as typed WS messages.
    """
    if not raw:
        return None

    text = raw.decode("utf-8", errors="replace")
    event_name = None
    payload_str = None

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("event: "):
            event_name = line[len("event: ") :]
        elif line.startswith("data: "):
            data_val = line[len("data: ") :]
            # Named-event data lines are plain values, not JSON objects.
            if event_name and not data_val.startswith("{"):
                return {"type": event_name, "payload": data_val}
            # Pull JSON out of optional <pre>timestamp: JSON</pre> wrapper.
            if "<pre>" in data_val:
                start = data_val.find("{")
                end = data_val.rfind("}") + 1
                if start != -1 and end > start:
                    payload_str = data_val[start:end]
            elif data_val.startswith("{"):
                payload_str = data_val

    if payload_str:
        try:
            obj = json.loads(payload_str)
            event = obj.get("Event", "telescope_event")
            return {"type": event, "payload": obj}
        except json.JSONDecodeError:
            return None

    return None


def start_pump(device_num: int) -> None:
    """Start the pump thread for device_num if not already running."""
    if device_num == 0:
        return  # Federation virtual device has no SSE event stream of its own.
    if device_num in _pump_threads and _pump_threads[device_num].is_alive():
        return
    t = threading.Thread(
        target=_pump,
        args=(device_num,),
        daemon=True,
        name=f"WsBridge-pump-{device_num}",
    )
    _pump_threads[device_num] = t
    t.start()
    logger.info("WS bridge: pump thread started for device %d", device_num)


# ---------------------------------------------------------------------------
# Async fan-out task: runs inside Uvicorn's event loop
# ---------------------------------------------------------------------------


async def _fanout(device_num: int) -> None:
    """Read from the device queue and broadcast to all connected tabs."""
    queue = get_or_create_queue(device_num)
    while True:
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            continue

        payload = json.dumps(msg)
        async with _connections_lock:
            dead = set()
            for ws in list(_connections[device_num]):
                try:
                    await asyncio.wait_for(ws.send_text(payload), timeout=2.0)
                except Exception:
                    dead.add(ws)
            _connections[device_num] -= dead


# Fanout tasks: device_num → asyncio.Task
_fanout_tasks: dict[int, asyncio.Task] = {}


async def ensure_fanout(device_num: int) -> None:
    """Ensure a fanout task is running for this device (called on WS connect)."""
    if device_num not in _fanout_tasks or _fanout_tasks[device_num].done():
        _fanout_tasks[device_num] = asyncio.create_task(
            _fanout(device_num), name=f"WsBridge-fanout-{device_num}"
        )


# ---------------------------------------------------------------------------
# FastAPI WebSocket endpoint handler
# ---------------------------------------------------------------------------


async def handle_ws(websocket: WebSocket, device_num: int) -> None:
    """Accept a WebSocket connection and keep it alive until the client disconnects."""
    await websocket.accept()
    start_pump(device_num)
    await ensure_fanout(device_num)

    async with _connections_lock:
        _connections[device_num].add(websocket)

    logger.debug("WS bridge: client connected for device %d", device_num)

    # Send a greeting so the client knows it's live.
    await websocket.send_text(
        json.dumps(
            {
                "type": "connected",
                "payload": {"device_num": device_num},
            }
        )
    )

    try:
        # Keep the connection open; client sends pings or nothing.
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send a keepalive ping
                await websocket.send_text(json.dumps({"type": "ping", "payload": None}))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WS bridge: device %d connection closed: %s", device_num, exc)
    finally:
        async with _connections_lock:
            _connections[device_num].discard(websocket)
        logger.debug("WS bridge: client disconnected from device %d", device_num)
