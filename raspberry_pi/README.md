# Raspberry Pi Install

## Overview

![Pi](https://assets.raspberrypi.com/static/raspberry-pi-4-labelled@2x-1c8c2d74ade597b9c9c7e9e2fff16dd4.png)

Raspberry Pi are a series of small single-board computers (SBCs) developed in the United Kingdom by the Raspberry Pi Foundation in association with Broadcom.

In the case of this project, we use it as a convenient reference platform to run a python based application (seestar_alp) for command and control of the SeeStar S50 telescope.

Note that these instructions assume some basic knowledge of linux systems, and is not intended to be a general tutorial on how to use a Raspberry Pi system running Linux.

## Which Pi should I buy?

Most any Pi with networking should work.
We recommend Pi 3 or newer.
Avoid Pi Zero, and Pico variants.

## Installing
These insructions are based from a fresh install of Raspberry Pi OS Lite, written by the [Raspberry Pi imager](https://www.raspberrypi.com/software/)

To automatically set up the Raspberry Pi for Seestar_alp, run the following command as a non-root user:

```
curl -s https://raw.githubusercontent.com/smart-underworld/seestar_alp/main/raspberry_pi/setup.sh | bash
```

This will:

1. Update the software on the system, and install dependencies needed for git
2. Clone the seestar_alp software from github
3. Install the python dependencies needed for the application
4. Modify the default config file to work on all network interfaces (wifi and ethernet)
5. Set up [systemd](https://en.wikipedia.org/wiki/Systemd) services to start the seestar service at boot time
6. Starts the service

### YouTube links

There have been a couple YouTube tutorials on how to set up a Raspberry Pi

[SeeStarALP RPi Demo](youtube.com/watch?v=0nhUNr_uNZA)

[Seestar ALP Install on Raspberry Pi P400](https://www.youtube.com/watch?v=Cm44uHXo5Rw)

## Updating

An update script is provided to properly stop the seestar service, and update the software appropriately

To update, on the raspberry pi run the following command:
```
~/seestar_alp/raspberry_pi/update.sh
```

## Checking logs

In the event of something going wrong, the first thing to check is the log from the service.

This can be found in the `logs` subfolder.

```
user@astro:~/seestar_alp $ ls logs/
alpyca.log  alpyca.log.2
```

Note that logs are [rotated](https://en.wikipedia.org/wiki/Log_rotation) on a timer, and appended with an integer. The log without an integer is the newest log.

## Service status

The `seestar` service is controlled via `systemd`. 

Super user access(root) is not needed for getting status.

The command to run is:

`systemctl status seestar`

Eg:

```
user@astro:~/seestar_alp $ systemctl status seestar
● seestar.service - SeeStar ALP communications
     Loaded: loaded (/etc/systemd/system/seestar.service; enabled; preset: enabled)
     Active: active (running) since Mon 2024-08-05 17:23:11 EDT; 3h 5min ago
   Main PID: 4345 (python3)
      Tasks: 8 (limit: 1582)
        CPU: 7.282s
     CGroup: /system.slice/seestar.service
             └─4345 /usr/bin/python3 /home/bguthro/seestar_alp/root_app.py

Aug 05 17:23:11 astro systemd[1]: Started seestar.service - SeeStar ALP communications.
```

## Service control (start, stop, restart)

The `seestar` service can be started/stopped/restarted using the appropriate verb via the following command:

`sudo systemctl stop seestar`

Replace the `stop` verb with the appropriate action that you are trying to achieve.

## Persistent logs

Should you find the need to look over systemd logs across boots, you can use `journalctl` to do so.

Eg:

`journalctl -u seestar`

## Getting help

This is very much still a system under development. Things go wrong.

Most of the developers are responsive on the `#seestar_alp` channel of the `Smart Telescope Underworld` discord server. 

See the [How to get Support](../README.md#how-to-get-support) section of the top-level README.md file for details.