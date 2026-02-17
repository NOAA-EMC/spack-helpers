"""Validate Spack environments for common issues.

This command provides validation checks for Spack environments,
including detection of duplicate package installations.
"""

import sys

try:
    import spack.llnl.util.tty as tty
except ImportError:
    import llnl.util.tty as tty

import spack.cmd
import spack.environment as ev
from spack.error import SpackError
from spack.extensions.helpers.check_duplicates import check_duplicate_packages
from spack.extensions.helpers.check_compiler_usage import check_compiler_usage
from spack.extensions.helpers.check_allowed_compilers import check_allowed_compilers
from spack.extensions.helpers.check_approved_packages import (
    check_approved_packages,
    read_approved_packages_from_file
)
from spack.extensions.helpers.check_buildable import check_buildable_configuration

description = "validate Spack environments"
section = "environments"
level = "long"


def _is_environment_fully_concretized(env):
    """Check if the active environment is fully concretized.
    
    An environment is fully concretized if all user specs have corresponding
    concretized specs in the lockfile.
    
    Args:
        env: A Spack Environment object
        
    Returns:
        bool: True if environment is fully concretized, False otherwise
    """

    # Check if all user specs are concretized
    return all([x in env.concrete_specs for x in env.user_specs])


def setup_parser(subparser):
    """Setup argument parser for validate command."""
    sp = subparser.add_subparsers(metavar='SUBCOMMAND', dest='validate_command')
    
    # check-duplicates subcommand
    duplicates_parser = sp.add_parser(
        'check-duplicates',
        help='check for duplicate package installations in environment'
    )
    duplicates_parser.add_argument(
        '-i', '--ignore-package',
        action='append',
        default=[],
        help='package name to ignore (can be specified multiple times)'
    )
    duplicates_parser.add_argument(
        '--ignore-build-deps',
        action='store_true',
        help='ignore duplicates for packages that are only used as build dependencies'
    )
    
    # allow-pkgs-for-compiler subcommand
    compiler_parser = sp.add_parser(
        'allow-pkgs-for-compiler',
        help='ensure only specified packages use a given compiler'
    )
    compiler_parser.add_argument(
        'compiler',
        help='compiler name to check (e.g., gcc, clang, intel)'
    )
    compiler_parser.add_argument(
        'packages',
        nargs='+',
        help='package names allowed to use the specified compiler'
    )
    compiler_parser.add_argument(
        '--pkgs-from-file',
        type=str,
        help='read allowed package names from a newline-delimited text file'
    )
    
    # compilers subcommand
    compilers_parser = sp.add_parser(
        'compilers',
        help='ensure only specified compilers appear in environment'
    )
    compilers_parser.add_argument(
        'compilers',
        nargs='+',
        help='allowed compiler specs (e.g., gcc@11.2.0 clang@14.0.0)'
    )
    
    # check-approved-pkgs subcommand
    approved_parser = sp.add_parser(
        'check-approved-pkgs',
        help='ensure only approved packages appear in environment'
    )
    
    # Make packages and --pkgs-from-file mutually exclusive
    pkg_group = approved_parser.add_mutually_exclusive_group(required=True)
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
    
    # check-buildable subcommand
    buildable_parser = sp.add_parser(
        'check-buildable',
        help='verify that unbuildable packages are not being built'
    )


def validate(parser, args):
    """Handle validate subcommands.
    
    Args:
        parser: Arg parser
        args: Parsed command-line arguments    
    Returns:
        Exit code: 0 for success, 1 for errors
    """

    if not args.validate_command:
        parser.print_help()
        return 1
    
    env = ev.active_environment()
    if not env:
        raise SpackError("No active Spack environment.")
    
    # Check if environment is fully concretized
    if not _is_environment_fully_concretized(env):
        tty.warn("Environment may not be fully concretized. Run 'spack concretize' to update.")

    if args.validate_command == 'check-duplicates':
        ignore_packages = args.ignore_package if args.ignore_package else []
        duplicates = check_duplicate_packages(
            env, 
            ignore_packages=ignore_packages,
            ignore_build_deps=args.ignore_build_deps
        )
        
        if duplicates:
            tty.error("Duplicates found!")
            for pkg_name, specs in duplicates.items():
                tty.msg(f"\nPackage: {pkg_name}")
                for spec in specs:
                    tty.msg(f"  {spec.format('{name}@{version}/{hash:7}')}")
            return 1
        else:
            tty.msg("No duplicates found.")
            return 0
    
    elif args.validate_command == 'allow-pkgs-for-compiler':
        # Get allowed packages from command line or file (mutually exclusive via argparse)
        if args.pkgs_from_file:
            try:
                with open(args.pkgs_from_file, 'r') as f:
                    allowed_packages = [
                        line.strip() for line in f 
                        if line.strip() and not line.strip().startswith('#')
                    ]
            except IOError as e:
                raise SpackError(f"Could not read package list from {args.pkgs_from_file}: {e}")
        else:
            allowed_packages = args.packages
        
        illegal_specs = check_compiler_usage(
            env, 
            restricted_compiler_name=args.compiler,
            allowed_packages=allowed_packages
        )
        
        if illegal_specs:
            tty.error(f"Found {len(illegal_specs)} package(s) using compiler '{args.compiler}' that are not in the allowed list!")
            for spec in illegal_specs:
                tty.msg(f"  {spec.format('{name}@{version}/{hash:7}')} (compiler: {spec.compiler})")
            return 1
        else:
            tty.msg(f"All packages using compiler '{args.compiler}' are in the allowed list.")
            return 0
    
    elif args.validate_command == 'compilers':
        illegal_specs = check_allowed_compilers(
            env, 
            allowed_compilers=args.compilers
        )
        
        if illegal_specs:
            tty.error(f"Found {len(illegal_specs)} spec(s) using disallowed compiler(s)!")
            for spec in illegal_specs:
                lang_strs = []
                for lang in ("c", "cxx", "fortran"):
                    if lang in spec:
                        lang_strs += [lang + " provider: " + spec[lang].format('{name}@{version}/{hash:7}')]
                tty.msg(f"  {spec.format('{name}@{version}/{hash:7}')} using {', '.join(lang_strs)}")
            return 1
        else:
            tty.msg("All specs use allowed compilers.")
            return 0
    
    elif args.validate_command == 'check-approved-pkgs':
        if args.pkgs_from_file:
            approved_packages = read_approved_packages_from_file(args.pkgs_from_file)
        else:
            approved_packages = args.packages
        
        unauthorized_specs = check_approved_packages(
            env, 
            approved_packages=approved_packages
        )
        
        if unauthorized_specs:
            tty.error(f"Found {len(unauthorized_specs)} unauthorized package(s)!")
            for spec in unauthorized_specs:
                tty.msg(f"  {spec.format('{name}@{version}/{hash:7}')}")
            return 1
        else:
            tty.msg("All packages are approved.")
            return 0
    
    elif args.validate_command == 'check-buildable':
        violations = check_buildable_configuration(env)
        
        if violations:
            tty.error(f"Found {len(violations)} package(s) marked unbuildable but being built!")
            for spec in violations:
                tty.msg(f"  {spec.format('{name}@{version}/{hash:7}')}")
            return 1
        else:
            tty.msg("All unbuildable packages are using externals.")
            return 0
