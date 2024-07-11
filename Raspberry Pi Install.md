#Raspberry Pi Install

These insructions are based from a fresh install of Raspberry Pi OS (Release date: July 4th 2024)

```shell
sudo apt install gh
git clone https://github.com/smart-underworld/seestar_alp.git
cd seestar_alp
sudo pip install -r requirements.txt --break-system-packages
edit /device/config.toml
run /device/app.py (This is the main seestar_alp application)
run /front/app.py (This is the WebUI)
```

To automatically start the two aforementioned applications, see the README.txt file in the systemd subfolder.
These instructions will walk you through using the systemd init system to have the system start the apps at boot time.
