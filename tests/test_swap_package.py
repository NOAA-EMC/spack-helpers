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
    monkeypatch.setattr(
        cmd.spack.config.CONFIG,
        "override",
        lambda key, value: (override_calls.append((key, value)) or _OverrideCtx()),
    )

    monkeypatch.setattr(
        cmd,
        "_compute_possible_transitive_dependents",
        lambda name: {"zlib", "hdf5", "netcdf-c", "parallel-netcdf"},
    )

    msgs = []
    monkeypatch.setattr(cmd.tty, "msg", lambda message: msgs.append(message))
    monkeypatch.setattr(cmd.tty, "warn", lambda _message: None)

    args = types.SimpleNamespace(
        package_spec="zlib@1.3.1",
        concretize=True,
        dependent_spec=[],
        uninstall_removed=False,
    )
    with swap_package_env:
        result = cmd.swap_package(None, args)

    assert result == 0
    # Selected package and dependents are re-added (by name only); non-dependents remain.
    assert {spec.name for spec in swap_package_env.user_specs} == {"cmake", "zlib", "hdf5", "netcdf-c"}
    # The selected root should match the user-requested spec constraint.
    assert any(spec.satisfies("zlib@1.3.1") for spec in swap_package_env.user_specs)
    # Global buildability gate should be closed, then selectively reopened for allowed names.
    assert swap_package_env.manifest.configuration["packages"]["all"]["buildable"] is False
    assert swap_package_env.manifest.configuration["packages"]["zlib"]["buildable"] is True
    assert swap_package_env.manifest.configuration["packages"]["parallel-netcdf"]["buildable"] is True
    # --fresh should map to concretizer reuse policy, not force concretization.
    assert override_calls == [("concretizer:reuse", False)]
    assert concretize_calls == [(None, False)]
    # User-facing summary should include the removal message path.
    assert any("Removed" in message for message in msgs)


def test_swap_package_readd_dependents_by_name_and_spec(monkeypatch, swap_package_env):
    """Re-add removed dependents by package name and allow explicit spec overrides."""

    monkeypatch.setattr(
        cmd,
        "_compute_possible_transitive_dependents",
        lambda name: {"zlib", "hdf5", "netcdf-c", "parallel-netcdf"},
    )

    msgs = []
    monkeypatch.setattr(cmd.tty, "msg", lambda message: msgs.append(message))
    monkeypatch.setattr(cmd.tty, "warn", lambda _message: None)

    args = types.SimpleNamespace(
        package_spec="zlib@1.3.1",
        concretize=False,
        dependent_spec=["hdf5@1.14.0"],
        uninstall_removed=False,
    )

    with swap_package_env:
        result = cmd.swap_package(None, args)

    assert result == 0
    user_specs_by_name = {spec.name: spec for spec in swap_package_env.user_specs}
    assert set(user_specs_by_name) == {"cmake", "zlib", "hdf5", "netcdf-c"}
    assert user_specs_by_name["hdf5"].satisfies("hdf5@1.14.0")
    assert swap_package_env.manifest.configuration["packages"]["hdf5"]["buildable"] is True
    assert swap_package_env.manifest.configuration["packages"]["netcdf-c"]["buildable"] is True
    assert any("Added" in message for message in msgs)


def test_swap_package_adds_selected_when_missing(monkeypatch, swap_package_env):
    """If selected package is not already an environment root, command should warn and add it."""
    monkeypatch.setattr(
        cmd,
        "_compute_possible_transitive_dependents",
        lambda name: {"libpng"},
    )

    warns = []
    msgs = []
    monkeypatch.setattr(cmd.tty, "warn", lambda message: warns.append(message))
    monkeypatch.setattr(cmd.tty, "msg", lambda message: msgs.append(message))

    args = types.SimpleNamespace(
        package_spec="libpng@1.6.43",
        concretize=False,
        dependent_spec=[],
        uninstall_removed=False,
    )

    with swap_package_env:
        result = cmd.swap_package(None, args)

    assert result == 0
    user_spec_names = {spec.name for spec in swap_package_env.user_specs}
    assert "libpng" in user_spec_names
    assert "cmake" in user_spec_names
    assert any("not a root" in message for message in warns)
    assert any("Added" in message for message in msgs)


