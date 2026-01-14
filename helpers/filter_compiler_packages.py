"""Filter compiler packages in Spack configuration.

This module provides functionality to filter compiler packages in the packages
configuration based on user-specified compiler specs.
"""

import spack.spec
import spack.config
try:
    from spack.llnl.util import tty
except ImportError:
    from llnl.util import tty

def _expand_compiler_synonyms(compiler_specs):
    """Expand compiler name synonyms to their full package names.
    
    Supports:
    - 'oneapi' -> 'intel-oneapi-compilers'
    - 'intel' -> 'intel-oneapi-compilers-classic'
    
    Args:
        compiler_specs: List of compiler spec strings
        
    Returns:
        List of compiler spec strings with synonyms expanded
    """
    synonyms = {
        'oneapi': 'intel-oneapi-compilers',
        'intel': 'intel-oneapi-compilers-classic'
    }
    
    expanded_specs = []
    for spec_str in compiler_specs:
        # Parse to extract compiler name
        spec = spack.spec.Spec(spec_str)
        base_name = spec.name
        
        # Replace if it's a synonym
        if base_name in synonyms:
            # Reconstruct spec string with full name
            full_name = synonyms[base_name]
            expanded_str = spec_str.replace(base_name, full_name, 1)
            expanded_specs.append(expanded_str)
        else:
            expanded_specs.append(spec_str)
    
    return expanded_specs


def filter_compiler_packages(env, compiler_specs, mode='remove'):
    """Filter compiler packages in packages configuration using :: syntax.
    
    This function filters compiler packages by creating environment-level package
    configuration entries using the '::' syntax to override upstream configs.
    
    Supports compiler name synonyms:
    - 'oneapi' -> 'intel-oneapi-compilers'
    - 'intel' -> 'intel-oneapi-compilers-classic'
    
    Args:
        compiler_specs: List of compiler spec strings (e.g., ['gcc@11.2.0', 'clang@14'])
        mode: Either 'remove' or 'keep-only'
            - 'remove': Exclude specified compiler specs from environment
            - 'keep-only': Include only specified compiler specs in environment
            
    Returns:
        tuple: modified_count - number of compilers modified
    """
    # Expand synonyms
    expanded_specs = _expand_compiler_synonyms(compiler_specs)
    
    # Parse compiler specs
    parsed_specs = [spack.spec.Spec(spec_str) for spec_str in expanded_specs]
    
    # Common compiler package names
    compiler_packages = {
        'gcc', 'llvm', 'clang', 'intel-oneapi-compilers', 
        'intel-oneapi-compilers-classic', 'aocc', 'nvhpc', 'apple-clang'
    }
    
    tty.debug(f"filter_compiler_packages: mode={mode}, parsed_specs={[str(s) for s in parsed_specs]}")
    
    # Get all packages configuration (from all scopes to find externals)
    all_packages = spack.config.get('packages')
    
    if not all_packages:
        return 0
    
    # Track compilers found and what to do with them
    compiler_externals_found = {}  # pkg_name -> list of (spec, external_dict) tuples
    
    # Scan all package configs for compiler externals
    for pkg_name, pkg_config in all_packages.items():
        # Only process known compiler packages
        if pkg_name not in compiler_packages:
            continue

        # Skip if config is not a dict or has no 'externals' section
        if not isinstance(pkg_config, dict) or 'externals' not in pkg_config:
            continue

        # Extract compiler specs from the externals list
        externals = pkg_config['externals']
        if not isinstance(externals, list):
            continue
        
        # Collect all specs and their full external dicts for this compiler package
        pkg_externals = []
        for external in externals:
            if not isinstance(external, dict) or 'spec' not in external:
                continue
            
            spec_str = external['spec']
            try:
                spec = spack.spec.Spec(spec_str)
                # Store both the spec and the entire external dict
                pkg_externals.append((spec, external))
            except Exception:
                # Skip invalid specs
                continue
        
        if pkg_externals:
            compiler_externals_found[pkg_name] = pkg_externals
    
    tty.debug(f"compiler_externals_found: {compiler_externals_found}")
    
    # Build new package configuration with :: syntax for environment
    env_packages_config = {}
    modified_count = 0
    
    for pkg_name, available_externals in compiler_externals_found.items():
        # Determine which externals to keep based on mode
        kept_externals = []
        
        tty.debug(f"Processing {pkg_name}, found {len(available_externals)} externals: {[str(s) for s, _ in available_externals]}")
        
        for spec, external_dict in available_externals:
            should_keep = False
            
            if mode == 'remove':
                # Keep spec if it doesn't match any parsed spec
                should_keep = not any(spec.satisfies(ps) for ps in parsed_specs)
            elif mode == 'keep-only':
                # Keep spec if it matches any parsed spec
                should_keep = any(spec.satisfies(ps) for ps in parsed_specs)
            
            tty.debug(f"Spec {spec} - should_keep={should_keep} (mode={mode})")
            
            if should_keep:
                # Keep the entire external dict (includes spec, prefix, modules, etc.)
                kept_externals.append(external_dict)
        
        # Create environment configuration entry using :: syntax
        if len(kept_externals) != len(available_externals):
            # Something changed for this compiler
            modified_count += 1
            
            # Start with existing config for this package (if any)
            # This preserves require, compiler, variants, etc.
            pkg_config = dict(all_packages.get(pkg_name, {}))
            
            # Zero out the externals section
            pkg_config['externals'] = []
            
            # Add filtered externals
            if kept_externals:
                pkg_config['externals'] = kept_externals
            
            # Write with :: syntax to override in environment
            env_packages_config[f"{pkg_name}:"] = pkg_config
    
    # Write to environment configuration (spack.yaml)
    if modified_count > 0:      
        # Get existing packages config ONLY from the environment's spack.yaml
        env_packages = env.manifest.configuration.get('packages', {})
        
        # Remove any existing entries for compilers we're modifying
        # (both with and without :: suffix to avoid duplicates)
        for key in list(env_packages_config.keys()):
            # Extract compiler name (remove trailing ':')
            compiler_name = key.rstrip(':')
            # Remove both 'gcc' and 'gcc:' / 'gcc::' if they exist
            env_packages.pop(compiler_name, None)
            env_packages.pop(f"{compiler_name}:", None)
        
        # Merge with new compiler configurations
        env_packages.update(env_packages_config)
        
        # Update the environment's packages config
        env.manifest.configuration['packages'] = env_packages
        env.manifest.changed = True
        env.write()
    
    return modified_count
