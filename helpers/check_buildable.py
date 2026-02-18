"""Check that concretized specs respect buildable configuration.

This module provides functionality to validate that packages marked as
buildable:false in the environment configuration are not being built.
"""

import spack.config
try:
    from spack.llnl.util import tty
except ImportError:
    from llnl.util import tty

def check_buildable_configuration(env):
    """Check for specs that are concretized despite being marked unbuildable.
    
    Iterates over all concretized specs in the environment and identifies
    specs whose packages are marked as buildable:false in the configuration
    but are being built anyway (not installed from an external).
    
    Args:
        env: A Spack Environment object to check
        
    Returns:
        List[Spec]: List of Spec objects that violate buildable configuration.
    """
    violations = []
    
    # Get packages configuration
    packages_config = env.manifest.configuration.get('packages', {})
    
    # Iterate over all concretized specs in the environment
    for user_spec, concrete_spec in env.concretized_specs():
        pkg_name = concrete_spec.name
        
        # Check if this package has buildable configuration
        pkg_config = packages_config.get(pkg_name, {})
        buildable = pkg_config.get('buildable', None)
        
        # If buildable is explicitly False, check if spec is external
        if buildable is False:
            # A spec is external if it has the external attribute set
            if not concrete_spec.external:
                violations.append(concrete_spec)
                tty.debug(f"Violation: {pkg_name} is buildable:false but being built")
            else:
                tty.debug(f"OK: {pkg_name} is buildable:false and using external")
        else:
            tty.debug(f"OK: {pkg_name} buildable setting allows building")
    
    return violations