def test_swap_package_optional_uninstall_removed(monkeypatch, swap_package_env):
    """Uninstall of removed packages should only occur when explicitly requested."""
    monkeypatch.setattr(
        cmd,
        "_compute_possible_transitive_dependents",
        lambda name: {"zlib", "hdf5", "netcdf-c"},
    )

    uninstall_calls = []
    monkeypatch.setattr(
        cmd,
        "_uninstall_installed_packages_by_name",
        lambda _env, package_names: uninstall_calls.append(set(package_names)) or [],
    )
    monkeypatch.setattr(cmd.tty, "warn", lambda _message: None)
    monkeypatch.setattr(cmd.tty, "msg", lambda _message: None)

    args = types.SimpleNamespace(
        package_spec="zlib@1.3.1",
        concretize=False,
        dependent_spec=[],
        uninstall_removed=True,
    )

    with swap_package_env:
        result = cmd.swap_package(None, args)

    assert result == 0
    assert uninstall_calls == [{"zlib", "hdf5", "netcdf-c"}]


def test_swap_package_adds_non_root_with_version_constraint(monkeypatch, swap_package_env):
    """Selecting a package not currently in the environment should add it with the requested version."""
    # Mock the package-level dependent discovery
    monkeypatch.setattr(
        cmd,
        "_compute_possible_transitive_dependents",
        lambda _name: {"gmake", "autoconf"},
    )

    warns = []
    monkeypatch.setattr(cmd.tty, "warn", lambda message: warns.append(message))
    monkeypatch.setattr(cmd.tty, "msg", lambda _message: None)

    args = types.SimpleNamespace(
        package_spec="gmake@4.2",
        concretize=False,
        dependent_spec=[],
        uninstall_removed=False,
    )

    with swap_package_env:
        result = cmd.swap_package(None, args)

    assert result == 0
    # gmake should be added with the requested version
    user_specs_by_name = {spec.name: spec for spec in swap_package_env.user_specs}
    assert "gmake" in user_specs_by_name
    assert user_specs_by_name["gmake"].satisfies("gmake@4.2")
    assert any("not a root" in message for message in warns)


def test_swap_package_adds_requested_spec_when_it_is_only_root(monkeypatch, tmp_path):
    """Regression: swapping should keep the user-requested selected spec as a root."""
    env_path = tmp_path / "swap_single_root_env"
    env_path.mkdir(exist_ok=True)
    env = ev.create_in_dir(env_path, with_view=False)
    env.add("zlib@1.2")
    env.write()

    monkeypatch.setattr(cmd, "_compute_possible_transitive_dependents", lambda _name: {"zlib"})
    monkeypatch.setattr(cmd.tty, "warn", lambda _message: None)
    monkeypatch.setattr(cmd.tty, "msg", lambda _message: None)

    args = types.SimpleNamespace(
        package_spec="zlib@1.3.1",
        concretize=False,
        dependent_spec=[],
        uninstall_removed=False,
    )

    with env:
        result = cmd.swap_package(None, args)

    assert result == 0
    user_specs = list(env.user_specs)
    # Only zlib is in the environment and it has no dependents, so it remains alone
    assert len(user_specs) == 1
    assert user_specs[0].name == "zlib"
    assert user_specs[0].satisfies("zlib@1.3.1")


def test_swap_package_readd_dependents_name_only_removes_versioned_root(monkeypatch, tmp_path):
    """Dependent roots should be removed and re-added by name-only when requested."""
    env_path = tmp_path / "swap_readd_name_only_env"
    env_path.mkdir(exist_ok=True)
    env = ev.create_in_dir(env_path, with_view=False)
    env.add("gmake@4.4.1")
    env.add("gmake@4.3")
    env.add("cmake@3")
    env.add("gcc-runtime")
    env.write()

    # Simulate no installed-dependent matches so graph-based root filtering is exercised.
    monkeypatch.setattr(cmd, "_compute_possible_transitive_dependents", lambda _name: {"gmake", "cmake"})
    monkeypatch.setattr(cmd.tty, "warn", lambda _message: None)
    monkeypatch.setattr(cmd.tty, "msg", lambda _message: None)

    args = types.SimpleNamespace(
        package_spec="gmake@4.2",
        concretize=False,
        dependent_spec=[],
        uninstall_removed=False,
    )

    with env:
        result = cmd.swap_package(None, args)

    assert result == 0
    user_specs_by_name = {spec.name: spec for spec in env.user_specs}
    assert set(user_specs_by_name) == {"gmake", "cmake", "gcc-runtime"}
    assert user_specs_by_name["gmake"].satisfies("gmake@4.2")
    assert str(user_specs_by_name["cmake"]) == "cmake"
