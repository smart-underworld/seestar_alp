import sys
import os
import subprocess

if getattr(sys, "frozen",  False):
    search_path = sys._MEIPASS
else:
    search_path = os.path.join(os.path.dirname(__file__))

version = None

class Version:
    # https://stackoverflow.com/questions/14989858/get-the-current-git-hash-in-a-python-script
    # Return the git revision as a string
    @staticmethod
    def git_version():
        def _minimal_ext_cmd(cmd):
            # construct minimal environment
            env = {}
            for k in ['SYSTEMROOT', 'PATH']:
                v = os.environ.get(k)
                if v is not None:
                    env[k] = v
            # LANGUAGE is used on win32
            env['LANGUAGE'] = 'C'
            env['LANG'] = 'C'
            env['LC_ALL'] = 'C'
            out = subprocess.Popen(cmd, stdout = subprocess.PIPE, env=env).communicate()[0]
            return out

        try:
            out = _minimal_ext_cmd(['git', 'describe', '--tags'])
            GIT_REVISION = out.strip().decode('ascii')
        except OSError:
            GIT_REVISION = "Unknown"

        return GIT_REVISION

    @staticmethod
    def app_version():
        global version
        if version is None:
            path_to_ver = os.path.abspath(os.path.join(search_path, "version.txt"))
            if not os.path.exists(path_to_ver):
                print("XXXX Getting git version")
                version = Version.git_version()
            else:
                print(f"XXXX Found version file: {path_to_ver}")
                with open(path_to_ver, 'r') as file:
                    version = file.read().replace('\n', '')
        return version


if __name__ == "__main__":
    print(f"VER: {Version.app_version()}")
