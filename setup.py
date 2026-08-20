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
    packages=find_packages(include=["alertissimo", "alertissimo.*"]),
    package_data={"alertissimo.dsl": ["grammar.lark", "expression.lark"]},
    cmdclass={"install": CustomInstall},
    install_requires=[
        "setuptools>=69.5.1",
        "antares-client==1.14.0",
        "lark==1.2.2",
        "marshmallow==3.21.1",
        "marshmallow-jsonapi==0.24.0",
        "pydantic==2.11.7",
        "pydantic_core==2.33.2",
        "python-dotenv==1.1.1",
        "rich==14.0.0",
        "streamlit==1.47.0",
        "streamlit-aggrid==1.2.1.post2",
        "pyarrow>=7.0,<25",  # PyArrow 25.0.0 segfaults across Streamlit reruns
        "matplotlib==3.10.3",
        "pandas==2.2.3",
        "altair==5.5.0",
        "astropy>=6.1.4",
        "alerce>=2.3.0",
        "cmake==3.28.3",
        "numpy>=2.0.0,<2.1.0",  # Allow NumPy 2.0.x but not 2.1+
    ],
    entry_points={
        "console_scripts": [
            "alertissimo = alertissimo.app_dsl:main",
        ],
    },
)
