import toml
import subprocess
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(script_dir)

with open(f'{repo_dir}/device/config.toml', 'r') as inf:
	config = toml.load(inf)
	seestars = config['seestars']

	for seestar in seestars:
		name = seestar['name']
		number = seestar['device_num']
		cmd = f'echo "start {repo_dir}/indi/seestar.py -n \\"{name}\\" -c \\"{number}\\"" > /tmp/seestar'
		print(cmd)
		subprocess.run(cmd, shell = True, executable="/bin/bash")