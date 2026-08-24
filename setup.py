from pathlib import Path

from setuptools import find_packages, setup


ROOT = Path(__file__).parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


setup(
    name="alertissimo",
    version="0.9.0",
    description="An uber broker for transient alert orchestration",
    long_description=README,
    long_description_content_type="text/markdown",
    packages=find_packages(include=["alertissimo", "alertissimo.*"]),
    include_package_data=True,
    package_data={
        "alertissimo.dsl": ["*.lark"],
        "alertissimo.data_layer.execution": ["*.yaml"],
        "alertissimo.data_layer.semantic_model": ["*.yaml"],
        "alertissimo.data_layer": ["providers/*/*/*.yaml"],
    },
    license_files=("LICENCE",),
    python_requires=">=3.10",
    install_requires=[
        "antares-client==1.14.0",
        "lark==1.2.2",
        "marshmallow==3.21.1",
        "marshmallow-jsonapi==0.24.0",
        "pydantic==2.11.7",
        "pydantic_core==2.33.2",
        "PyYAML>=6.0",
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
        "numpy>=2.0.0,<2.1.0",  # Allow NumPy 2.0.x but not 2.1+
    ],
    entry_points={
        "console_scripts": [
            "alertissimo = alertissimo.app_dsl:main",
        ],
    },
)
