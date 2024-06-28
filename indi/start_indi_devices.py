import toml
import subprocess

with open('/home/seestar/seestar_alp/device/config.toml', 'r') as inf:
	config = toml.load(inf)
	seestars = config['seestars']
	
	for seestar in seestars:
		name = seestar['name']
		number = seestar['device_num']
		cmd = f'echo "start /home/seestar/seestar_alp/indi/seestar.py -n \\"{name}\\" -c \\"{number}\\"" > /tmp/seestar'
		print(cmd)
		subprocess.run(cmd, shell = True, executable="/bin/bash")