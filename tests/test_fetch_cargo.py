"""Unit tests for fetch_cargo module."""
import os
import subprocess

import pytest

import spack.config
import spack.environment as ev
import spack.spec
import spack.extensions

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.fetch_cargo import *


def find_system_python():
    """Find the system python executable and determine its version and prefix."""
    python_exe = None
    for search_path in os.environ.get("PATH", "").split(os.pathsep):
        potential_python = os.path.join(search_path, "python3")
        if os.path.isfile(potential_python) and os.access(potential_python, os.X_OK):
            python_exe = potential_python
            break
    
    if not python_exe:
        return None, None, None
    
    # Get python version
    try:
        result = subprocess.run([python_exe, "--version"], capture_output=True, text=True, check=True)
        # Parse version from output like "Python 3.10.12"
        version_str = result.stdout.split()[1]
    except Exception:
        return None, None, None
    
    # Get python prefix
    try:
        result = subprocess.run(
            [python_exe, "-c", "import sys; print(sys.prefix)"],
            capture_output=True,
            text=True,
            check=True
        )
        python_prefix = result.stdout.strip()
    except Exception:
        return None, None, None
    
    return python_exe, version_str, python_prefix


@pytest.mark.integration
def test_fetch_cargo_dependencies_with_external_rust(tmp_path):
    """Test fetch_cargo_dependencies with py-maturin package in an environment.
    
    This test creates an environment, adds a 'python' external package,
    adds 'py-maturin' (which depends on rust) to the environment,
    concretizes it, then runs fetch_cargo_dependencies() on the concrete py-maturin spec.
    """
    # Find system python
    python_exe, python_version, python_prefix = find_system_python()
    if not python_exe:
        pytest.skip("Python executable not found in PATH - skipping test")
    
    # Create environment
    env_path = tmp_path / "test_env"
    env_path.mkdir(exist_ok=False)
    env = ev.create_in_dir(env_path, with_view=False)
    
    # Configure python as external in the environment using Spack config
    externals_config = {
        "python": {
            "externals": [
                {
                    "spec": f"python@{python_version}",
                    "prefix": python_prefix
                }
            ],
            "buildable": False
        }
    }
    
    with spack.config.CONFIG.override("packages", externals_config):
        # Add py-maturin spec to environment
        maturin_spec = spack.spec.Spec("py-maturin@1.9.6")
        env.add(maturin_spec)
        env.write()
        
        # Concretize the environment
        env.concretize()
        env.write()
        
        # Get the concrete py-maturin spec
        concrete_specs = env.concrete_roots()
        maturin_concrete = None
        for spec in concrete_specs:
            if spec.name == "py-maturin":
                maturin_concrete = spec
                break
        
        assert maturin_concrete is not None, "Could not find concrete py-maturin spec"
        assert maturin_concrete.concrete, "py-maturin spec is not concrete"
        
        # Check that py-maturin depends on rust
        assert "rust" in maturin_concrete, "py-maturin should depend on rust"
        
        # Set CARGO_HOME to a temporary directory
        cargo_home = tmp_path / "cargo_home"
        cargo_home.mkdir()
        old_cargo_home = os.environ.get("CARGO_HOME")
        os.environ["CARGO_HOME"] = str(cargo_home)
        
        try:
            # Run fetch_cargo_dependencies on the concrete py-maturin spec
            fetch_cargo_dependencies([maturin_concrete], use_spack_rust=False)
            
            # Verify that the CARGO_HOME directory has been populated
            # (it should contain downloaded dependencies)
            cache_contents = list(cargo_home.iterdir())
            assert len(cache_contents) > 0, "CARGO_HOME should contain downloaded dependencies"
        finally:
            # Restore environment variable
            if old_cargo_home is None:
                os.environ.pop("CARGO_HOME", None)
            else:
                os.environ["CARGO_HOME"] = old_cargo_home


@pytest.mark.integration
def test_fetch_cargo_dependencies_with_spack_rust(tmp_path):
    """Test fetch_cargo_dependencies with Spack-installed rust (use_spack_rust=True).
    
    This test creates an environment, adds 'py-maturin' (which depends on rust),
    concretizes it, installs the rust dependency via Spack, then runs 
    fetch_cargo_dependencies() with use_spack_rust=True.
    """
    # Find system python
    python_exe, python_version, python_prefix = find_system_python()
    if not python_exe:
        pytest.skip("Python executable not found in PATH - skipping test")
    
    # Create environment
    env_path = tmp_path / "test_env"
    env_path.mkdir(exist_ok=False)
    env = ev.create_in_dir(env_path, with_view=False)
    
    # Configure python as external in the environment using Spack config
    externals_config = {
        "python": {
            "externals": [
                {
                    "spec": f"python@{python_version}",
                    "prefix": python_prefix
                }
            ],
            "buildable": False
        }
    }
    
    with spack.config.CONFIG.override("packages", externals_config):
        # Add py-maturin spec to environment (rust will be a dependency)
        maturin_spec = spack.spec.Spec("py-maturin")
        env.add(maturin_spec)
        env.write()
        
        # Concretize the environment
        env.concretize()
        env.write()
        
        # Get the concrete py-maturin spec
        concrete_specs = env.concrete_roots()
        maturin_concrete = None
        for spec in concrete_specs:
            if spec.name == "py-maturin":
                maturin_concrete = spec
                break
        
        assert maturin_concrete is not None, "Could not find concrete py-maturin spec"
        assert maturin_concrete.concrete, "py-maturin spec is not concrete"
        
        # Check that py-maturin depends on rust
        assert "rust" in maturin_concrete, "py-maturin should depend on rust"
        
        # Get the rust dependency
        rust_spec = maturin_concrete["rust"]
        assert rust_spec.concrete, "rust spec should be concrete"
        
        # Install the rust dependency
        installer = PackageInstaller([rust_spec.package])
        installer.install()
        
        # Verify rust is installed
        assert rust_spec.installed, "rust should be installed"
        cargo_exe_path = os.path.join(rust_spec.prefix.bin, "cargo")
        assert os.path.exists(cargo_exe_path), f"cargo executable should exist at {cargo_exe_path}"
        
        # Set CARGO_HOME to a temporary directory
        cargo_home = tmp_path / "cargo_home"
        cargo_home.mkdir()
        old_cargo_home = os.environ.get("CARGO_HOME")
        os.environ["CARGO_HOME"] = str(cargo_home)
        
        try:
            # Run fetch_cargo_dependencies with use_spack_rust=True
            # This should use the Spack-installed rust
            fetch_cargo_dependencies([maturin_concrete], use_spack_rust=True)
            
            # Verify that the CARGO_HOME directory has been populated
            # (it should contain downloaded dependencies)
            cache_contents = list(cargo_home.iterdir())
            assert len(cache_contents) > 0, "CARGO_HOME should contain downloaded dependencies"
        finally:
            # Restore environment variable
            if old_cargo_home is None:
                os.environ.pop("CARGO_HOME", None)
            else:
                os.environ["CARGO_HOME"] = old_cargo_home


def test_fetch_cargo_dependencies_empty_list():
    """Test fetch_cargo_dependencies with an empty list of specs."""
    # This should not raise any errors
    fetch_cargo_dependencies([])


def test_fetch_cargo_dependencies_non_concrete_spec():
    """Test fetch_cargo_dependencies with non-concrete specs.
    
    The function should skip non-concrete specs.
    """
    # Create a simple spec that is not concrete
    spec = spack.spec.Spec("zlib")
    
    # This should not raise any errors (spec is skipped because not concrete)
    fetch_cargo_dependencies([spec])
