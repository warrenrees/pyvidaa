#!/usr/bin/env python3
"""Setup script for pyvidaa package."""
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="pyvidaa",
    version="2.0.0",
    author="Warren Rees",
    author_email="",
    description="Control Hisense/Vidaa Smart TVs via MQTT",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/warrenrees/pyvidaa",
    project_urls={
        "Bug Tracker": "https://github.com/warrenrees/pyvidaa/issues",
        "Documentation": "https://github.com/warrenrees/pyvidaa#readme",
        "Source Code": "https://github.com/warrenrees/pyvidaa",
        "Changelog": "https://github.com/warrenrees/pyvidaa/blob/main/CHANGELOG.md",
    },
    packages=find_packages(exclude=["tests", "tests.*"]),
    package_data={"pyvidaa": ["remote_ca.pem"]},
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Home Automation",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="hisense myhisense vidaa tv mqtt smart-tv home-automation",
    install_requires=[
        "paho-mqtt>=1.6.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "tv=pyvidaa.cli:main",
            "pyvidaa=pyvidaa.cli:main",
        ],
    },
    python_requires=">=3.8",
)
