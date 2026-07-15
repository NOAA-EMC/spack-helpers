"""Allow only approved packages in Spack environment.

This command configures a Spack environment so that only approved packages
are buildable while all other packages are marked as non-buildable.
"""

try:
    from spack.util import tty
except ImportError:
    try:
        from spack.llnl.util import tty
    except ImportError:
        from llnl.util import tty

import spack.cmd
import spack.environment as ev
from spack.error import SpackError
from spack.extensions.helpers.allow_only_approved_packages import (
    allow_only_approved_packages,
    read_approved_packages_from_file
)

description = "configure environment to set only approved packages as buildable"
section = "environments"
level = "long"


def setup_parser(subparser):
    """Setup argument parser for allow-only-approved-pkgs command."""
    
    # Make packages and --pkgs-from-file mutually exclusive
    pkg_group = subparser.add_mutually_exclusive_group(required=True)
    pkg_group.add_argument(
        '--packages',
        nargs='+',
        help='approved package names'
    )
    pkg_group.add_argument(
        '--pkgs-from-file',
        type=str,
        help='read approved package names from a newline-delimited text file'
    )


def allow_only_approved_pkgs(parser, args):
    """Handle allow-only-approved-pkgs command.
    
    Args:
        parser: Arg parser
        args: Parsed command-line arguments    
    Returns:
        Exit code: 0 for success, 1 for errors
    """
    
    env = ev.active_environment()
    if not env:
        raise SpackError("No active Spack environment.")
    
    # Get approved packages from command line or file
    if args.pkgs_from_file:
        approved_packages = read_approved_packages_from_file(args.pkgs_from_file)
    else:
        approved_packages = args.packages if args.packages else []
    
    if not approved_packages:
        raise SpackError("No packages specified. Provide package names or use --pkgs-from-file.")
    
    # Configure buildability
    configured_count = allow_only_approved_packages(env, approved_packages)
    
    tty.msg(f"Configured {len(approved_packages)} approved package(s) as buildable.")
    tty.msg("Set 'all' packages as non-buildable (buildable:false).")
    
    # Check if environment has concrete specs and remind user to re-concretize
    if env.concretized_specs():
        tty.warn("Environment has concretized specs. Run 'spack concretize -f' to re-concretize with the new buildabillity settings.")
    
    return 0
