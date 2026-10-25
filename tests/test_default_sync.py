"""GATE-FIX 2: plain uv sync must not remove the working runtime again.

Read project metadata, not the reviewer's already-populated venv. An extra is
NOT part of uv's default set. Check the owner's Python as well as the oldest
supported Python so a dependency marker cannot silently recreate the failure.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parents[1]


def project_metadata():
    return tomllib.loads((REPO / "pyproject.toml").read_text())


def default_requirements(metadata):
    """Project deps + uv's default PEP 735 groups (including nested groups)."""
    groups = metadata.get("dependency-groups", {})
    defaults = metadata.get("tool", {}).get("uv", {}).get("default-groups", ["dev"])
    if defaults == "all":
        defaults = list(groups)

    def expand(group, trail=()):
        assert group not in trail, f"dependency-group cycle: {(*trail, group)}"
        for entry in groups.get(group, []):
            if isinstance(entry, str):
                yield Requirement(entry)
            else:
                yield from expand(entry["include-group"], (*trail, group))

    yield from (Requirement(dep) for dep in metadata["project"].get("dependencies", []))
    for group in defaults:
        yield from expand(group)


@pytest.mark.parametrize("python_version", ["3.11", "3.12", "3.14"])
@pytest.mark.parametrize("package", [
    "google-genai", "httpx", "faster-whisper", "piper-tts", "pytest", "ruff",
])
def test_plain_uv_sync_keeps_runtime_and_dev(package, python_version):
    env = {**default_environment(), "python_version": python_version,
           "python_full_version": python_version + ".0", "sys_platform": "linux",
           "platform_system": "Linux", "extra": ""}
    names = {canonicalize_name(dep.name) for dep in default_requirements(project_metadata())
             if dep.marker is None or dep.marker.evaluate(env)}
    assert package in names, f"plain uv sync on Python {python_version} would omit {package}"


def test_wake_inference_is_optional_and_onnx_only():
    metadata = project_metadata()
    extras = metadata["project"]["optional-dependencies"]
    wake = {canonicalize_name(Requirement(dep).name) for dep in extras["voice"]}
    assert "onnxruntime" in wake
    assert not {"openwakeword", "tflite-runtime"} & wake
    defaults = list(default_requirements(metadata))
    # ONNX Runtime is also a Whisper/Piper transitive dependency: its presence
    # is NOT permission to enable the optional wake path or install its shelf.
    assert all(not {"voice", "wake"} & dep.extras for dep in defaults)
    groups = metadata.get("tool", {}).get("uv", {}).get("default-groups", ["dev"])
    assert groups != "all" and not {"voice", "wake"} & set(groups)


def test_no_extra_can_reintroduce_the_cp311_only_tflite_dependency():
    metadata = project_metadata()
    requirements = list(default_requirements(metadata))
    for deps in metadata["project"]["optional-dependencies"].values():
        requirements.extend(Requirement(dep) for dep in deps)
    names = {canonicalize_name(dep.name) for dep in requirements}
    # openwakeword 0.6 pulls tflite-runtime on Linux even with an ONNX model.
    assert not {"tflite-runtime", "openwakeword"} & names


def test_default_group_includes_are_followed_but_extras_are_not():
    metadata = {
        "project": {"dependencies": ["httpx"],
                    "optional-dependencies": {"voice": ["do-not-install"]}},
        "dependency-groups": {"dev": [{"include-group": "test"}, "ruff"],
                              "test": ["pytest"]},
    }
    assert {dep.name for dep in default_requirements(metadata)} == {"httpx", "pytest", "ruff"}


def test_genuinely_optional_extras_have_exact_setup_commands():
    metadata = project_metadata()
    base = {canonicalize_name(dep.name) for dep in default_requirements(metadata)}
    setup = (REPO / "GETTING-STARTED.md").read_text()
    unit = (REPO / "systemd" / "assistant.service").read_text()
    for name, deps in metadata["project"]["optional-dependencies"].items():
        if {canonicalize_name(Requirement(dep).name) for dep in deps} - base:
            command = f"uv sync --extra {name}"
            assert command in setup, command
            assert command in unit, command


def test_universal_lock_has_no_tflite_in_any_optional_dependency_tree():
    lock = tomllib.loads((REPO / "uv.lock").read_text())
    names = {package["name"] for package in lock["package"]}
    assert not {"tflite-runtime", "openwakeword"} & names
    assert {"google-genai", "faster-whisper", "ctranslate2", "onnxruntime",
            "piper-tts", "pytest", "ruff"} <= names
