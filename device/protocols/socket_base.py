#
# Base socket-handling code
#
import datetime
import socket
import threading
from abc import ABC, abstractmethod
import time
from typing import List, Optional

from device.config import Config


# todo : onstopped, onstarted?
class SocketListener(ABC):
    """Socket listener base class.  Implement to listen for socket events."""

    @abstractmethod
    def on_connect(self):
        pass

    @abstractmethod
    def on_heartbeat(self):
        pass

    @abstractmethod
    def on_disconnect(self):
        pass


class MessageListener(ABC):
    """Message listener base class.  Implement to listen for socket messages."""

    @abstractmethod
    def on_message(self, message):
        pass


class SocketBase:
    def __init__(self, logger, device_name: str, host: str, port: int):
        self.device_name = device_name
        self.host = host
        self.port = port
        self.logger = logger
        self._s: Optional[socket.socket] = None
        self._is_connected: bool = False
        self._is_started: bool = False
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()
        self._listeners: List[SocketListener] = []  # todo : change to weak references!

    def start(self):
        """Starts socket. Attempts to connect, and continues to keep alive until stopped."""
        with self.lock:
            # print("Start SocketBase!")
            if self._is_started:
                return

            self._is_started = True

            if self.heartbeat_thread is None:
                self.heartbeat_thread = threading.Thread(
                    target=self._heartbeat_message_thread_fn, daemon=True
                )
                self.heartbeat_thread.name = f"SocketHeartbeatMessageThread.{self.device_name}"  # todo : tweak the name
                self.heartbeat_thread.start()

            self.connect()

    def stop(self):
        """Stops socket connection"""
        with self.lock:
            self._is_started = False

            # todo : stop the heartbeat thread?

            self.disconnect()

    def connect(self):
        with self.lock:
            if not self._is_started:
                # todo : do something else!
                return False

            try:
                self._s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._s.settimeout(Config.timeout)
                self._s.connect((self.host, self.port))
                self._s.settimeout(None)
                self._is_connected = True
                self.logger.info("connected")
                for listener in self._listeners:
                    listener.on_connect()
                return True
            except socket.error as e:
                # Let's just delay a fraction of a second to avoid reconnecting too quickly
                self.logger.error(f"connect socket error: {e}")
                self._is_connected = False
                self._s = None
                time.sleep(0.1)
                return False

    def disconnect(self):
        with self.lock:
            self.logger.info("disconnect")
            self._is_connected = False
            if self._s:
                try:
                    self._s.close()
                    self._s = None
                except:
                    pass
                for listener in self._listeners:
                    listener.on_disconnect()

    def is_connected(self):
        with self.lock:
            return self._is_connected and self._s is not None

    def is_started(self):
        with self.lock:
            return self._is_started

    def reconnect(self):
        with self.lock:
            if self._is_connected:
                return True

            try:
                self.disconnect()
                return self.connect()
            except socket.error:
                # Let's just delay a fraction of a second to avoid reconnecting too quickly
                self._is_connected = False
                time.sleep(0.1)
                return False

    def add_listener(self, listener: SocketListener):
        with self.lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: SocketListener):
        with self.lock:
            self._listeners.remove(listener)

    def _heartbeat_message_thread_fn(self):
        while True:
            threading.current_thread().last_run = datetime.datetime.now()

            # Minimize time holding lock
            if self.is_started():
                # Only run heartbeat logic or try reconnecting if we're started
                if not self.is_connected() and not self.reconnect():
                    time.sleep(1)
                    continue

                for listener in self._listeners:
                    listener.on_heartbeat()

            time.sleep(3)
