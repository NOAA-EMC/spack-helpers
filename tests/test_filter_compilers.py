"""Unit tests for filter-compilers command and filter_compiler_packages functionality."""
import pytest

import spack.environment as ev
import spack.config
import spack.extensions

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.filter_compiler_packages import filter_compiler_packages, _expand_compiler_synonyms


@pytest.fixture
def filter_compilers_env(tmp_path, monkeypatch):
    """Create a test environment with compiler packages configuration.
    
    This environment includes:
    - gcc compiler with two externals
    - clang compiler with two externals
    - Package-level configuration (variants, buildable) to ensure
      non-externals config is preserved during filtering
    """
    env_path = tmp_path / "filter_test_env"
    env_path.mkdir(exist_ok=True)
    
    env = ev.create_in_dir(env_path, with_view=False)
    
    # Create packages configuration with compiler externals and non-externals config
    packages_config = {
        'gcc': {
            'externals': [
                {'spec': 'gcc@11.2.0', 'prefix': '/usr/bin/gcc-11'},
                {'spec': 'gcc@10.3.0', 'prefix': '/usr/bin/gcc-10'},
            ],
            # Non-externals config that should be preserved
            'variants': '+binutils',
        },
        'clang': {
            'externals': [
                {'spec': 'clang@14.0.0', 'prefix': '/usr/bin/clang-14'},
                {'spec': 'clang@13.0.0', 'prefix': '/usr/bin/clang-13'},
            ],
            # Non-externals config that should be preserved
            'buildable': False,
        },
    }
    
    env.manifest.configuration['packages'] = packages_config
    env.write()
    
    # Mock spack.config.get to return our test packages config
    original_config_get = spack.config.get
    
    def mock_config_get(key, default=None, scope=None):
        if key == 'packages':
            return env.manifest.configuration.get('packages', {})
        return original_config_get(key, default, scope)
    
    monkeypatch.setattr(spack.config, 'get', mock_config_get)
    
    return env


def test_filter_compilers_keep_only(filter_compilers_env):
    """Test filter-compilers --keep-only mode.
    
    Keep only gcc@11.2.0, verifying that the clang externals and the other gcc 
    external are properly removed and non-externals configuration is retained.
    """
    env = filter_compilers_env
    
    # Keep only gcc@11.2.0
    modified_count = filter_compiler_packages(
        env,
        ['gcc@11.2.0'],
        mode='keep-only'
    )
    
    assert modified_count > 0, "Should have modified compiler configuration"
    
    packages = env.manifest.configuration.get('packages', {})
    
    # gcc should have only gcc@11.2.0
    gcc_config = packages.get('gcc:') or packages.get('gcc')
    assert gcc_config is not None, "gcc should be in configuration"
    gcc_externals = gcc_config.get('externals', [])
    assert len(gcc_externals) == 1, f"gcc should have exactly 1 external, got {len(gcc_externals)}"
    assert gcc_externals[0]['spec'] == 'gcc@11.2.0'
    assert gcc_externals[0]['prefix'] == '/usr/bin/gcc-11'
    
    # gcc non-externals configuration should be preserved
    assert gcc_config.get('variants') == '+binutils', "gcc variants should be preserved"
    
    # clang should have no externals (all removed)
    clang_config = packages.get('clang:') or packages.get('clang')
    assert clang_config is not None, "clang should be in configuration"
    clang_externals = clang_config.get('externals', [])
    assert len(clang_externals) == 0, f"clang should have 0 externals, got {len(clang_externals)}"
    
    # clang non-externals configuration should be preserved
    assert clang_config.get('buildable') is False, "clang buildable should be preserved"


def test_filter_compilers_remove(filter_compilers_env):
    """Test filter-compilers --remove mode.
    
    Remove gcc@10.3.0 and both clang versions, ensuring that only gcc@11.2.0 
    remains and that non-externals configuration is suitably retained.
    """
    env = filter_compilers_env
    
    # Remove gcc@10.3.0, clang@14.0.0, and clang@13.0.0
    modified_count = filter_compiler_packages(
        env,
        ['gcc@10.3.0', 'clang@14.0.0', 'clang@13.0.0'],
        mode='remove'
    )
    
    assert modified_count > 0, "Should have modified compiler configuration"
    
    packages = env.manifest.configuration.get('packages', {})
    
    # gcc should have only gcc@11.2.0
    gcc_config = packages.get('gcc:') or packages.get('gcc')
    assert gcc_config is not None, "gcc should be in configuration"
    gcc_externals = gcc_config.get('externals', [])
    assert len(gcc_externals) == 1, f"gcc should have exactly 1 external, got {len(gcc_externals)}"
    assert gcc_externals[0]['spec'] == 'gcc@11.2.0'
    assert gcc_externals[0]['prefix'] == '/usr/bin/gcc-11'
    
    # gcc non-externals configuration should be preserved
    assert gcc_config.get('variants') == '+binutils', "gcc variants should be preserved"
    
    # clang should have no externals (all removed)
    clang_config = packages.get('clang:') or packages.get('clang')
    assert clang_config is not None, "clang should be in configuration"
    clang_externals = clang_config.get('externals', [])
    assert len(clang_externals) == 0, f"clang should have 0 externals, got {len(clang_externals)}"
    
    # clang non-externals configuration should be preserved
    assert clang_config.get('buildable') is False, "clang buildable should be preserved"


def test_expand_compiler_synonyms():
    """Test that compiler synonyms are correctly expanded."""

    # Test both synonyms together
    result = _expand_compiler_synonyms(['oneapi@2024.2.1', 'intel@2021.4.0', 'gcc@11.2.0'])
    assert result == ['intel-oneapi-compilers@2024.2.1', 'intel-oneapi-compilers-classic@2021.4.0', 'gcc@11.2.0']
    
    # Test non-synonym (should be unchanged)
    result = _expand_compiler_synonyms(['gcc@11.2.0', 'clang@14.0.0'])
    assert result == ['gcc@11.2.0', 'clang@14.0.0']
