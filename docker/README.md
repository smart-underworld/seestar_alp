# seestar_alp on docker
Docker provides a portable way to run the application on any OS and architecture.  It's been tested on various Linux distributions and architectures, Mac OS (Apple Silicon, but should also work on Intel), and Windows 11 with WSL 2.

# Install docker
This should work with any version of docker (e.g. Docker Desktop, docker.io, docker-ce, etc.).

If you don't have docker installed and don't have a preference, then [follow the official instructions](https://docs.docker.com/get-docker/).

# Configuration
Copy `docker/config.toml.example` to `docker/config.toml` and edit it for your Seestar array.  

Identify your local time zone using one of the `TZ identifier` options listed [here](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones). For example:  
`TIME_ZONE="America/Vancouver"`

# Run
To run on Windows with Alpaca, simply run the following command from a terminal, setting your local time zone using one of the `TZ identifier` options listed [here](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones). For example:  
`TIME_ZONE="America/Vancouver"`
```
./docker/run.sh -t "America/Vancouver"
```

To run on a Mac with INDI, include the `-i` option:
```
./docker/run.sh -i -t "America/Vancouver"
```

# Build
If the image doesn't exist, then it will be built automatically.  Otherwise, if you want to rebuild it, then run the following:
```
./docker/run.sh -b -t "America/Vancouver"
```
OR to build the INDI version
```
./docker/run.sh -b -i -t "America/Vancouver"
```

# Connect to Seestar from Stellarium

- In Stellarium, enable the Telescope Control plugin by clicking Load on startup  

- Restart Stellarium, go to the Telescope Control plugin and click Configure  

- Click Add New Telescope icon  

- Click INDI/INDIGO  

- Name the telescope Seestar (or whatever else you'd prefer)  

- Select Equinox of the date (JNow) 

- Leave INDI host settings at defaults and click Refresh Devices

- You should see "Seestar Alpha" (or whatever you called it in your config.toml file) listed

- Click OK and then Connect

- You should now see the location of your Seestar on the Stellarium sky atlas. Its position
will update every couple of seconds. 