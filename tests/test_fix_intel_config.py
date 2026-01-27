"""Unit tests for fix_intel_config functionality."""
import pytest

import spack.config
import spack.environment as ev
import spack.extensions

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.fix_intel_config import (
    fix_intel_lib_config_for_env,
    consolidate_intel_oneapi_compilers
)


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
        actual_path = external['extra_attributes']['environment']['append_path']['LD_LIBRARY_PATH']
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


@pytest.fixture
def oneapi_compilers_env(tmp_path, monkeypatch):
    """Create a test environment with intel-oneapi-compilers externals to consolidate."""
    env_path = tmp_path / "oneapi_test_env"
    env_path.mkdir()
    env = ev.create_in_dir(env_path, with_view=False)
    
    env.manifest.configuration['packages'] = {
        'intel-oneapi-compilers': {
            'externals': [
                {
                    'spec': 'intel-oneapi-compilers@2025.3.1 languages=c,cxx',
                    'prefix': '/opt/intel/oneapi/compilers/2025.3.1',
                    'extra_attributes': {
                        'compilers': {
                            'c': '/opt/intel/oneapi/compilers/2025.3.1/bin/icx',
                            'cxx': '/opt/intel/oneapi/compilers/2025.3.1/bin/icpx'
                        }
                    }
                },
                {
                    'spec': 'intel-oneapi-compilers@2025.3.0 languages=fortran',
                    'prefix': '/opt/intel/oneapi/compilers/2025.3.0',
                    'extra_attributes': {
                        'compilers': {
                            'fortran': '/opt/intel/oneapi/compilers/2025.3.0/bin/ifx'
                        }
                    }
                },
                {
                    'spec': 'intel-oneapi-compilers@2024.2.1 languages=c,cxx,fortran',
                    'prefix': '/opt/intel/oneapi/compilers/2024.2.1'
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


def test_consolidate_intel_oneapi_compilers(oneapi_compilers_env):
    """Test that intel-oneapi-compilers externals are consolidated by version."""
    consolidated_count = consolidate_intel_oneapi_compilers(oneapi_compilers_env)
    
    # Should consolidate the 2025.3.x pair
    assert consolidated_count == 1
    
    packages = oneapi_compilers_env.manifest.configuration.get('packages', {})
    intel_config = packages['intel-oneapi-compilers:']
    externals = intel_config['externals']
    
    # Should have 2 externals: the consolidated 2025.3 and the complete 2024.2.1
    assert len(externals) == 2
    
    # Find the consolidated external
    consolidated = None
    complete = None
    for ext in externals:
        if '@2025.3' in ext['spec']:
            consolidated = ext
        elif '@2024.2.1' in ext['spec']:
            complete = ext
    
    assert consolidated is not None
    assert complete is not None
    
    # Check that consolidated has all languages
    assert 'languages=c,cxx,fortran' in consolidated['spec']
    
    # Check that extra_attributes were merged
    assert 'extra_attributes' in consolidated
    assert 'compilers' in consolidated['extra_attributes']
    compilers = consolidated['extra_attributes']['compilers']
    assert 'c' in compilers
    assert 'cxx' in compilers
    assert 'fortran' in compilers


def test_consolidate_no_matching_pairs(tmp_path, monkeypatch):
    """Test that consolidation handles cases with no matching pairs."""
    env_path = tmp_path / "no_match_env"
    env_path.mkdir()
    env = ev.create_in_dir(env_path, with_view=False)
    
    env.manifest.configuration['packages'] = {
        'intel-oneapi-compilers': {
            'externals': [
                {
                    'spec': 'intel-oneapi-compilers@2025.3.1 languages=c,cxx',
                    'prefix': '/opt/intel/oneapi/compilers/2025.3.1'
                },
                {
                    'spec': 'intel-oneapi-compilers@2024.2.0 languages=fortran',
                    'prefix': '/opt/intel/oneapi/compilers/2024.2.0'
                }
            ]
        }
    }
    env.write()
    
    # Mock spack.config.get
    original_config_get = spack.config.get
    
    def mock_config_get(key, default=None, scope=None):
        if key == 'packages':
            return env.manifest.configuration.get('packages', {})
        return original_config_get(key, default, scope)
    
    monkeypatch.setattr(spack.config, 'get', mock_config_get)
    
    consolidated_count = consolidate_intel_oneapi_compilers(env)
    
    # Should not consolidate anything (different major.minor versions)
    assert consolidated_count == 0


def test_consolidate_idempotent(oneapi_compilers_env):
    """Test that running consolidation twice doesn't modify anything the second time."""
    consolidated_count1 = consolidate_intel_oneapi_compilers(oneapi_compilers_env)
    assert consolidated_count1 == 1
    
    # Run again - should find nothing to consolidate
    consolidated_count2 = consolidate_intel_oneapi_compilers(oneapi_compilers_env)
    assert consolidated_count2 == 0


def test_consolidate_no_oneapi_package(tmp_path, monkeypatch):
    """Test that function handles absence of intel-oneapi-compilers gracefully."""
    env_path = tmp_path / "empty_env"
    env_path.mkdir()
    env = ev.create_in_dir(env_path, with_view=False)
    env.write()
    
    # Mock spack.config.get to return empty packages
    original_config_get = spack.config.get
    
    def mock_config_get(key, default=None, scope=None):
        if key == 'packages':
            return env.manifest.configuration.get('packages', {})
        return original_config_get(key, default, scope)
    
    monkeypatch.setattr(spack.config, 'get', mock_config_get)
    
    consolidated_count = consolidate_intel_oneapi_compilers(env)
    assert consolidated_count == 0
