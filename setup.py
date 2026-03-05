#!/usr/bin/env python3
"""
Setup script for NeoRunner - Minecraft Modded Server Manager

Install: pip install -e .
"""

from setuptools import setup, find_packages
from pathlib import Path

readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text() if readme_path.exists() else "NeoRunner - Minecraft modded server manager"

setup(
    name="neorunner",
    version="2.1.0",
    author="NeoRunner Team",
    author_email="contact@neorunner.dev",
    description="A comprehensive Minecraft modded server manager for NeoForge, Forge, and Fabric",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/neorunner/neorunner",
    packages=find_packages(),
    package_data={
        "neorunner": ["templates/*.html", "static/*", "mods/*"],
    },
    data_files=[
        ("/etc/systemd/system", ["neorunner/neorunner.service"]),
    ],
    include_package_data=True,
    scripts=["neorunner/manage.sh"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Games/Entertainment",
        "Topic :: System :: Systems Administration",
    ],
    python_requires=">=3.9",
    install_requires=[
        "flask>=2.0.0",
        "requests>=2.25.0",
        "apscheduler>=3.9.0",
        "tomli>=2.0.0; python_version<'3.11'",
        "waitress>=2.0.0",
    ],
    extras_require={
        "full": ["playwright>=1.30.0", "playwright-stealth>=1.0.0"],
        "scraper": ["playwright>=1.30.0", "playwright-stealth>=1.0.0"],
        "dev": ["pytest>=7.0.0", "black>=22.0.0", "mypy>=0.950"],
    },
    entry_points={
        "console_scripts": [
            "neorunner=neorunner.cli:main",
            "neorunner-server=neorunner.server:main",
            "neorunner-manage=neorunner.cli:manage",
        ],
    },
    keywords="minecraft server modded neoforge forge fabric mods",
    project_urls={
        "Bug Reports": "https://github.com/neorunner/neorunner/issues",
        "Source": "https://github.com/neorunner/neorunner",
    },
)
