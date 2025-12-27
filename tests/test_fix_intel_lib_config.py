"""Unit tests for fix_intel_lib_config functionality."""
import pytest

import spack.config
import spack.environment as ev
import spack.extensions

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.fix_intel_lib_config import fix_intel_lib_config_for_env


@pytest.fixture
def intel_env(tmp_path, monkeypatch):
    """Create a test environment with intel-oneapi-compilers-classic external."""
    env_path = tmp_path / "intel_test_env"
    env_path.mkdir()
    env = ev.create_in_dir(env_path, with_view=False)
    
    env.manifest.configuration['packages'] = {
        'intel-oneapi-compilers-classic': {
            'externals': [
                {
                    'spec': 'intel-oneapi-compilers-classic@2023.2.1',
                    'prefix': '/opt/intel/oneapi/compiler/2023.2.1/linux'
                },
                {
                    'spec': 'intel-oneapi-compilers-classic@2023.1.0',
                    'prefix': '/opt/intel/oneapi/compiler/2023.1.0/linux'
                }
            ]
        }
    }
    env.write()
    
    # Mock spack.config.get to return our test packages config
    original_config_get = spack.config.get
    
    def mock_config_get(key, default=None, scope=None):
        if key == 'packages':
            return env.manifest.configuration.get('packages', {})
        return original_config_get(key, default, scope)
    
    monkeypatch.setattr(spack.config, 'get', mock_config_get)
    
    return env


def test_fix_intel_lib_config_adds_ld_library_path(intel_env):
    """Test that LD_LIBRARY_PATH is added to intel externals."""
    modified_count = fix_intel_lib_config_for_env(intel_env)
    
    assert modified_count == 2
    
    packages = intel_env.manifest.configuration.get('packages', {})
    intel_config = packages['intel-oneapi-compilers-classic:']
    
    for i, external in enumerate(intel_config['externals']):
        prefix = external['prefix']
        expected_path = f"{prefix}/compiler/lib/intel64_lin"
        actual_path = external['extra_attributes']['environment']['prepend_path']['LD_LIBRARY_PATH']
        assert actual_path == expected_path


def test_fix_intel_lib_config_idempotent(intel_env):
    """Test that running twice doesn't modify anything the second time."""
    modified_count1 = fix_intel_lib_config_for_env(intel_env)
    assert modified_count1 == 2
    
    modified_count2 = fix_intel_lib_config_for_env(intel_env)
    assert modified_count2 == 0


def test_fix_intel_lib_config_no_intel_package(tmp_path):
    """Test that function handles absence of intel package gracefully."""
    env_path = tmp_path / "empty_env"
    env_path.mkdir()
    env = ev.create_in_dir(env_path, with_view=False)
    env.write()
    
    modified_count = fix_intel_lib_config_for_env(env)
    assert modified_count == 0
