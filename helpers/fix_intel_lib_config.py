"""Fix Intel OneAPI library configuration for external specs.

This module provides functionality to add LD_LIBRARY_PATH configuration
to intel-oneapi-compilers-classic external specs in Spack environments.
"""

import spack.config
from spack.llnl.util import tty


def fix_intel_lib_config_for_env(env):
    """Add LD_LIBRARY_PATH configuration to intel-oneapi-compilers-classic externals.
    
    For each external spec in packages:intel-oneapi-compilers-classic:externals,
    this function adds:
        extra_attributes:
          environment:
            prepend_path:
              LD_LIBRARY_PATH: <prefix>/linux/compiler/lib/intel64_lin
    
    This function only modifies the environment's spack.yaml file. If an external
    is found in another configuration file, a new overriding entry is created
    in spack.yaml using the :: syntax.
    
    Args:
        env: Active Spack environment
        
    Returns:
        int: Number of external specs modified
    """
    PACKAGE_NAME = 'intel-oneapi-compilers-classic'
    LIB_PATH_SUFFIX = 'compiler/lib/intel64_lin'
    
    # Get all packages configuration (from all scopes to find externals)
    all_packages = spack.config.get('packages')
    
    if not all_packages:
        tty.debug("No packages configuration found")
        return 0
    
    # Check if the intel-oneapi-compilers-classic package exists
    if PACKAGE_NAME not in all_packages:
        tty.debug(f"Package {PACKAGE_NAME} not found in configuration")
        return 0
    
    pkg_config = all_packages[PACKAGE_NAME]
    
    # Skip if config is not a dict or has no 'externals' section
    if not isinstance(pkg_config, dict) or 'externals' not in pkg_config:
        tty.debug(f"No externals found for {PACKAGE_NAME}")
        return 0
    
    externals = pkg_config['externals']
    if not isinstance(externals, list):
        tty.debug(f"Externals is not a list for {PACKAGE_NAME}")
        return 0
    
    # Process each external and add the LD_LIBRARY_PATH configuration
    modified_externals = []
    modified_count = 0
    
    for external in externals:
        if not isinstance(external, dict) or 'spec' not in external or 'prefix' not in external:
            # Keep unmodified if it doesn't have the required fields
            modified_externals.append(external)
            continue
        
        # Create a copy of the external dict to modify
        modified_external = dict(external)
        
        # Construct the library path from the prefix
        prefix = external['prefix']
        lib_path = f"{prefix}/{LIB_PATH_SUFFIX}"
        
        # Check if extra_attributes already exists
        if 'extra_attributes' not in modified_external:
            modified_external['extra_attributes'] = {}
        
        extra_attrs = modified_external['extra_attributes']
        
        # Check if environment already exists
        if 'environment' not in extra_attrs:
            extra_attrs['environment'] = {}
        
        environment = extra_attrs['environment']
        
        # Check if prepend_path already exists
        if 'prepend_path' not in environment:
            environment['prepend_path'] = {}
        
        prepend_path = environment['prepend_path']
        
        # Check if LD_LIBRARY_PATH already exists
        if 'LD_LIBRARY_PATH' not in prepend_path:
            # Add the LD_LIBRARY_PATH
            prepend_path['LD_LIBRARY_PATH'] = lib_path
            modified_count += 1
            tty.debug(f"Added LD_LIBRARY_PATH={lib_path} for spec {external['spec']}")
        else:
            # Check if the path is already correct
            existing_path = prepend_path['LD_LIBRARY_PATH']
            if existing_path != lib_path:
                # Update the path
                prepend_path['LD_LIBRARY_PATH'] = lib_path
                modified_count += 1
                tty.debug(f"Updated LD_LIBRARY_PATH from {existing_path} to {lib_path} for spec {external['spec']}")
            else:
                tty.debug(f"LD_LIBRARY_PATH already correct for spec {external['spec']}")
        
        modified_externals.append(modified_external)
    
    # Write to environment configuration (spack.yaml) if anything was modified
    if modified_count > 0:
        # Get existing packages config ONLY from the environment's spack.yaml
        env_packages = env.manifest.configuration.get('packages', {})
        
        # Start with existing config for this package (if any)
        # This preserves require, compiler, variants, etc.
        new_pkg_config = dict(all_packages.get(PACKAGE_NAME, {}))
        
        # Replace externals section with modified one
        new_pkg_config['externals'] = modified_externals
        
        # Remove any existing entries for this package
        # (both with and without :: suffix to avoid duplicates)
        env_packages.pop(PACKAGE_NAME, None)
        env_packages.pop(f"{PACKAGE_NAME}:", None)
        
        # Write with :: syntax to override in environment
        env_packages[f"{PACKAGE_NAME}:"] = new_pkg_config
        
        # Update the environment's packages config
        env.manifest.configuration['packages'] = env_packages
        env.manifest.changed = True
    
    return modified_count
