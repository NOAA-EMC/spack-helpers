"""Unit tests for create-python-venv command."""

import os
import types

import pytest

import spack.environment as ev
import spack.extensions

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.cmd import create_python_venv as cmd
from spack.error import SpackError


@pytest.fixture
def spack_test_env(tmp_path):
    """Create a temporary Spack environment for command-level tests."""
    env_path = tmp_path / "create_python_venv_env"
    env_path.mkdir(exist_ok=True)
    env = ev.create_in_dir(env_path, with_view=False)
    env.write()
    return env


def test_select_environment_if_needed_uses_active_environment(spack_test_env):
    """If an environment is active, it should be used directly."""
    with spack_test_env:
        selected = cmd._select_environment_if_needed()

    assert selected.path == spack_test_env.path


def test_select_environment_if_needed_selects_from_available(monkeypatch, spack_test_env):
    """If no env is active, command should prompt, read, and activate one."""
    monkeypatch.setattr(ev, "active_environment", lambda: None)
    monkeypatch.setattr(ev, "all_environment_names", lambda: ["unit-env"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")
    monkeypatch.setattr(ev, "read", lambda _name: spack_test_env)

    activated = {}

    def _fake_activate(environment):
        activated["env"] = environment

    monkeypatch.setattr(ev, "activate", _fake_activate)

    selected = cmd._select_environment_if_needed()

    assert selected.path == spack_test_env.path
    assert activated["env"].path == spack_test_env.path


def test_select_environment_if_needed_accepts_path(monkeypatch, spack_test_env):
    """If no env is active, command should accept an arbitrary environment directory path."""
    monkeypatch.setattr(ev, "active_environment", lambda: None)
    monkeypatch.setattr(ev, "all_environment_names", lambda: [])
    monkeypatch.setattr("builtins.input", lambda _prompt: spack_test_env.path)
    monkeypatch.setattr(ev, "environment_from_name_or_dir", lambda path: ev.Environment(path))

    activated = {}

    def _fake_activate(environment):
        activated["env"] = environment

    monkeypatch.setattr(ev, "activate", _fake_activate)

    selected = cmd._select_environment_if_needed()

    assert selected.path == spack_test_env.path
    assert activated["env"].path == spack_test_env.path


def test_select_python_packages_duplicate_names_raise(monkeypatch):
    """Selecting same package name more than once should raise an error."""

    class FakeSpec:
        def __init__(self, name):
            self.name = name
            self.installed = True

    env = types.SimpleNamespace(all_specs=lambda: [FakeSpec("py-numpy"), FakeSpec("py-numpy")])

    monkeypatch.setattr(cmd, "_is_python_package_spec", lambda _spec: True)
    monkeypatch.setattr(
        cmd,
        "_prompt_multi_choice",
        lambda _prompt, options, formatter: [options[0], options[1]],
    )

    with pytest.raises(SpackError, match="multiple specs were selected for the same package name"):
        cmd._select_python_packages(env)


def test_gather_python_paths_uses_python_dependency_layout(tmp_path):
    """Path gathering should use python dependency purelib/platlib directories."""
    prefix = tmp_path / "pkg-prefix"
    purelib = prefix / "lib" / "python3.11" / "site-packages"
    purelib.mkdir(parents=True)

    python_pkg = types.SimpleNamespace(
        purelib=os.path.join("lib", "python3.11", "site-packages"),
        platlib=os.path.join("lib64", "python3.11", "site-packages"),
    )

    python_dep = types.SimpleNamespace(package=python_pkg)

    class FakeSpec:
        def __init__(self, package_prefix):
            self.prefix = str(package_prefix)

        def __getitem__(self, item):
            if item == "python":
                return python_dep
            raise KeyError(item)

    paths = cmd._gather_python_paths([FakeSpec(prefix)])

    assert paths == [str(purelib)]


def test_create_venv_sets_pythonpath(monkeypatch, tmp_path):
    """_create_venv should pass selected paths via PYTHONPATH."""
    python_prefix = tmp_path / "python-prefix"
    python_bin = python_prefix / "bin"
    python_bin.mkdir(parents=True)
    python_exe = python_bin / "python"
    python_exe.write_text("", encoding="utf-8")

    python_spec = types.SimpleNamespace(prefix=str(python_prefix))

    captured = {}

    def _fake_run(command, env=None, check=None):
        captured["command"] = command
        captured["env"] = env
        captured["check"] = check
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(cmd.subprocess, "run", _fake_run)
    monkeypatch.setenv("PYTHONPATH", "/already/present")

    venv_path = tmp_path / "venv"
    paths = ["/from/spack/one", "/from/spack/two"]
    cmd._create_venv(python_spec, str(venv_path), paths)

    assert captured["command"] == [str(python_exe), "-m", "venv", str(venv_path)]
    assert captured["check"] is True
    assert captured["env"]["PYTHONPATH"] == "/from/spack/one:/from/spack/two:/already/present"


def test_build_pip_install_args_from_path_requirements(tmp_path):
    """Path helper should produce -r install args for requirements.txt."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pytest\n", encoding="utf-8")

    args, source = cmd._build_pip_install_args_from_path(str(requirements))

    assert args == ["-r", str(requirements)]
    assert "requirements.txt" in source


def test_build_pip_install_args_from_path_pyproject_file(tmp_path):
    """Path helper should install from project directory when given pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")

    args, source = cmd._build_pip_install_args_from_path(str(pyproject))

    assert args == [str(tmp_path)]
    assert "pyproject.toml" in source


def test_select_pip_install_args_manual_list(monkeypatch):
    """Manual package selection should parse shell-style package tokens."""
    responses = iter(["4", "requests==2.32.0 'urllib3<3'"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    args, source = cmd._select_pip_install_args()

    assert args == ["requests==2.32.0", "urllib3<3"]
    assert source == "manual package list"


def test_install_pip_packages_executes_venv_pip(monkeypatch, tmp_path):
    """pip install should run via the newly-created venv pip binary."""
    venv_path = tmp_path / "venv"
    pip_path = venv_path / "bin" / "pip"
    pip_path.parent.mkdir(parents=True)
    pip_path.write_text("", encoding="utf-8")

    captured = {}

    def _fake_run(command, check=None):
        captured["command"] = command
        captured["check"] = check
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(cmd.subprocess, "run", _fake_run)

    installed = cmd._install_pip_packages(str(venv_path), ["-r", "/tmp/requirements.txt"])

    assert installed is True
    assert captured["command"] == [str(pip_path), "install", "-r", "/tmp/requirements.txt"]
    assert captured["check"] is True


def test_create_python_venv_command_flow(monkeypatch):
    """Top-level command function should coordinate helper calls successfully."""
    fake_env = object()
    fake_python_spec = types.SimpleNamespace(format=lambda _fmt: "python@3.11/abc1234")
    fake_packages = [types.SimpleNamespace(name="py-numpy")]

    monkeypatch.setattr(cmd, "_select_environment_if_needed", lambda: fake_env)
    monkeypatch.setattr(cmd, "_select_python_installation", lambda _env: fake_python_spec)
    monkeypatch.setattr(cmd, "_select_python_packages", lambda _env: fake_packages)
    monkeypatch.setattr(cmd, "_select_pip_install_args", lambda: (["requests"], "manual package list"))
    monkeypatch.setattr(cmd, "_gather_python_paths", lambda _specs: ["/path/one"])
    monkeypatch.setattr(cmd, "_create_venv", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cmd, "_write_integration_pth", lambda *_args, **_kwargs: "/venv/site/spack_selected_packages.pth")
    monkeypatch.setattr(cmd, "_install_pip_packages", lambda *_args, **_kwargs: True)

    messages = []
    monkeypatch.setattr(cmd.tty, "msg", lambda message: messages.append(("msg", message)))
    monkeypatch.setattr(cmd.tty, "warn", lambda message: messages.append(("warn", message)))

    args = types.SimpleNamespace(venv_path="/tmp/test-venv")
    result = cmd.create_python_venv(None, args)

    assert result == 0
    assert any("Created virtual environment" in message for level, message in messages if level == "msg")
    assert any("Integrated package paths" in message for level, message in messages if level == "msg")
    assert any("Installed pip packages" in message for level, message in messages if level == "msg")
