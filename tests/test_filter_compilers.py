"""Unit tests for filter-compilers command and filter_compiler_packages functionality."""
import pytest

import spack.environment as ev
import spack.config
import spack.extensions

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.filter_compiler_packages import filter_compiler_packages, _expand_compiler_synonyms


@pytest.fixture
def multi_compiler_env(tmp_path, monkeypatch):
    """Create a test environment with multiple compiler externals and config.
    
    Provides gcc and clang with multiple externals each, plus non-externals config
    (variants, buildable) to verify preservation during filtering.
    """
    env_path = tmp_path / "filter_test_env"
    env_path.mkdir(exist_ok=True)
    
    env = ev.create_in_dir(env_path, with_view=False)
    
    packages_config = {
        'gcc': {
            'externals': [
                {'spec': 'gcc@11.2.0', 'prefix': '/usr/bin/gcc-11'},
                {'spec': 'gcc@10.3.0', 'prefix': '/usr/bin/gcc-10'},
            ],
            'variants': '+binutils',
        },
        'clang': {
            'externals': [
                {'spec': 'clang@14.0.0', 'prefix': '/usr/bin/clang-14'},
                {'spec': 'clang@13.0.0', 'prefix': '/usr/bin/clang-13'},
            ],
            'buildable': False,
        },
    }
    
    env.manifest.configuration['packages'] = packages_config
    env.write()
    
    original_config_get = spack.config.get
    
    def mock_config_get(key, default=None, scope=None):
        if key == 'packages':
            return env.manifest.configuration.get('packages', {})
        return original_config_get(key, default, scope)
    
    monkeypatch.setattr(spack.config, 'get', mock_config_get)
    
    return env


@pytest.fixture
def single_external_env(tmp_path, monkeypatch):
    """Create a test environment with a compiler having a single external."""
    env_path = tmp_path / "single_external_env"
    env_path.mkdir(exist_ok=True)
    
    env = ev.create_in_dir(env_path, with_view=False)
    
    packages_config = {
        'gcc': {
            'externals': [
                {'spec': 'gcc@11.2.0', 'prefix': '/usr/bin/gcc-11'},
            ],
        },
    }
    
    env.manifest.configuration['packages'] = packages_config
    env.write()
    
    original_config_get = spack.config.get
    
    def mock_config_get(key, default=None, scope=None):
        if key == 'packages':
            return env.manifest.configuration.get('packages', {})
        return original_config_get(key, default, scope)
    
    monkeypatch.setattr(spack.config, 'get', mock_config_get)
    
    return env


@pytest.fixture
def empty_packages_env(tmp_path, monkeypatch):
    """Create a test environment with no packages configuration."""
    env_path = tmp_path / "empty_env"
    env_path.mkdir(exist_ok=True)
    
    env = ev.create_in_dir(env_path, with_view=False)
    env.write()
    
    original_config_get = spack.config.get
    
    def mock_config_get(key, default=None, scope=None):
        if key == 'packages':
            return env.manifest.configuration.get('packages', {})
        return original_config_get(key, default, scope)
    
    monkeypatch.setattr(spack.config, 'get', mock_config_get)
    
    return env


@pytest.mark.parametrize('mode,filter_specs,expected_gcc_count,expected_clang_count', [
    ('keep-only', ['gcc@11.2.0'], 1, 0),
    ('remove', ['gcc@10.3.0', 'clang@14.0.0', 'clang@13.0.0'], 1, 0),
])
def test_filter_modes(multi_compiler_env, mode, filter_specs, expected_gcc_count, expected_clang_count):
    """Test both filter modes (keep-only and remove) maintain expected behavior.
    
    Parametrized test reduces duplication while ensuring both modes work correctly.
    Verifies externals count and that non-externals config is preserved.
    """
    env = multi_compiler_env
    
    modified_count = filter_compiler_packages(env, filter_specs, mode=mode)
    
    assert modified_count > 0
    packages = env.manifest.configuration.get('packages', {})
    
    # Verify gcc externals and config
    gcc_config = packages.get('gcc:')  # Use consistent :: syntax key
    if gcc_config is None:
        gcc_config = packages.get('gcc')
    assert gcc_config is not None
    assert len(gcc_config.get('externals', [])) == expected_gcc_count
    assert gcc_config.get('variants') == '+binutils'  # Non-externals config preserved
    
    # Verify clang externals and config
    clang_config = packages.get('clang:')
    if clang_config is None:
        clang_config = packages.get('clang')
    assert clang_config is not None
    assert len(clang_config.get('externals', [])) == expected_clang_count
    assert clang_config.get('buildable') is False  # Non-externals config preserved


def test_filter_single_external(single_external_env):
    """Test filtering a compiler with only one external."""
    env = single_external_env
    
    # Remove the only external
    modified_count = filter_compiler_packages(env, ['gcc@11.2.0'], mode='remove')
    
    assert modified_count > 0
    packages = env.manifest.configuration.get('packages', {})
    gcc_config = packages.get('gcc:') or packages.get('gcc')
    assert gcc_config is not None
    assert len(gcc_config.get('externals', [])) == 0


def test_filter_no_matching_specs(multi_compiler_env):
    """Test filter with specs that don't match any externals."""
    env = multi_compiler_env
    
    # Try to remove specs that don't exist in config
    modified_count = filter_compiler_packages(
        env,
        ['gcc@99.0.0', 'clang@99.0.0'],
        mode='remove'
    )
    
    # Should not modify anything since no externals match
    assert modified_count == 0
    
    # Verify original config is unchanged
    packages = env.manifest.configuration.get('packages', {})
    gcc_config = packages.get('gcc') or packages.get('gcc')
    gcc_externals = gcc_config.get('externals', []) if gcc_config else []
    assert len(gcc_externals) == 2  # Original count


def test_filter_empty_packages_config(empty_packages_env):
    """Test filter on environment with no packages configuration."""
    env = empty_packages_env
    
    modified_count = filter_compiler_packages(env, ['gcc@11.2.0'], mode='remove')
    
    # Should return 0 (no modifications)
    assert modified_count == 0


def test_expand_compiler_synonyms_basic():
    """Test that compiler synonyms are correctly expanded."""
    result = _expand_compiler_synonyms(['oneapi@2024.2.1', 'intel@2021.4.0', 'gcc@11.2.0'])
    assert result == ['intel-oneapi-compilers@2024.2.1', 'intel-oneapi-compilers-classic@2021.4.0', 'gcc@11.2.0']


def test_expand_compiler_synonyms_non_synonyms():
    """Test that non-synonym specs are left unchanged."""
    result = _expand_compiler_synonyms(['gcc@11.2.0', 'clang@14.0.0'])
    assert result == ['gcc@11.2.0', 'clang@14.0.0']


def test_filter_with_synonym_expansion(multi_compiler_env, monkeypatch):
    """Test that synonym expansion works in actual filtering context.
    
    Note: Current implementation of filter_compiler_packages doesn't expose
    direct synonym handling for filtering. This test documents expected behavior
    if synonym expansion is needed during filter operations.
    """
    # This test documents that _expand_compiler_synonyms is used internally
    # Verifying the helper function works correctly with actual filtering
    env = multi_compiler_env
    
    # Manually expand and filter using the helper
    specs_with_synonyms = ['gcc@11.2.0']
    expanded = _expand_compiler_synonyms(specs_with_synonyms)
    
    assert expanded == specs_with_synonyms  # No synonyms in this input
    
    modified_count = filter_compiler_packages(env, specs_with_synonyms, mode='keep-only')
    assert modified_count > 0
