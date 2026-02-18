"""Filter compiler packages from environment packages configuration.

This command filters compiler packages in the packages configuration
based on user-specified compiler specs.
"""

try:
    import spack.llnl.util.tty as tty
except ImportError:
    import llnl.util.tty as tty

import spack.cmd
import spack.environment as ev
from spack.error import SpackError
from spack.extensions.helpers.filter_compiler_packages import filter_compiler_packages

description = "filter compiler packages from environment packages configuration"
section = "environments"
level = "long"


def setup_parser(subparser):
    """Setup argument parser for filter-compilers command."""
    subparser.add_argument(
        'compiler_specs',
        nargs='+',
        help='compiler specs to filter (e.g., gcc@11.2.0 clang@14.0.0)'
    )
    
    mode_group = subparser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        '--remove',
        action='store_true',
        help='remove specified compiler specs'
    )
    mode_group.add_argument(
        '--keep-only',
        action='store_true',
        help='keep only specified compiler specs'
    )
    
    subparser.add_argument(
        '--all-compilers-unbuildable',
        action='store_true',
        help='mark all compiler languages (c, cxx, fortran) as unbuildable'
    )


def filter_compilers(parser, args):
    """Handle filter-compilers command.
    
    Args:
        parser: Arg parser
        args: Parsed command-line arguments    
    Returns:
        Exit code: 0 for success, 1 for errors
    """
    
    env = ev.active_environment()
    if not env:
        raise SpackError("No active Spack environment.")
    
    # Determine mode
    if args.remove:
        mode = 'remove'
    elif args.keep_only:
        mode = 'keep-only'
    else:
        raise SpackError("No filter mode specified")
    
    try:
        modified_count = filter_compiler_packages(
            env,
            args.compiler_specs,
            mode=mode
        )
        
        if modified_count > 0:
            tty.msg(f"Filtered {modified_count} compiler package(s) from packages configuration.")
            env.write()
            tty.msg("Environment configuration updated.")
        else:
            tty.msg("No compiler packages were filtered.")
        
        # Handle --all-compilers-unbuildable option
        if args.all_compilers_unbuildable:
            tty.msg("Setting all compiler languages (c, cxx, fortran) as unbuildable...")
            
            # Get packages config from environment
            if 'packages' not in env.manifest.configuration:
                env.manifest.configuration['packages'] = {}
            
            packages = env.manifest.configuration['packages']
            
            # Set buildable: false for each compiler language
            for compiler_lang in ['c', 'cxx', 'fortran']:
                if compiler_lang not in packages:
                    packages[compiler_lang] = {}
                packages[compiler_lang]['buildable'] = False
            
            # Mark as changed and write
            env.manifest.changed = True
            env.write()
            tty.msg("Set c, cxx, and fortran as unbuildable.")
        
        return 0
    except Exception as e:
        tty.error(f"Error filtering compiler packages: {e}")
        return 1
