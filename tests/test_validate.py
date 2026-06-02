"""Unit tests for validate command and helper functions."""
import copy
import pytest

import spack.config
import spack.environment as ev
import spack.spec
import spack.extensions

# Load the helpers extension
spack.extensions.load_extension("helpers")
from spack.extensions.helpers.check_duplicates import check_duplicate_packages
from spack.extensions.helpers.check_compiler_usage import check_compiler_usage
from spack.extensions.helpers.check_allowed_compilers import check_allowed_compilers
from spack.extensions.helpers.check_approved_packages import check_approved_packages
from spack.extensions.helpers.check_buildable import check_buildable_configuration


@pytest.fixture(scope="session")
def _validation_env_base(tmp_path_factory):
    """Create a comprehensive test environment for validation checks (cached).
    
    This environment contains:
    - Duplicate packages (zlib with two different variants)
    - Multiple compilers (gcc and intel-oneapi-compilers)
    - Mixed compiler usage across different packages
    - Both approved and unapproved packages
    
    This is a session-scoped fixture that is created once and reused.
    """
    # Create environment directory and manifest file
    tmp_path = tmp_path_factory.mktemp("validation_test_env")
    env_path = tmp_path / "validation_test_env"
    env_path.mkdir(exist_ok=False)
    env = ev.create_in_dir(env_path, with_view=False)
    
    # Add specs that will create various validation scenarios
    specs_to_add = [
        # Duplicates: zlib with two different variants
        "zlib+shared ^gmake@4.3",
        "zlib~shared ^gmake@4.2",
        
        # Different packages using gcc
        "libelf%gcc",
        "libdwarf%gcc",
        
        # Packages that will pull in gmake as a build dependency with different versions
        # (gmake is a build dependency for many packages)
        "autoconf",
        "automake",
        
        # Additional packages for approved/unapproved testing
        "py-numpy",
    ]
    
    for spec_str in specs_to_add:
        spec = spack.spec.Spec(spec_str)
        env.add(spec)
    
    env.write()
    
    # Concretize the environment once
    with spack.config.override("concretizer:unify", "when_possible"):
        env.concretize()
    env.write()
    
    return env


@pytest.fixture
def validation_test_env(_validation_env_base):
    """Provide a deep copy of the validation test environment for each test.
    
    This allows tests to reuse the same concretized environment without
    having to concretize it multiple times, while still providing independent
    copies to avoid any potential state pollution between tests.
    """
    return copy.deepcopy(_validation_env_base)


def test_check_duplicate_packages_finds_duplicates(validation_test_env):
    """Test that check_duplicate_packages identifies duplicate installations."""
    env = validation_test_env
    
    # Check for duplicates
    duplicates = check_duplicate_packages(env)
    
    # Should find zlib as a duplicate (we added zlib+shared and zlib~shared)
    assert "zlib" in duplicates, "Should detect zlib duplicates"
    assert len(duplicates["zlib"]) == 2, "Should find exactly 2 zlib specs"
    
    # Verify the duplicates are different
    hashes = [spec.dag_hash() for spec in duplicates["zlib"]]
    assert len(set(hashes)) == 2, "Duplicate specs should have different hashes"


def test_check_duplicate_packages_with_ignore(validation_test_env):
    """Test that check_duplicate_packages respects ignore_packages parameter."""
    env = validation_test_env
    
    # Check for duplicates, ignoring zlib
    duplicates = check_duplicate_packages(env, ignore_packages=["zlib"])
    
    # Should not find zlib as a duplicate since we're ignoring it
    assert "zlib" not in duplicates, "Should not detect ignored package as duplicate"


def test_check_duplicate_packages_no_false_positives(validation_test_env):
    """Test that check_duplicate_packages doesn't flag non-duplicates."""
    env = validation_test_env
    
    duplicates = check_duplicate_packages(env)
    
    # Packages added only once should never appear as duplicates.
    for pkg in ["libelf", "libdwarf"]:
        assert pkg not in duplicates, f"{pkg} should not be flagged as a duplicate"


def test_check_duplicate_packages_includes_dependencies(validation_test_env):
    """Test that check_duplicate_packages detects duplicates in transitive dependencies."""
    env = validation_test_env
    
    # Check for duplicates across the entire dependency graph
    duplicates = check_duplicate_packages(env)
    
    # Verify that gmake duplicates are detected
    # gmake is not a root spec but appears as a dependency with different versions
    assert "gmake" in duplicates, "Should detect gmake dependency duplicates"


def test_check_duplicate_packages_ignore_build_deps(validation_test_env):
    """Test that check_duplicate_packages can ignore build-only dependencies."""
    env = validation_test_env
    
    # Get duplicates without ignoring build deps
    duplicates_with_build = check_duplicate_packages(env, ignore_build_deps=False)
    
    # Get duplicates ignoring build deps
    duplicates_without_build = check_duplicate_packages(env, ignore_build_deps=True)
    
    # gmake should appear as a duplicate when not ignoring build deps
    # (autoconf and automake both pull in gmake as a build dependency)
    assert "gmake" in duplicates_with_build, \
        "gmake should be detected as duplicate when not ignoring build deps"
    
    # gmake should NOT appear as a duplicate when ignoring build deps
    # (since it's only used as a build dependency)
    assert "gmake" not in duplicates_without_build, \
        "gmake should not be detected as duplicate when ignoring build deps"


