"""
RockTranslate — PyPI Package Configuration Setup
Path: setup.py

Configures core metadata, entry points, and optional GUI extras for PyPI distribution.
"""

from setuptools import setup, find_packages

# Core lightweight requirements for CLI & Python API Library usage (No GUI dependencies)
requirements = [
    "beautifulsoup4>=4.12.0",
    "lxml>=4.9.0",
    "litellm>=1.0.0",
    "json-repair>=0.10.0",
    "pypdf>=4.0.0",
    "loguru>=0.7.0",
    "tiktoken>=0.5.0"
]

# Optional extras for desktop GUI environments
extras_require = {
    "gui": [
        "pywebview>=5.0"  # Lightweight HTML5 viewport engine
    ]
}

setup(
    name="rocktranslate",
    version="1.0.0",
    author="PerfectWin (WINTER TONY)",
    author_email="wintertony7777@gmail.com",
    description="High-fidelity layout-preserved scientific PDF translator using advanced LLMs",
    long_description=open("README.md", "r", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/PerfectWin7777/RockTranslate",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    install_requires=requirements,
    extras_require=extras_require,
    entry_points={
        "console_scripts": [
            "rocktranslate=rocktranslate.cli:main",
            "rocktranslate-gui=rocktranslate.web_gui:main"
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
)