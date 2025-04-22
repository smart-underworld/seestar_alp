#
# Defines binary protocol handlers
#
import socket
import errno
from struct import calcsize, unpack


from device.protocols.socket_base import SocketBase, SocketListener
from lib.trace import MessageTrace


# methods:
# - send message
# - socket handling code


class SeestarBinaryProtocol(SocketBase):
    def __init__(self, logger, device_name, device_num, host, port):
        super().__init__(logger, device_name, host, port)
        self.device_name = device_name
        self.device_num = device_num
        self.trace = MessageTrace(self.device_num, self.port, False)
        self.binary_listener = SeestarBinaryProtocol.BinaryListener(self)
        self.add_listener(self.binary_listener)

    def __del__(self):
        self.remove_listener(self.binary_listener)

    class BinaryListener(SocketListener):
        def __init__(self, protocol):
            self.protocol = protocol

        def on_connect(self):
            pass

        def on_heartbeat(self):
            # self.protocol.logger.info("send HEARTBEAT!!")
            self.protocol.send_message(
                '{ "id" : 2,  "method" : "test_connection"}' + "\r\n"
            )
            # self.protocol.logger.info("sent HEARTBEAT!!")

        def on_disconnect(self):
            pass

    def send_message(self, data):
        # Minimize time holding lock
        with self.lock:
            soc = self._s if self.is_connected() else None

        if soc is not None:
            self.logger.debug(f"sending message: {data}")  # temp made info
            try:
                soc.sendall(
                    data.encode()
                )  # TODO: would utf-8 or unicode_escaped help here
                # self.trace.save_message(data, 'send')
                return True
            except socket.timeout:
                print("sending timeout")
                return False
            except IOError as e:
                if e.errno == errno.EPIPE:
                    self.disconnect()
                    if self.reconnect():
                        return self.send_message(data)
            except socket.error as e:
                self.logger.error(f"Send Socket error: {e}")
                # self.disconnect()
                # if self.reconnect():
                #    return self.send_message(data)
                return False
        else:
            self.logger.warning(f"Send Socket error: not connected: {data}")
            return False

    def recv_exact(self, num):
        """Reads exactly num bytes from the socket, and returns the bytes, or None
        if no more bytes."""
        # Minimize time holding lock when reading from socket
        with self.lock:
            soc = self._s if self.is_connected() else None

        if soc is not None:
            data = None
            try:
                data = soc.recv(num, socket.MSG_WAITALL)  # comet data is >50kb
            except socket.timeout:
                self.logger.info("recv timeout")
                return None
            except socket.error as e:
                # todo : if general socket error, close socket, and kick off reconnect?
                # todo : no route to host...
                self.logger.error(f"Device {self.device_name}: read Socket error: {e}")
                self.disconnect()
                return None

            if data is None or len(data) == 0:
                return None

            # self.logger.debug(f'{self.device_name} received : {len(data)}')
            self.logger.debug(f"received : {len(data)}")  # todo : make debug!
            dl = len(data)
            if dl < 100 and dl != 80:
                self.logger.debug(f"Message: {data}")
            # self.trace.save_message(data, 'recv')
            return data
        else:
            return None

    def send_message_sync(self, message):
        # send and wait for response
        pass

    def parse_header(self, header):
        if header is not None and len(header) > 20:
            # print(type(header))
            self.logger.debug("Header:" + ":".join("{:02x}".format(c) for c in header))
            # We ignore all values at end of header...
            header = header[:20]
            fmt = ">HHHIHHBBHH"
            self.logger.debug(f"size: {calcsize(fmt)}")
            _s1, _s2, _s3, size, _s5, _s6, code, id, width, height = unpack(fmt, header)
            if size > 100:
                self.logger.debug(
                    f"header: {size=} {width=} {height=} {_s1=} {_s2=} {_s3=} {code=} {id=}"
                )  # xxx trace

            return size, id, width, height
        return 0, None, None, None
