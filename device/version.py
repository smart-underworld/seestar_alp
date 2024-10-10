import sys
import os
import subprocess
import logging

if getattr(sys, "frozen",  False):
    search_path = sys._MEIPASS
else:
    search_path = os.path.join(os.path.dirname(__file__))

logger = logging.getLogger()

_version = None
class Version:
    # https://stackoverflow.com/questions/14989858/get-the-current-git-hash-in-a-python-script
    # Return the git revision as a string
    @staticmethod
    def git_version():
        global _version
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

        if _version:
            return _version
        else:
            try:
                _minimal_ext_cmd(['git', 'fetch', '--tags'])
            except OSError:
                logger.warning("unable to get git tags")

            try:
                out = _minimal_ext_cmd(['git', 'describe', '--tags'])
                GIT_REVISION = out.strip().decode('ascii')
            except OSError:
                GIT_REVISION = "Unknown"

            _version = GIT_REVISION
            return GIT_REVISION

    @staticmethod
    def app_version():
        path_to_ver = os.path.abspath(os.path.join(search_path, "version.txt"))
        if not os.path.exists(path_to_ver):
            return Version.git_version()
        else:
            with open(path_to_ver, 'r') as file:
                return file.read().replace('\n', '')



if __name__ == "__main__":
    print(f"VER: {Version.app_version()}")
