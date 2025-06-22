# Seestar S50 Simulator

This project implements a simulator of the Seestar S50 telescope. It allows clients to connect and send commands, which are then processed to simulate the behavior of the telescope.

The purpose is to allow parts of the main programs to be worked on during the day.  For example scheduling a mosaic and running the schedule can only be done during the night when you can do a proper startup.  With the simulator you can work on this code without connecting to a real SeeStar

## Project Structure

```
seestar-s50-socket-listener
├── src
│   ├── main.py              # Entry point of the application
│   ├── listener.py          # Socket listener implementation
│   ├── config.py            # Handles the config.toml file
│   ├── log.py               # log file utilities
│   └── seestar_simulator.py # the file that handles all of the interpretation of commands and their responses
├── requirements.txt         # Project dependencies
└── README.md                # Project documentation
```

## Setup Instructions

1. Clone the repository:
   ```
   git clone <repository-url>
   cd simulator
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. In the config.toml of seestar_alp, in the 'seestars' section set the ip address to "127.0.0.1" or the ip of the machine that you are running the simulator on. 
Create a new entry in [[seestars]] to turn on the simulator functionality.
simulator = true

4. In the config.toml of the simulator you shouldn't have to change anything.


## Usage


To start the simulator, run the following command:

```
python src/main.py
```

The simulator will start and wait for incoming connections. Clients can connect to the server and send commands to interact with the simulated telescope.

## Details about the Seestar S50 Telescope Simulation

The Seestar S50 telescope simulation allows users to send various commands to control the telescope's functions. The socket listener processes these commands and returns appropriate responses, simulating the expected behavior of the actual telescope.

## License

This project is licensed under the MIT License - see the LICENSE file for details.