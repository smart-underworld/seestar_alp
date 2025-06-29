import threading
import socket
import select
import json  # Added import for JSON handling
from seestar_simulator import SeestarSimulator


class SocketListener:
    def __init__(
        self, logger, host="localhost", tcp_port=4700, udp_port=4720
    ):  # Changed default tcp_port to 5555
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.tcp_socket = None
        self.udp_socket = None
        self.logger = logger  # Use the provided logger
        self.shutdown_event = threading.Event()
        self.simulator = SeestarSimulator(
            logger=logger,  # Replace with actual logger if needed
            host=self.host,
            port=self.tcp_port,
            device_name="Seestar Simulator",
            device_num=1,
            is_EQ_mode=True,
            is_debug=True,
        )

    def start_listening(self):
        """
        Starts the socket listener in a separate thread and manages its lifecycle.

        This method initializes a shutdown event and spawns a new thread to run the socket listener.
        It keeps the main thread alive while the listener thread is running, allowing for graceful
        shutdown on a KeyboardInterrupt (Ctrl+C). Upon interruption, it signals the listener to stop,
        closes any open TCP and UDP sockets, and waits for the listener thread to finish before exiting.

        Raises:
            KeyboardInterrupt: If the user interrupts the process (e.g., with Ctrl+C).
        """
        self.shutdown_event = threading.Event()
        listener_thread = threading.Thread(target=self._start_socket_listener)
        listener_thread.start()

        try:
            while listener_thread.is_alive():
                listener_thread.join(timeout=1)
        except KeyboardInterrupt:
            print("Shutting down sockets...")
            self.shutdown_event.set()
            if self.tcp_socket:
                self.tcp_socket.close()
            if self.udp_socket:
                self.udp_socket.close()
            listener_thread.join()
            print("Shutdown complete.")

    def _start_socket_listener(self):
        """
        Starts and manages the main socket listener loop for both TCP and UDP connections.
        This method sets up non-blocking TCP and UDP sockets bound to the specified host and ports.
        It monitors these sockets for incoming connections or data using the `select` module.
        - For TCP: Accepts new client connections and spawns a new thread to handle each connection.
        - For UDP: Receives datagrams and processes them accordingly.
        The method continues running until the `shutdown_event` is set, allowing for graceful shutdown.
        All socket errors and select loop errors are caught and logged to the console.
        Side Effects:
            - Modifies `self.tcp_socket` and `self.udp_socket`.
            - Sets the socket in the associated simulator.
            - Spawns threads for each TCP client connection.
            - Prints status and error messages to the console.
        """
        # TCP setup
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_socket.bind((self.host, self.tcp_port))
        self.tcp_socket.listen(5)
        self.tcp_socket.setblocking(False)  # 🔧 Required for select()

        self.simulator.set_socket(self.tcp_socket)  # Set the socket in the simulator
        # UDP setup
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind((self.host, self.udp_port))
        self.udp_socket.setblocking(False)

        print(f"Listening on TCP {self.host}:{self.tcp_port}")
        print(f"Listening on UDP {self.host}:{self.udp_port}")
        print("Startup complete.       Press Ctrl+C to stop.")

        sockets_to_monitor = [self.tcp_socket, self.udp_socket]

        while not self.shutdown_event.is_set():
            try:
                readable, _, _ = select.select(sockets_to_monitor, [], [], 1.0)
                for sock in readable:
                    if sock is self.tcp_socket:
                        try:
                            client_socket, addr = self.tcp_socket.accept()
                            self.simulator.set_socket(
                                client_socket
                            )  # Set the socket in the simulator
                            # Handle TCP connection (maybe spawn a thread if needed)
                            threading.Thread(
                                target=self.handle_tcp_connection,
                                args=(client_socket, addr),
                                daemon=True,
                            ).start()
                        except Exception as e:
                            print(f"TCP accept error: {e}")
                    elif sock is self.udp_socket:
                        try:
                            data, addr = self.udp_socket.recvfrom(4096)
                            # Handle UDP message
                            self.handle_udp_message(data, addr)
                        except Exception as e:
                            print(f"UDP receive error: {e}")
            except Exception as e:
                print(f"Select loop error: {e}")
                break

    def handle_tcp_connection(self, client_socket, addr):
        """
        Handles an incoming TCP connection from a client.

        Receives data from the client socket in a blocking manner, buffering incoming bytes.
        Processes complete messages separated by '\r\n', decodes each message as UTF-8,
        and passes the command to `self.process_tcp_command`. Sends the response back to the client.
        Handles client disconnection and logs any exceptions that occur during processing.

        Args:
            client_socket (socket.socket): The socket object representing the client connection.
            addr (tuple): The address of the connected client.
        """
        with client_socket:
            client_socket.setblocking(True)  # Ensure blocking mode for the handler
            try:
                buffer = b""
                while True:
                    data = client_socket.recv(4096)
                    if not data:
                        break  # Client closed connection
                    buffer += data
                    # Process complete messages separated by \r\n
                    while b"\r\n" in buffer:
                        msg, buffer = buffer.split(b"\r\n", 1)
                        if not msg:
                            continue
                        command = msg.decode("utf-8")
                        response = self.process_tcp_command(command)
                        client_socket.sendall(response.encode("utf-8"))
            except Exception as e:
                print(f"Error handling TCP connection from {addr}: {e}")

    def process_tcp_command(self, command):
        """
        Processes a TCP command by sending it to the simulator and handling the response.

        Args:
            command (str): The TCP command to be processed.

        Returns:
            str: The JSON-formatted response from the simulator, terminated with a carriage return and newline.

        Logs:
            - Debug logs for incoming commands (except 'scope_get_equ_coord').
            - Debug logs for responses, with special handling for 'scope_get_equ_coord' method responses.
        """

        # 'scope_get_equ_coord' is the heartbeat message and creates a bunch of clutter in the logs
        if "scope_get_equ_coord" not in command:
            self.logger.debug(f"Processing command: {command}")
        else:
            self.logger.debug("Processing command: scope_get_equ_coord")

        response = self.simulator.send_message_param_sync(command)

        if response["method"] == "scope_get_equ_coord":
            self.logger.debug(f"Response: {response['method']}")
        else:
            self.logger.debug(f"Response: {response} ")

        return json.dumps(response) + "\r\n"  # print(response)

    def handle_udp_message(self, data, addr):
        """
        Handles incoming UDP messages by decoding the data, attempting to parse it as JSON,
        and processing the command. Sends a response back to the sender.

        Args:
            data (bytes): The received UDP message data.
            addr (tuple): The address of the sender (IP, port).

        Side Effects:
            Logs the received message.
            Sends a response to the sender via UDP.
            Logs or prints errors encountered during processing or sending.

        """
        message = data.decode(
            "utf-8", errors="replace"
        )  # Decode the bytes into a string
        self.logger.debug(f"Received UDP message from {addr}: {message}")

        # Try to parse as JSON
        try:
            parsed = json.loads(message)
        except Exception:
            parsed = None

        # Call process_udp_command to get the response
        response = self.process_udp_command(message, addr, parsed).encode("utf-8")
        try:
            self.udp_socket.sendto(response, addr)
            # print(f"Sent response to {addr}")
        except Exception as e:
            print(f"Error sending UDP response to {addr}: {e}")

    def process_udp_command(self, message, addr, parsed=None):
        """
        Processes incoming UDP commands and returns appropriate responses.

        If the 'parsed' argument is a dictionary (indicating a JSON-based command), this method checks the "method" key
        to determine the requested action. For the "scan_iscope" method, it returns a JSON-formatted response containing
        device information. Additional JSON-based commands can be handled by extending the method.

        If 'parsed' is not a dictionary, the method treats the message as an unknown command and returns a corresponding response.

        Args:
            message (str): The raw message received over UDP.
            addr (tuple): The address (IP, port) of the sender.
            parsed (dict or None, optional): The parsed JSON object from the message, if available.

        Returns:
            str: The response to be sent back to the sender, either as a JSON string or a plain text message.
        """
        # If parsed is a dict, handle JSON-based commands
        if isinstance(parsed, dict):
            method = parsed.get("method", "").lower()
            if method == "scan_iscope":
                device_info = {
                    "id": parsed.get("id", 1),
                    "result": "ok",
                    "device": "seestar",
                    "name": "seestar simulator",
                    "ip": addr[0],
                }
                response = json.dumps(device_info)
                self.logger.debug(f"UDP response to {addr}: {response}")
                return response
            # Add more JSON-based command handling here if needed
            # response = "" # json.dumps({"error": "Unknown JSON command"})
            self.logger.debug(f"UDP response to {addr}: {response}")
            return response
        else:
            response = f"Unknown command: {message}"
            print(f"UDP response to {addr}: {response}")
            return response
