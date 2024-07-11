Instructions for systemd startup of seestar apps.
This should work on RaspberryPi machines, or any other Linux distro running systemd

1. Copy service files to systemd location
   cp ./*.service /etc/systemd/system

2. Edit the .service files, and replace <username> with your user, or path where you have seestar_alp cloned

3. Reload the systemd daemon, to find the new service files
   sudo systemctl daemon-reload

4. Enable the services
   sudo systemctl enable seestar_device
   sudo systemctl enable seestar_front

5. Start the services
   sudo systemctl start seestar_device
   sudo systemctl start seestar_front
