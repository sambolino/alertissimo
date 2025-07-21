# Custom build script to handle confluent-kafka
from setuptools import setup, find_packages
from setuptools.command.install import install
import subprocess

class CustomInstall(install):
    def run(self):
        # Install confluent-kafka with custom paths
        subprocess.run([
            "pip", "install", "confluent-kafka",
            "--global-option=build_ext",
            "--global-option=--include-dirs=/usr/include",
            "--global-option=--library-dirs=/usr/lib/x86_64-linux-gnu"
        ], check=True)
        
        # Proceed with normal installation
        super().run()

setup(
    name="alertissimo",
    version="0.1.0",
    packages=find_packages(include=['alertissimo', 'alertissimo.*']),
    cmdclass={"install": CustomInstall},
    install_requires=[
        "antares-client==1.8.0",
        "lark==1.2.2",
        "marshmallow==3.21.1",
        "marshmallow-jsonapi==0.24.0",
        "pydantic==2.11.7",
        "pydantic_core==2.33.2",
        "python-dotenv==1.1.1",
        "rich==14.0.0",
        "streamlit==1.47.0",
        "matplotlib==3.10.3",
        "pandas==2.3.1",
        "altair==5.5.0",
        "astropy==7.1.0",
        "cmake==3.28.3"
    ],
    entry_points={
        'console_scripts': [
            'alertissimo = alertissimo.app_dsl:main',
        ],
    },
)
