import os

from django.core import management
from setuptools.command.build import build

here = os.path.abspath(os.path.dirname(__file__))
npm_installed = False


class CustomBuild(build):
    def run(self):
        locale_found = False
        for dirpath, dirnames, filenames in os.walk('.', topdown=True):
            for dirname in dirnames:
                if dirname == 'locale':
                    locale_found = True
                    break

        if locale_found:
            management.call_command('compilemessages', verbosity=1)
        build.run(self)
