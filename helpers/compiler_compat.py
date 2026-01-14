"""Compatibility utilities for handling both old and new Spack compiler models.

This module provides utilities to detect and handle both:
- Old model: Compilers configured in compilers.yaml, accessed via spec.compiler attribute
- New model: Compilers as packages/nodes in the DAG, accessed via spec["c"], spec["cxx"], spec["fortran"]
"""

import spack.spec


def uses_compilers_as_nodes(spec):
    """Detect if a spec uses the compilers-as-nodes model.
    
    In newer Spack versions with compilers-as-nodes, compiler languages
    (c, cxx, fortran) are virtual dependencies that can be accessed via
    the spec["c"], spec["cxx"], spec["fortran"] syntax.
    
    In older Spack versions, compilers were configured in compilers.yaml
    and accessed via spec.compiler attribute.
    
    Args:
        spec: A concrete Spack spec to check
        
    Returns:
        bool: True if spec uses compilers-as-nodes, False if traditional model
    """
    if not spec.concrete:
        return False
    
    # Check if any compiler language exists as a dependency
    return any(lang in spec for lang in ("c", "cxx", "fortran"))


def get_compiler_names(spec):
    """Get compiler package names used by a spec, handling both models.
    
    Args:
        spec: A concrete Spack spec
        
    Returns:
        set: Set of compiler package names (e.g., {"gcc", "intel-oneapi-compilers"})
    """
    if not spec.concrete:
        return set()
    
    compiler_names = set()
    
    if uses_compilers_as_nodes(spec):
        # New model: get names from compiler package dependencies
        for lang in ("c", "cxx", "fortran"):
            if lang in spec:
                compiler_names.add(spec[lang].name)
    else:
        # Old model: extract compiler name from spec.compiler
        if hasattr(spec, 'compiler') and spec.compiler:
            # spec.compiler is a CompilerSpec like "gcc@11.2.0"
            # Extract just the name part
            compiler_names.add(str(spec.compiler.name))
    
    return compiler_names


def check_spec_uses_compiler_name(spec, compiler_name):
    """Check if a spec uses a specific compiler by name.
    
    Handles both old and new compiler models.
    
    Args:
        spec: Concrete spec to check
        compiler_name: Name of compiler to check for (e.g., "gcc", "intel")
        
    Returns:
        bool: True if spec uses the specified compiler
    """
    if not spec.concrete:
        return False
    
    if uses_compilers_as_nodes(spec):
        # New model: check if any language uses this compiler
        for lang in ("c", "cxx", "fortran"):
            if lang in spec:
                if spec[lang].name == compiler_name:
                    return True
        return False
    else:
        # Old model: check spec.compiler.name
        if hasattr(spec, 'compiler') and spec.compiler:
            return spec.compiler.name == compiler_name
        return False
