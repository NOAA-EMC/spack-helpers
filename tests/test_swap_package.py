"""Unit tests for swap-package command."""

import types

import pytest
import spack.environment as ev
import spack.extensions

spack.extensions.load_extension("helpers")
from spack.extensions.helpers.cmd import swap_package as cmd


@pytest.fixture
def swap_package_env(tmp_path):
    """Create a real Spack environment with roots used by swap-package flow tests."""
    env_path = tmp_path / "swap_package_env"
    env_path.mkdir(exist_ok=True)
    env = ev.create_in_dir(env_path, with_view=False)
    env.add("zlib")
    env.add("hdf5")
    env.add("netcdf-c")
    env.add("cmake")
    env.write()
    return env


def test_compute_possible_transitive_dependents(monkeypatch):
    """Package-level dependent closure should include selected package and transitive dependents."""
    monkeypatch.setattr(cmd.dependents_cmd, "inverted_dependencies", lambda: {"zlib": {"hdf5"}})
    monkeypatch.setattr(
        cmd.dependents_cmd,
        "get_dependents",
        lambda pkg_name, ideps, transitive: {"hdf5", "netcdf-c"},
    )

    result = cmd._compute_possible_transitive_dependents("zlib")

    assert result == {"zlib", "hdf5", "netcdf-c"}


def test_set_buildability_for_allowed_packages_preserves_existing_config():
    """Buildability rewrite should preserve unrelated package settings while updating allowed names."""
    env = types.SimpleNamespace(
        manifest=types.SimpleNamespace(
            configuration={
                "packages": {
                    "cmake": {"version": ["3.28.3"]},
                    "hdf5": {"variants": "+fortran", "buildable": False},
                }
            },
            changed=False,
        )
    )

    cmd._set_buildability_for_allowed_packages(env, {"hdf5", "netcdf-c"})

    packages = env.manifest.configuration["packages"]
    assert packages["all"]["buildable"] is False
    assert packages["hdf5"]["buildable"] is True
    assert packages["hdf5"]["variants"] == "+fortran"
    assert packages["netcdf-c"]["buildable"] is True
    assert packages["cmake"]["version"] == ["3.28.3"]
    assert env.manifest.changed is True


def test_swap_package_command_flow(monkeypatch, swap_package_env):
    """Top-level command should remove selected names, update buildability, and concretize fresh without force."""

    class _OverrideCtx:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    override_calls = []
    concretize_calls = []

    def _fake_concretize(force=None, tests=False):
        concretize_calls.append((force, tests))
        return []

    monkeypatch.setattr(swap_package_env, "concretize", _fake_concretize)
    monkeypatch.setattr(cmd.spack.cmd, "disambiguate_spec", lambda spec, _env: types.SimpleNamespace(name=spec.name))
    monkeypatch.setattr(
        cmd.spack.config,
        "override",
        lambda key, value: (override_calls.append((key, value)) or _OverrideCtx()),
    )

    fake_parent_specs = [types.SimpleNamespace(name="hdf5"), types.SimpleNamespace(name="netcdf-c")]
    monkeypatch.setattr(
        cmd.spack.store.STORE.db,
        "installed_relatives",
        lambda selected, relation, transitive=True: fake_parent_specs,
    )
    monkeypatch.setattr(
        cmd,
        "_compute_possible_transitive_dependents",
        lambda name: {"zlib", "hdf5", "netcdf-c", "parallel-netcdf"},
    )

    msgs = []
    monkeypatch.setattr(cmd.tty, "msg", lambda message: msgs.append(message))
    monkeypatch.setattr(cmd.tty, "warn", lambda _message: None)

    args = types.SimpleNamespace(package_spec="zlib@1.3.1", fresh=True)
    with swap_package_env:
        result = cmd.swap_package(None, args)

    assert result == 0
    # Selected package + installed dependents should be removed while non-dependents stay.
    assert {spec.name for spec in swap_package_env.user_specs} == {"cmake"}
    # Global buildability gate should be closed, then selectively reopened for allowed names.
    assert swap_package_env.manifest.configuration["packages"]["all"]["buildable"] is False
    assert swap_package_env.manifest.configuration["packages"]["zlib"]["buildable"] is True
    assert swap_package_env.manifest.configuration["packages"]["parallel-netcdf"]["buildable"] is True
    # --fresh should map to concretizer reuse policy, not force concretization.
    assert override_calls == [("concretizer:reuse", False)]
    assert concretize_calls == [(None, False)]
    # User-facing summary should include the removal message path.
    assert any("Removed" in message for message in msgs)
