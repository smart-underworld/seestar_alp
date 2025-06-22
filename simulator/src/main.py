from listener import SocketListener
import logging
import log


def main():
    Config.load_toml()

    # Example: get log config from Config

    logger = log.init_logging()
    # Share this logger throughout
    log.logger = logger

    logger = logging.getLogger("seestar")
    # Share this logger throughout

    # Start the socket listener
    # Initialize the socket listener with the specified host and port
    # The UDP port is used for iscope commands
    # The TCP port is used for other commands
    socket_listener = SocketListener(
        logger, Config.ip_address, Config.tcp_port, Config.udp_port
    )
    # Start listening for incoming connections
    socket_listener.start_listening()


if __name__ == "__main__":
    main()
