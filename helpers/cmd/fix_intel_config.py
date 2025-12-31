"""Fix Intel OneAPI configuration command.

This command performs various fixes for Intel OneAPI externals:
- Adds LD_LIBRARY_PATH configuration to intel-oneapi-compilers-classic external specs
- Consolidates intel-oneapi-compilers externals by version (optional, with -c flag)
"""

import spack.llnl.util.tty as tty

import spack.cmd
import spack.environment as ev
from spack.error import SpackError
from spack.extensions.helpers.fix_intel_config import (
    fix_intel_lib_config_for_env,
    consolidate_intel_oneapi_compilers
)

description = "fix Intel OneAPI configuration issues (library paths, compiler consolidation)"
section = "environments"
level = "long"


def setup_parser(subparser):
    """Setup argument parser for fix-intel-config command."""
    subparser.add_argument(
        '-c', '--consolidate',
        action='store_true',
        default=False,
        help='consolidate intel-oneapi-compilers externals by version'
    )


def fix_intel_config(parser, args):
    """Handle fix-intel-config command.
    
    Args:
        parser: Arg parser
        args: Parsed command-line arguments
        
    Returns:
        Exit code: 0 for success, 1 for errors
    """
    
    env = ev.active_environment()
    if not env:
        raise SpackError("No active Spack environment.")
    
    try:
        # Always apply library path fix
        modified_count = fix_intel_lib_config_for_env(env)
        
        if modified_count > 0:
            tty.msg(f"Fixed LD_LIBRARY_PATH configuration for {modified_count} intel-oneapi-compilers-classic external(s).")
        else:
            tty.msg("No intel-oneapi-compilers-classic externals needed modification.")
        
        # Optionally consolidate compilers
        if args.consolidate:
            consolidated_count = consolidate_intel_oneapi_compilers(env)
            if consolidated_count > 0:
                tty.msg(f"Consolidated {consolidated_count} intel-oneapi-compilers external(s).")
            else:
                tty.msg("No intel-oneapi-compilers externals needed consolidation.")
        
        # Write changes if any were made
        if modified_count > 0 or (args.consolidate and consolidated_count > 0):
            env.write()
            tty.msg("Environment configuration updated.")
        
        return 0
    except Exception as e:
        tty.error(f"Error fixing Intel configuration: {e}")
        return 1
