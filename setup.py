"""Setuptools entry point.

All package metadata lives in ``pyproject.toml``; this shim keeps the classic
``python setup.py sdist``/``bdist_wheel`` commands working. It deliberately does
nothing else: setuptools executes this file whenever it builds the project, so
putting build logic here would break ``pip install``.

The desktop installer is a separate, explicit step: build the executable with
``build.bat``, then compile ``installer/Textra.iss`` (Inno Setup 6) with
``installer/build_installer.bat``.
"""

from setuptools import setup

setup()
