#!/usr/bin/env python3
"""Build and verify the distributable Alertissimo wheel without provider API calls.

The check proves that release metadata and declarative runtime resources survive
packaging, then installs the wheel into an isolated target directory and runs the
public static DSL facade from that installed copy rather than from the source tree.
"""

from __future__ import annotations

from email.parser import Parser
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.1.0"


def _runtime_resources() -> tuple[str, ...]:
    paths = [
        *sorted((ROOT / "alertissimo" / "dsl").glob("*.lark")),
        *sorted((ROOT / "alertissimo" / "data_layer" / "execution").glob("*.yaml")),
        *sorted((ROOT / "alertissimo" / "data_layer" / "semantic_model").glob("*.yaml")),
        *sorted((ROOT / "alertissimo" / "data_layer" / "providers").glob("**/*.yaml")),
    ]
    return tuple(path.relative_to(ROOT).as_posix() for path in paths)


def _build_wheel(wheel_dir: Path) -> Path:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
        ],
        cwd=ROOT,
        check=True,
    )
    wheels = tuple(wheel_dir.glob("alertissimo-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one Alertissimo wheel, found {len(wheels)}")
    return wheels[0]


def _verify_wheel(wheel: Path) -> int:
    expected_resources = _runtime_resources()
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = [resource for resource in expected_resources if resource not in names]
        if missing:
            raise RuntimeError(
                "wheel is missing runtime declarative resources:\n  "
                + "\n  ".join(missing)
            )

        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise RuntimeError("wheel must contain exactly one METADATA file")
        metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
        if metadata.get("Version") != EXPECTED_VERSION:
            raise RuntimeError(
                f"wheel version {metadata.get('Version')!r} != {EXPECTED_VERSION!r}"
            )
        requirements = metadata.get_all("Requires-Dist") or []
        if not any(requirement.lower().startswith("pyyaml") for requirement in requirements):
            raise RuntimeError("wheel metadata does not declare the PyYAML runtime dependency")

        for name in names:
            if not name.endswith(".dist-info/entry_points.txt"):
                continue
            entry_points = archive.read(name).decode("utf-8")
            if "alertissimo = alertissimo.app_dsl:main" in entry_points:
                raise RuntimeError(
                    "wheel still exposes the Streamlit renderer as a console command"
                )

    return len(expected_resources)


def _verify_installed_wheel(wheel: Path, target: Path) -> str:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ],
        cwd=target.parent,
        check=True,
    )

    code = r'''
from importlib.metadata import version
from pathlib import Path
import os

import alertissimo
from alertissimo.api import validate_dsl
from alertissimo.data_layer.execution import EndpointRegistry, load_execution_policy
from alertissimo.data_layer.semantic_model import load_semantic_model_index

expected_target = Path(os.environ["ALERTISSIMO_CHECK_TARGET"]).resolve()
package_path = Path(alertissimo.__file__).resolve()
if expected_target not in package_path.parents:
    raise RuntimeError(f"imported Alertissimo from source instead of wheel target: {package_path}")
if version("alertissimo") != "0.1.0":
    raise RuntimeError(f"installed metadata version is {version('alertissimo')!r}")

policy = load_execution_policy()
if policy.max_auto_pages != 3:
    raise RuntimeError(f"unexpected packaged execution policy: {policy.max_auto_pages}")

semantic_model = load_semantic_model_index()
if not semantic_model.containers or not semantic_model.fields:
    raise RuntimeError("packaged semantic ontology did not load substantive declarations")

registry = EndpointRegistry()
registry.resolve("alerce", "lsst", "query_objects")

dsl = """objects from ztf via alerce
inside (124.87996115142856, -6.0205001, 1arcsec)
latest 1
"""
validation = validate_dsl(dsl, name="0.1.0 installed-wheel acceptance")
if not validation.is_valid or not validation.is_runnable:
    raise RuntimeError(f"installed-wheel DSL validation failed: {validation!r}")

print(package_path)
'''
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(target)
    environment["ALERTISSIMO_CHECK_TARGET"] = str(target)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=target.parent,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def main() -> int:
    print("=== ALERTISSIMO 0.1.0 RELEASE PACKAGE CHECK ===")
    with tempfile.TemporaryDirectory(prefix="alertissimo-release-") as temporary:
        root = Path(temporary)
        wheel = _build_wheel(root / "wheel")
        resource_count = _verify_wheel(wheel)
        installed_path = _verify_installed_wheel(wheel, root / "installed")

        print(f"wheel:             {wheel.name}")
        print(f"runtime resources: {resource_count} packaged")
        print(f"installed import:  {installed_path}")
        print("public API:        alertissimo.api")
        print("static DSL:        VALID / RUNNABLE")
        print("provider APIs:     not contacted")
        print("PASS: Alertissimo 0.1.0 wheel is self-contained for declarative runtime data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
