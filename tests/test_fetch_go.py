"""Unit tests for fetch_go module."""
import os
import subprocess

import pytest

import spack.config
import spack.environment as ev
import spack.spec
import spack.extensions

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.fetch_go import *

def find_system_go():
    """Find the system go executable and determine its version and prefix."""
    go_exe = None
    for search_path in os.environ.get("PATH", "").split(os.pathsep):
        potential_go = os.path.join(search_path, "go")
        if os.path.isfile(potential_go) and os.access(potential_go, os.X_OK):
            go_exe = potential_go
            break
    
    if not go_exe:
        return None, None, None
    
    # Get go version
    try:
        result = subprocess.run([go_exe, "version"], capture_output=True, text=True, check=True)
        # Parse version from output like "go version go1.21.0 linux/amd64"
        version_str = result.stdout.split()[2].replace("go", "")
    except Exception:
        return None, None, None
    
    # Get go prefix (one level up from bin)
    go_prefix = os.path.dirname(os.path.dirname(go_exe))
    
    return go_exe, version_str, go_prefix


@pytest.mark.integration
def test_fetch_go_dependencies_with_external_go(tmp_path):
    """Test fetch_go_dependencies with gh package in an environment.
    
    This test creates an environment, adds a 'go' external package,
    adds 'gh' (GitHub CLI which depends on go) to the environment,
    concretizes it, then runs fetch_go_dependencies() on the concrete gh spec.
    """
    # Find system go
    go_exe, go_version, go_prefix = find_system_go()
    if not go_exe:
        pytest.skip("Go executable not found in PATH - skipping test")
    
    # Create environment
    env_path = tmp_path / "test_env"
    env_path.mkdir(exist_ok=False)
    env = ev.create_in_dir(env_path, with_view=False)
    
    # Configure go as external in the environment using Spack config
    externals_config = {
        "go": {
            "externals": [
                {
                    "spec": f"go@{go_version}",
                    "prefix": go_prefix
                }
            ],
            "buildable": False
        }
    }
    
    with spack.config.CONFIG.override("packages", externals_config):
        # Add gh spec to environment
        gh_spec = spack.spec.Spec("gh")
        env.add(gh_spec)
        env.write()
        
        # Concretize the environment
        env.concretize()
        env.write()
        
        # Get the concrete gh spec
        concrete_specs = env.concrete_roots()
        gh_concrete = None
        for spec in concrete_specs:
            if spec.name == "gh":
                gh_concrete = spec
                break
        
        assert gh_concrete is not None, "Could not find concrete gh spec"
        assert gh_concrete.concrete, "gh spec is not concrete"
        
        # Check that gh depends on go
        assert "go" in gh_concrete, "gh should depend on go"
        
        # Set GOMODCACHE to a temporary directory
        gomodcache = tmp_path / "gomodcache"
        gomodcache.mkdir()
        old_gomodcache = os.environ.get("GOMODCACHE")
        os.environ["GOMODCACHE"] = str(gomodcache)
        
        try:
            # Run fetch_go_dependencies on the concrete gh spec
            fetch_go_dependencies([gh_concrete], use_spack_go=False)
            
            # Verify that the GOMODCACHE directory has been populated
            # (it should contain downloaded modules)
            cache_contents = list(gomodcache.iterdir())
            assert len(cache_contents) > 0, "GOMODCACHE should contain downloaded modules"
        finally:
            # Restore environment variable
            if old_gomodcache is None:
                os.environ.pop("GOMODCACHE", None)
            else:
                os.environ["GOMODCACHE"] = old_gomodcache


@pytest.mark.integration
def test_fetch_go_dependencies_with_spack_go(tmp_path):
    """Test fetch_go_dependencies with Spack-installed go (use_spack_go=True).
    
    This test creates an environment, adds 'gh' (GitHub CLI which depends on go),
    concretizes it, installs the go dependency via Spack, then runs 
    fetch_go_dependencies() with use_spack_go=True.
    """
    # Create environment
    env_path = tmp_path / "test_env"
    env_path.mkdir(exist_ok=False)
    env = ev.create_in_dir(env_path, with_view=False)
    
    # Add gh spec to environment (go will be a dependency)
    gh_spec = spack.spec.Spec("gh")
    env.add(gh_spec)
    env.write()
    
    # Concretize the environment
    env.concretize()
    env.write()
    
    # Get the concrete gh spec
    concrete_specs = env.concrete_roots()
    gh_concrete = None
    for spec in concrete_specs:
        if spec.name == "gh":
            gh_concrete = spec
            break
    
    assert gh_concrete is not None, "Could not find concrete gh spec"
    assert gh_concrete.concrete, "gh spec is not concrete"
    
    # Check that gh depends on go
    assert "go" in gh_concrete, "gh should depend on go"
    
    # Get the go dependency
    go_spec = gh_concrete["go"]
    assert go_spec.concrete, "go spec should be concrete"
    
    # Install the go dependency
    installer = PackageInstaller([go_spec.package])
    installer.install()
    
    # Verify go is installed
    assert go_spec.installed, "go should be installed"
    go_exe_path = os.path.join(go_spec.prefix.bin, "go")
    assert os.path.exists(go_exe_path), f"go executable should exist at {go_exe_path}"
    
    # Set GOMODCACHE to a temporary directory
    gomodcache = tmp_path / "gomodcache"
    gomodcache.mkdir()
    old_gomodcache = os.environ.get("GOMODCACHE")
    os.environ["GOMODCACHE"] = str(gomodcache)
    
    # Run fetch_go_dependencies with use_spack_go=True
    # This should use the Spack-installed go
    fetch_go_dependencies([gh_concrete], use_spack_go=True)
        
    # Verify that the GOMODCACHE directory has been populated
    # (it should contain downloaded modules)
    cache_contents = list(gomodcache.iterdir())
    assert len(cache_contents) > 0, "GOMODCACHE should contain downloaded modules"



def test_fetch_go_dependencies_empty_list():
    """Test fetch_go_dependencies with an empty list of specs."""
    # This should not raise any errors
    fetch_go_dependencies([])


def test_fetch_go_dependencies_non_concrete_spec():
    """Test fetch_go_dependencies with non-concrete specs.
    
    The function should skip non-concrete specs.
    """
    # Create a simple spec that is not concrete
    spec = spack.spec.Spec("zlib")
    
    # This should not raise any errors (spec is skipped because not concrete)
    fetch_go_dependencies([spec])
