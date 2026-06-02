"""Unit tests for allow-only-approved-pkgs command."""
import pytest

import spack.environment as ev
import spack.spec
import spack.extensions
from spack.error import SpackError

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.cmd import allow_only_approved_pkgs as cmd
from spack.extensions.helpers.allow_only_approved_packages import (
    allow_only_approved_packages,
    read_approved_packages_from_file,
)


@pytest.fixture
def test_env(tmp_path):
    """Create a test environment for allow-only-approved-pkgs command."""
    env_path = tmp_path / "test_env"
    env_path.mkdir(exist_ok=True)
    
    env = ev.create_in_dir(env_path, with_view=False)
    env.write()
    
    return env


@pytest.fixture
def mock_args():
    """Factory for creating mock Args objects."""
    class Args:
        def __init__(self, packages=None, pkgs_from_file=None):
            self.packages = packages
            self.pkgs_from_file = pkgs_from_file
    return Args


@pytest.fixture
def preconfigured_env(test_env):
    """Environment with pre-existing package configuration."""
    test_env.manifest.configuration['packages'] = {
        'gcc': {
            'variants': '+binutils',
            'externals': [{'spec': 'gcc@11.2.0', 'prefix': '/usr'}]
        },
        'cmake': {
            'buildable': False
        },
        'openmpi': {
            'version': ['4.1.0'],
        }
    }
    test_env.write()
    return test_env


@pytest.mark.parametrize('packages,expected_buildable_pkgs', [
    (['gcc'], ['gcc']),
    (['gcc', 'cmake'], ['gcc', 'cmake']),
    (['gcc', 'openmpi', 'hdf5'], ['gcc', 'openmpi', 'hdf5']),
])
def test_allow_only_approved_pkgs_basic(test_env, mock_args, packages, expected_buildable_pkgs):
    """Test basic functionality with various package counts."""
    args = mock_args(packages=packages)
    
    with test_env:
        result = cmd.allow_only_approved_pkgs(None, args)
    
    assert result == 0
    
    env_packages = test_env.manifest.configuration.get('packages', {})
    
    # Verify approved packages are buildable
    for pkg in expected_buildable_pkgs:
        assert env_packages[pkg]['buildable'] is True
    
    # Verify 'all' is non-buildable
    assert env_packages['all']['buildable'] is False


def test_allow_only_approved_pkgs_skips_already_false(test_env, mock_args):
    """Test that packages marked buildable:false are not changed to true."""
    # Pre-configure cmake as buildable:false
    test_env.manifest.configuration['packages'] = {
        'cmake': {'buildable': False}
    }
    test_env.write()
    
    args = mock_args(packages=['gcc', 'cmake', 'openmpi'])
    
    with test_env:
        result = cmd.allow_only_approved_pkgs(None, args)
    
    assert result == 0
    
    env_packages = test_env.manifest.configuration.get('packages', {})
    
    # cmake should remain False (unchanged)
    assert env_packages['cmake']['buildable'] is False
    
    # Other packages should be True
    assert env_packages['gcc']['buildable'] is True
    assert env_packages['openmpi']['buildable'] is True
    
    # 'all' should be False
    assert env_packages['all']['buildable'] is False


def test_allow_only_approved_pkgs_preserves_other_config(preconfigured_env, mock_args):
    """Test that existing package configuration (variants, externals, etc.) is preserved."""
    args = mock_args(packages=['gcc', 'openmpi'])
    
    with preconfigured_env:
        result = cmd.allow_only_approved_pkgs(None, args)
    
    assert result == 0
    
    env_packages = preconfigured_env.manifest.configuration.get('packages', {})
    
    # Check gcc's other config is preserved
    assert env_packages['gcc']['variants'] == '+binutils'
    assert env_packages['gcc']['externals'][0]['spec'] == 'gcc@11.2.0'
    assert env_packages['gcc']['buildable'] is True
    
    # Check openmpi's version is preserved (not buildable:false, so gets set to True)
    assert env_packages['openmpi']['version'] == ['4.1.0']
    assert env_packages['openmpi']['buildable'] is True
    
    # cmake (not approved) should remain buildable:false
    assert env_packages['cmake']['buildable'] is False


def test_read_approved_packages_from_file(tmp_path):
    """Test reading package list from file with comments and empty lines."""
    pkg_file = tmp_path / "packages.txt"
    pkg_file.write_text("gcc\n# comment line\nopenmpi\n\nhdf5\n\n# another comment\n")
    
    result = read_approved_packages_from_file(str(pkg_file))
    
    assert result == ['gcc', 'openmpi', 'hdf5']


def test_read_approved_packages_from_file_empty(tmp_path):
    """Test reading file with only comments and empty lines returns empty list."""
    pkg_file = tmp_path / "packages.txt"
    pkg_file.write_text("# comment\n\n# another comment\n")
    
    result = read_approved_packages_from_file(str(pkg_file))
    
    assert result == []


def test_read_approved_packages_from_file_not_found():
    """Test reading from non-existent file raises SpackError."""
    with pytest.raises(SpackError, match="Could not read package list"):
        read_approved_packages_from_file("/nonexistent/path/packages.txt")


def test_allow_only_approved_pkgs_from_file_via_command(test_env, mock_args, tmp_path):
    """Test command-level functionality with --pkgs-from-file option."""
    pkg_file = tmp_path / "packages.txt"
    pkg_file.write_text("gcc\nopenmpi\nhdf5\n")
    
    args = mock_args(packages=None, pkgs_from_file=str(pkg_file))
    
    with test_env:
        result = cmd.allow_only_approved_pkgs(None, args)
    
    assert result == 0
    
    env_packages = test_env.manifest.configuration.get('packages', {})
    
    # Check packages from file are buildable
    for pkg in ['gcc', 'openmpi', 'hdf5']:
        assert env_packages[pkg]['buildable'] is True
    
    # 'all' should be False
    assert env_packages['all']['buildable'] is False


def test_allow_only_approved_packages_empty_list_raises(test_env):
    """Test that calling with empty package list raises SpackError."""
    with pytest.raises(SpackError, match="No approved packages specified"):
        allow_only_approved_packages(test_env, [])


def test_allow_only_approved_packages_returns_configured_count(preconfigured_env):
    """Test that configured_count reflects only newly configured packages."""
    # cmake is already buildable:false, so it should not count
    result = allow_only_approved_packages(preconfigured_env, ['gcc', 'cmake', 'openmpi'])
    
    # Only gcc and openmpi should be counted (cmake was already buildable:false)
    assert result == 2

