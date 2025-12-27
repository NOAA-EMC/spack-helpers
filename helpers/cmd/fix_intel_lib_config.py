"""Fix Intel OneAPI library configuration command.

This command adds LD_LIBRARY_PATH configuration to intel-oneapi-compilers-classic
external specs in the active Spack environment.
"""

import spack.llnl.util.tty as tty

import spack.cmd
import spack.environment as ev
from spack.error import SpackError
from spack.extensions.helpers.fix_intel_lib_config import fix_intel_lib_config_for_env

description = "add LD_LIBRARY_PATH configuration for intel-oneapi-compilers-classic externals"
section = "environments"
level = "long"


def setup_parser(subparser):
    """Setup argument parser for fix-intel-lib-config command."""
    pass  # No arguments needed for this command


def fix_intel_lib_config(parser, args):
    """Handle fix-intel-lib-config command.
    
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
        modified_count = fix_intel_lib_config_for_env(env)
        
        if modified_count > 0:
            tty.msg(f"Fixed LD_LIBRARY_PATH configuration for {modified_count} intel-oneapi-compilers-classic external(s).")
            env.write()
            tty.msg("Environment configuration updated.")
        else:
            tty.msg("No intel-oneapi-compilers-classic externals needed modification.")
        
        return 0
    except Exception as e:
        tty.error(f"Error fixing Intel library configuration: {e}")
        return 1
