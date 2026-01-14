"""Check that only specified compilers appear in a Spack environment.

This module provides functionality to validate that only whitelisted compilers
are used in a concretized Spack environment.

Supports both old Spack (compilers.yaml) and new Spack (compilers-as-nodes).
"""

from typing import List

import spack.spec
from spack.extensions.helpers.compiler_compat import uses_compilers_as_nodes


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


def check_allowed_compilers(env, allowed_compilers):
    """Check for specs using compilers not in the allowed list.
    
    Iterates over all concretized specs in the environment and identifies
    specs that use compilers (c, c++, fortran) not in the allowed list.
    
    Supports both:
    - New Spack (compilers-as-nodes): Checks spec["c"], spec["cxx"], spec["fortran"]
    - Old Spack (compilers.yaml): Checks spec.compiler attribute
    
    Supports compiler name synonyms:
    - 'oneapi' -> 'intel-oneapi-compilers'
    - 'intel' -> 'intel-oneapi-compilers-classic'
    
    Args:
        env: A Spack Environment object to check
        allowed_compilers: List of allowed compiler specs (e.g., 'gcc@11.2.0', 'clang@14.0.0')
        
    Returns:
        List[Spec]: List of Spec objects that use disallowed compilers.
    """
    import spack.spec
    
    illegal_specs = []
    
    # Expand synonyms
    expanded_compilers = _expand_compiler_synonyms(allowed_compilers)
    
    # Parse allowed compiler specs
    allowed_compiler_specs = [spack.spec.Spec(spec_str) for spec_str in expanded_compilers]
    
    # Iterate over all concretized specs in the environment
    for user_spec, concrete_spec in env.concretized_specs():
        is_allowed = True
        
        # Detect which compiler model is being used
        if uses_compilers_as_nodes(concrete_spec):
            # New approach: check language-specific compilers
            for lang in ("c", "cxx", "fortran"):
                if lang in concrete_spec:
                    compiler_spec = concrete_spec[lang]
                    
                    # Check if this compiler satisfies any of the allowed compiler specs
                    lang_is_allowed = any(
                        compiler_spec.satisfies(allowed_spec)
                        for allowed_spec in allowed_compiler_specs
                    )
                    
                    if not lang_is_allowed:
                        is_allowed = False
                        break
        else:
            # Old approach: check spec.compiler attribute
            if hasattr(concrete_spec, 'compiler') and concrete_spec.compiler:
                spec_compiler = concrete_spec.compiler
                
                # Check if compiler matches any allowed spec
                compiler_is_allowed = False
                for allowed_spec in allowed_compiler_specs:
                    # Compare compiler name
                    if spec_compiler.name != allowed_spec.name:
                        continue
                    
                    # If allowed spec has no version constraint, allow any version
                    if not allowed_spec.versions or allowed_spec.versions == spack.spec.VersionList([':']):
                        compiler_is_allowed = True
                        break
                    
                    # Check if compiler version satisfies the allowed spec's version
                    if spec_compiler.version and spec_compiler.version in allowed_spec.versions:
                        compiler_is_allowed = True
                        break
                
                is_allowed = compiler_is_allowed
        
        # If this spec uses a disallowed compiler, add to illegal list
        if not is_allowed:
            illegal_specs.append(concrete_spec)
    
    return illegal_specs