def test_check_compiler_usage_detects_violations(validation_test_env):
    """Test that check_compiler_usage detects packages using restricted compilers."""
    env = validation_test_env
    
    # Allow only autoconf to use gcc
    allowed_packages = ["autoconf"]
    illegal_specs = check_compiler_usage(env, "gcc", allowed_packages)
    
    # Should find specs using gcc that are not autoconf
    # (libelf, libdwarf, and potentially dependencies)
    assert len(illegal_specs) > 0, "Should detect packages using gcc that aren't allowed"
    
    # Verify that autoconf is not in the illegal list
    illegal_names = [spec.name for spec in illegal_specs]
    assert "autoconf" not in illegal_names, "autoconf should not be in illegal list"


def test_check_compiler_usage_no_violations(validation_test_env):
    """Test that check_compiler_usage returns empty when all packages are allowed."""
    env = validation_test_env
    
    # Get all package names in the environment
    all_packages = set()
    for _, concrete_spec in env.concretized_specs():
        all_packages.add(concrete_spec.name)
    
    # Allow all packages to use gcc
    illegal_specs = check_compiler_usage(env, "gcc", list(all_packages))
    
    # Should find no violations
    assert len(illegal_specs) == 0, "Should find no violations when all packages are allowed"


def test_check_compiler_usage_nonexistent_compiler(validation_test_env):
    """Test check_compiler_usage with a compiler that doesn't exist in env."""
    env = validation_test_env
    
    # Check for a compiler that's not used (e.g., 'clang')
    illegal_specs = check_compiler_usage(env, "nonexistent-compiler", [])
    
    # Should find no violations since no specs use this compiler
    assert len(illegal_specs) == 0, "Should find no violations for unused compiler"


def test_check_allowed_compilers_detects_violations(validation_test_env):
    """Test that check_allowed_compilers detects specs using disallowed compilers."""
    env = validation_test_env
    
    # Allow only a specific gcc version (that likely doesn't match)
    allowed_compilers = ["gcc@999.0.0"]
    illegal_specs = check_allowed_compilers(env, allowed_compilers)
    
    # Should find specs using compilers other than gcc@999.0.0
    assert len(illegal_specs) > 0, "Should detect specs using disallowed compilers"



def test_check_approved_packages_detects_violations(validation_test_env):
    """Test that check_approved_packages detects unauthorized packages."""
    env = validation_test_env
    
    # Allow only a subset of packages
    approved_packages = ["zlib", "autoconf"]
    unauthorized_specs = check_approved_packages(env, approved_packages)
    
    # Should find unauthorized packages (like libelf, libdwarf, gmake, etc.)
    assert len(unauthorized_specs) > 0, "Should detect unauthorized packages"
    
    # Verify that approved packages are not in the unauthorized list
    unauthorized_names = [spec.name for spec in unauthorized_specs]
    assert "zlib" not in unauthorized_names, "zlib should not be unauthorized"
    assert "autoconf" not in unauthorized_names, "autoconf should not be unauthorized"
    
    # Verify that dependencies are being checked (should find gmake as unauthorized)
    assert "gmake" in unauthorized_names, "gmake (a dependency) should be detected as unauthorized"


def test_check_approved_packages_all_approved(validation_test_env):
    """Test that check_approved_packages returns empty when all are approved."""
    env = validation_test_env
    
    # Get all package names in the environment (including dependencies)
    all_packages = set()
    for concrete_spec in env.all_specs():
        all_packages.add(concrete_spec.name)
    
    # Approve all packages
    unauthorized_specs = check_approved_packages(env, list(all_packages))
    
    # Should find no unauthorized packages
    assert len(unauthorized_specs) == 0, "Should find no violations when all packages are approved"


def test_check_approved_packages_none_approved(validation_test_env):
    """Test that check_approved_packages detects all packages when none approved."""
    env = validation_test_env
    
    # Approve no packages (empty list)
    unauthorized_specs = check_approved_packages(env, [])
    
    # Should find all packages as unauthorized
    assert len(unauthorized_specs) > 0, "Should detect all packages as unauthorized"
    
    # Count should match total number of non-external specs (including dependencies)
    total_non_external_specs = len([s for s in env.all_specs() if not s.external])
    assert len(unauthorized_specs) == total_non_external_specs, "All non-external specs (including dependencies) should be unauthorized"


def test_check_buildable_configuration_no_violations(validation_test_env):
    """Test check_buildable when all unbuildable packages use externals."""
    env = validation_test_env
    
    # Initially no buildable:false settings, so no violations
    violations = check_buildable_configuration(env)
    assert len(violations) == 0, "Should find no violations without buildable:false settings"


def test_check_buildable_configuration_with_violation(validation_test_env):
    """Test check_buildable detects packages marked unbuildable being built."""
    env = validation_test_env
    
    # Get a package name that's in the environment and mark it unbuildable
    pkg_name = None
    for _, concrete_spec in env.concretized_specs():
        # Find a non-external package
        if not concrete_spec.external:
            pkg_name = concrete_spec.name
            break
    
    assert pkg_name is not None, "Should find at least one non-external package"
    
    # Mark the package as unbuildable
    if 'packages' not in env.manifest.configuration:
        env.manifest.configuration['packages'] = {}
    env.manifest.configuration['packages'][pkg_name] = {'buildable': False}
    
    # Check for violations
    violations = check_buildable_configuration(env)
    
    # Should find at least the package we marked as unbuildable
    assert len(violations) > 0, "Should detect unbuildable package being built"
    
    # Verify the package we marked is in the violations
    violation_names = [spec.name for spec in violations]
    assert pkg_name in violation_names, f"{pkg_name} should be in violations"

