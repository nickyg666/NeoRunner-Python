#!/usr/bin/env python3
"""
Setup script for NeoRunner - Minecraft Modded Server Manager

Install: pip install -e .
     or: pip install .
"""

from setuptools import setup, find_packages
from pathlib import Path

readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text() if readme_path.exists() else "NeoRunner"

setup(
    name="neorunner",
    version="2.3.0",
    author="NeoRunner Team",
    author_email="contact@neorunner.dev",
    description="Minecraft modded server manager for NeoForge, Forge, and Fabric",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/nickyg666/NeoRunner-Python",
    packages=find_packages(include=["neorunner_pkg", "neorunner_pkg.*"]),
    package_data={
        "neorunner_pkg": ["templates/*.html", "static/*"],
    },
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=[
        "flask>=2.0.0",
        "requests>=2.25.0",
        "apscheduler>=3.9.0",
        "tomli>=2.0.0; python_version<'3.11'",
        "waitress>=2.0.0",
        "beautifulsoup4>=4.9.0",
        "lxml>=4.6.0",
    ],
    extras_require={
        "full": ["playwright>=1.30.0", "playwright-stealth>=1.0.0"],
        "scraper": ["playwright>=1.30.0", "playwright-stealth>=1.0.0"],
    },
    entry_points={
        "console_scripts": [
            "neorunner=neorunner_pkg.cli:main",
        ],
    },
    keywords="minecraft server modded neoforge forge fabric mods",
    project_urls={
        "Bug Reports": "https://github.com/nickyg666/NeoRunner-Python/issues",
        "Source": "https://github.com/nickyg666/NeoRunner-Python",
    },
)