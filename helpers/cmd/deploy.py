"""Deploy Spack environments based on configuration files.

This command automates the creation, concretization, validation, fetching,
and installation of multiple spack-stack environments based on a deployments.yaml
configuration file.

This file is not unit tested.
"""

import argparse
import collections
from datetime import datetime
import logging
import os
import socket
import subprocess
import sys
import yaml
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace

try:
    import spack.llnl.util.tty as tty
    using_old_spackstack = False
except ImportError:
    import llnl.util.tty as tty
    using_old_spackstack = True
import spack.cmd
import spack.environment as ev
from spack.error import SpackError
from spack.extensions.helpers.check_duplicates import check_duplicate_packages
from spack.extensions.helpers.check_compiler_usage import check_compiler_usage
from spack.extensions.helpers.check_approved_packages import (
    check_approved_packages,
    read_approved_packages_from_file
)
from spack.extensions.helpers.check_buildable import check_buildable_configuration
from spack.extensions.helpers.check_allowed_compilers import check_allowed_compilers
from spack.extensions.helpers.fetch_cargo import fetch_cargo_dependencies
from spack.extensions.helpers.fetch_go import fetch_go_dependencies
from spack.extensions.helpers.allow_only_approved_packages import allow_only_approved_packages
from spack.extensions.helpers.compiler_compat import uses_compilers_as_nodes

description = "deploy spack-stack environments based on configuration"
section = "environments"
level = "long"

logging.basicConfig(level=logging.CRITICAL)


def setup_parser(subparser):
    """Setup argument parser for deploy command."""
    subparser.add_argument(
        '-n', '--no-scheduler',
        action='store_true',
        help="Run installation on local node (no job scheduler)"
    )
    subparser.add_argument(
        '-x', '--skip-go-rust-handling',
        action='store_true',
        help="Skip handling of Go/Rust dep fetching when using parallel job scheduler"
    )
    subparser.add_argument(
        '-r', '--redeploy-existing',
        action='store_true',
        help="Redeploy existing deployments (default is skip existing env dirs)"
    )
    subparser.add_argument(
        '-s', '--site',
        type=str,
        help='Site name override'
    )
    subparser.add_argument(
        '-u', '--until',
        choices=("create", "concretize", "validate", "fetch", "install"),
        help='Carry out steps up to and including'
    )
    subparser.add_argument(
        'deployments',
        nargs='*',
        help="List of deployments to apply (default is all; specify template+compiler with, e.g., 'unified-dev%%oneapi@2024.2.1')"
    )
    subparser.add_argument(
        '-l', '--list-only',
        action='store_true',
        help="List configured deployments for the detected site and exit"
    )
    subparser.add_argument(
        '--disable-validation-use-at-your-own-risk',
        action='store_true',
        help="Override ordinarily ignored validations (namely for Acorn non-WCOSS2 stacks)"
    )


def get_site_and_tier(deployment={}, args=None):
    """Determine the site and tier for deployment."""
    if args and args.site:
        return args.site, "tier1"
    if "site" in deployment:
        return deployment["site"], "tier1"
    fqdn = socket.getfqdn()
    if "acorn.wcoss2" in fqdn:
        return "acorn", "tier1"
    # Default fallback
    return "default", "tier1"


def get_env_dir_basename(deployment):
    """Generate environment directory basename from deployment config."""
    base = deployment["template"]
    base = base.replace("unified-dev", "ue")
    base = base.replace("-dev", "")
    # Convert compiler spec to hyphenated format for directory name
    return "-".join([base, deployment["compiler"].replace('@', '-', 1)])


def deployment_already_exists(env_dir_basename, spack_stack_dir):
    """Check if deployment environment directory already exists."""
    path_to_check = os.path.join(spack_stack_dir, "envs", env_dir_basename)
    return os.path.isdir(path_to_check)


def is_deployment_requested(env_dir_basename, deployment, args, spack_stack_dir):
    """Determine if a deployment should be processed."""
    template = deployment["template"]
    template_and_compiler = deployment["template"] + "%" + deployment["compiler"]
    if args.deployments and (template not in args.deployments) and (template_and_compiler not in args.deployments):
        return False
    if template in args.deployments:
        return True
    if template_and_compiler in args.deployments:
        return True
    if args.redeploy_existing:
        return True
    return not deployment_already_exists(env_dir_basename, spack_stack_dir)


def get_create_env_settings(env_dir_basename, deployment, deployments, spack_stack_dir):
    """Generate environment creation settings."""
    config_dict = {}
    config_dict["site"] = deployment["site"]
    config_dict["template"] = deployment["template"]
    config_dict["dir"] = os.path.join(spack_stack_dir, "envs")
    config_dict["name"] = env_dir_basename
    if "upstreams" in deployment:
        upstream_full_paths = []
        for upstream_template in deployment["upstreams"]:
            for _candidate_upstream in deployments.values():
                if (_candidate_upstream["template"] == upstream_template) and (_candidate_upstream["compiler"] == deployment["compiler"]):
                    upstream_basename = get_env_dir_basename(_candidate_upstream)
                    upstream_full_path = os.path.join(spack_stack_dir, "envs", upstream_basename, "install")
                    upstream_full_paths.append([upstream_full_path])
                    break
        config_dict["upstreams"] = upstream_full_paths
    if using_old_spackstack:
        config_dict["compiler"] = deployment["compiler"]
    else:
        config_dict["compiler"] = deployment["compiler_hyphenated"]

    return config_dict


def run_batch_install(batch_config, deployment, env_dir_full_path, logfile, logfilepath, packages_to_install=[], suffix=".batch_install"):
    """Run installation via batch scheduler."""
    from spack.util.executable import which
    
    if "walltime" in deployment:
        walltime = deployment["walltime"]
    elif "default_walltime" in batch_config:
        walltime = batch_config["default_walltime"]
    else:
        raise SpackError("Set deployment-specific walltime or batch_config:default_walltime")

    if batch_config["scheduler"] == "pbspro":
        cmd = [
            "qsub",
            "-o", logfilepath + suffix,
            "-e", logfilepath + suffix,
            "-A", batch_config["account"],
            "-q", batch_config["queue"],
            "-l", "walltime=" + walltime + ",select=1:ncpus=12",
            "-V", "-Wblock=true", "--",
            which("spack").path, "--env", env_dir_full_path,
            "install", "--fail-fast", "--show-log-on-error",
            "--concurrent-packages", "4", "--jobs", "4",
        ]
    else:
        raise SpackError("batch_config:scheduler must be pbspro")
    if packages_to_install:
        cmd.extend(packages_to_install)
    logfile.write("Launching batch job:\n%s\n" % " ".join(cmd))
    subprocess.run(cmd, stdout=logfile, stderr=logfile, check=True)


def deploy(parser, args):
    """Execute the deploy command.
    
    Args:
        parser: Argument parser
        args: Parsed command-line arguments
        
    Returns:
        Exit code: 0 for success, 1 for errors
    """
    # Check that we're not already in an environment
    if os.getenv("SPACK_ENV"):
        raise SpackError("$SPACK_ENV is set. Deactivate the current environment before deploying.")

    # Get spack-stack directory
    spack_stack_dir = os.getenv("SPACK_STACK_DIR")
    if not spack_stack_dir:
        raise SpackError("$SPACK_STACK_DIR environment variable is not set.")

    # Load stack extension and related modules
    try:
        import spack.extensions
        spack.extensions.load_extension("stack")
        from spack.extensions.stack.cmd.stack_cmds.create import StackEnv
        from spack.extensions.stack.meta_modules import setup_meta_modules
    except Exception as e:
        raise SpackError(f"Failed to load spack-stack extension: {e}")

    # Setup logging
    nowdate = datetime.now().strftime("%Y%m%d-%H%M")
    logdir = os.path.join(spack_stack_dir, "deploy_logs")
    os.makedirs(logdir, exist_ok=True)

    # Load deployments.yaml configuration
    site, tier = get_site_and_tier(args=args)
    deployments_yaml_path = os.path.join(spack_stack_dir, "configs", "sites", tier, site, "deployments.yaml")
    
    if not os.path.exists(deployments_yaml_path):
        raise SpackError(f"Deployments configuration not found at: {deployments_yaml_path}")
    
    with open(deployments_yaml_path, "r") as f:
        deployments_yaml = yaml.safe_load(f)
    
    tty.msg(f"Loading deployments.yaml for site {site}")

    # Generate deployments object, including iterating over compilers
    deployments = collections.OrderedDict()

    for _deployment in deployments_yaml["deployments"]:
        for _compiler in _deployment["compilers"]:
            deployment = _deployment.copy()
            del(deployment["compilers"])
            deployment["compiler"] = _compiler
            deployment["compiler_hyphenated"] = _compiler.replace('@', '-', 1)
            if "packages_to_install" not in deployment:
                deployment["packages_to_install"] = []
            if "only_concretize_requested_packages" not in deployment:
                deployment["only_concretize_requested_packages"] = False
            env_dir_basename = get_env_dir_basename(deployment)
            deployments[env_dir_basename] = deployment
            deployment["site"] = get_site_and_tier(deployment=_deployment)[0]
            tty.msg(f"  Registered deployment: {deployment['template']}%{deployment['compiler']} ({env_dir_basename}, using '{deployment['site']}' site config)")

    if args.list_only:
        sys.exit(0)

    tty.msg("=" * 30)

    # Create and install each deployment
    for env_dir_basename, deployment in deployments.items():
        if not is_deployment_requested(env_dir_basename, deployment, args, spack_stack_dir):
            tty.msg(f"Skipping deployment: {deployment['template']}%{deployment['compiler']} ({env_dir_basename})")
            continue
        
        tty.msg("=" * 30)
        
        # Create env based on config
        stack_settings = get_create_env_settings(env_dir_basename, deployment, deployments, spack_stack_dir)
        env_dir_full_path = os.path.join(spack_stack_dir, "envs", env_dir_basename)
        
        if os.path.isdir(env_dir_full_path) and args.redeploy_existing:
            backup_dir_full_path = os.path.join(spack_stack_dir, "envs", env_dir_basename + "_bkp")
            if os.path.isdir(backup_dir_full_path):
                raise SpackError(f"Backup dir {backup_dir_full_path} already exists")
            tty.msg(f"Moving {env_dir_full_path}\n  to {backup_dir_full_path}")
            os.rename(env_dir_full_path, backup_dir_full_path)
        
        # Use hyphenated compiler format in log file name
        logfilepath = os.path.join(logdir, nowdate + f".{deployment['template']}.{deployment['compiler_hyphenated']}.log")
        tty.msg(f"Log file: {logfilepath}")
        logfile = open(logfilepath, "a", buffering=1)
        logfile.write(str(deployment) + "\n")
        logfile.write(str(stack_settings) + "\n")
        
        tty.msg(f"Creating environment for {deployment['template']}/{deployment['compiler']} with '{deployment['site']}' site config")
        tty.msg(f"  at {env_dir_full_path} ...")
        
        # Use equivalent of 'spack stack create env'
        stack_env = StackEnv(**stack_settings)
        stack_env.write()
        stack_env.check_umask()
        env = ev.Environment(env_dir_full_path)
        ev.activate(env)

        # Filter out unwanted packages before concretization
        if deployment["only_concretize_requested_packages"]:
            # Check if specs are defined in manifest definitions structure
            has_definitions = (
                "spack" in env.manifest 
                and "definitions" in env.manifest["spack"]
                and isinstance(env.manifest["spack"]["definitions"], list)
            )
            
            if has_definitions:
                # Remove specs from definitions lists
                import spack.spec
                for definition in env.manifest["spack"]["definitions"]:
                    if isinstance(definition, dict) and "packages" in definition:
                        original_packages = definition["packages"][:]
                        definition["packages"] = []
                        for pkg_entry in original_packages:
                            # Parse as spec and check if it satisfies any requested package
                            try:
                                spec = spack.spec.Spec(pkg_entry)
                                keep_spec = False
                                for requested_pkg in deployment["packages_to_install"]:
                                    requested_spec = spack.spec.Spec(requested_pkg)
                                    if spec.satisfies(requested_spec):
                                        keep_spec = True
                                        break
                                if keep_spec:
                                    definition["packages"].append(pkg_entry)
                            except:
                                # If parsing fails, keep the entry to be safe
                                definition["packages"].append(pkg_entry)
            else:
                # Use env.remove() for specs in roots
                for root_spec in env.roots():
                    if root_spec.name not in deployment["packages_to_install"]:
                        env.remove(root_spec)
            
            env.write()

        # Configure buildability if approved packages list exists or site is wcoss2
        approved_list_path = os.path.join(env_dir_full_path, "site", "approved_packages.txt")
        if (os.path.exists(approved_list_path) or deployment["site"] in ["wcoss2", "acorn"]) and not args.disable_validation_use_at_your_own_risk:
            tty.msg("... configuring buildability for approved packages ...")
            approved_packages = read_approved_packages_from_file(approved_list_path)
            configured_count = allow_only_approved_packages(env, approved_packages)

        if args.until == "create":
            ev.deactivate()
            logfile.close()
            continue

        # Concretize environment
        tty.msg(f"... concretizing ...")
        with redirect_stdout(logfile), redirect_stderr(logfile):
            with env.write_transaction():
                concretized_specs = env.concretize()
                env.write()
            ev.display_specs([concrete for _, concrete in concretized_specs])

        if args.until == "concretize":
            ev.deactivate()
            logfile.close()
            continue

        tty.msg("... validating concretization ...")
        
        # Check for duplicate packages
        ignore_list = [] if "duplicates_to_ignore" not in deployment else deployment["duplicates_to_ignore"]
        duplicates = check_duplicate_packages(env, ignore_packages=ignore_list)
        if duplicates:
            tty.error("Duplicate packages found in environment:")
            for pkg_name, specs in duplicates.items():
                tty.error(f"  {pkg_name}:")
                for spec in specs:
                    tty.error(f"    - {spec.dag_hash(length=7)} {spec}")
            raise SpackError("Duplicates found! Review the errors above.")

        # Check that only allowed compilers are used
        allowed_compiler_spec = deployment["compiler"]
        illegal_compiler_specs = check_allowed_compilers(env, [allowed_compiler_spec, "gcc"])
        if illegal_compiler_specs:
            tty.error(f"Packages using disallowed compilers (allowed: {allowed_compiler_spec}):")
            for spec in illegal_compiler_specs:
                tty.error(f"  - {spec.name}/{spec.dag_hash(length=7)} (compiler: {spec.compiler})")
            raise SpackError("Disallowed compilers found! Review the errors above.")

        # Check for packages that shouldn't be built with GCC
        if "allowed_gcc_packages" in deployment:
            illegal_gcc_specs = check_compiler_usage(
                env, "gcc", deployment["allowed_gcc_packages"]
            )
            if illegal_gcc_specs:
                tty.error("Packages built with GCC that are not in allowed_gcc_packages:")
                for spec in illegal_gcc_specs:
                    tty.error(f"  - {spec.name}/{spec.dag_hash(length=7)}")
                raise SpackError("Illegal GCC usage found! Review the errors above.")

        # Check for approved packages if approved_packages.txt exists
        approved_list_path = os.path.join(env_dir_full_path, "site", "approved_packages.txt")
        if (os.path.exists(approved_list_path) or deployment["site"] in ["wcoss2", "acorn"]) and not args.disable_validation_use_at_your_own_risk:
            approved_packages = read_approved_packages_from_file(approved_list_path)
            unauthorized_specs = check_approved_packages(env, approved_packages)
            if unauthorized_specs:
                tty.error("Unauthorized packages found in environment:")
                for spec in unauthorized_specs:
                    tty.error(f"  - {spec.name}/{spec.dag_hash(length=7)}")
                raise SpackError("Unauthorized packages found! Review the errors above.")

        # Check buildable configuration
        buildability_violations = check_buildable_configuration(env)
        if buildability_violations:
            tty.error("Packages marked unbuildable but being built:")
            for spec in buildability_violations:
                tty.error(f"  - {spec.name}/{spec.dag_hash(length=7)}")
            raise SpackError("Buildability configuration violations found! Review the errors above.")

        if args.until == "validate":
            ev.deactivate()
            logfile.close()
            continue

        # Fetch packages
        tty.msg(f"... fetching packages ...")
        for spec in env.all_specs():
            logfile.write(f"Fetching {spec.name}@{spec.version}/{spec.dag_hash(length=7)}\n")
            with redirect_stdout(logfile), redirect_stderr(logfile):
                spec.package.do_fetch()

        if args.until == "fetch":
            ev.deactivate()
            logfile.close()
            continue

        # Install packages
        if deployment["packages_to_install"]:
            tty.msg("... installing specs: " + " ".join(deployment["packages_to_install"]) + "...")
        else:
            tty.msg("... installing ...")
        
        if args.no_scheduler:
            specs = env.all_matching_specs(*(" ".join(deployment["packages_to_install"])))
            env.install_specs(specs)
        else:
            logfile.write("Starting install jobs via job scheduler...\n")
            if not args.skip_go_rust_handling:
                # Install rust and go packages first
                run_batch_install(deployments_yaml["batch_config"], deployment, env_dir_full_path, logfile, logfilepath, packages_to_install=["rust", "go"], suffix=".rustgo")
                
                # Fetch Rust/Cargo dependencies
                rust_specs = [s for s in env.all_specs() if "rust" in s and s.name != "rust"]
                if rust_specs:
                    tty.msg("... fetching Rust/Cargo dependencies ...")
                    fetch_cargo_dependencies(rust_specs, use_spack_rust=True)
                
                # Fetch Go dependencies
                go_specs = [s for s in env.all_specs() if "go" in s and s.name != "go"]
                if go_specs:
                    tty.msg("... fetching Go module dependencies ...")
                    fetch_go_dependencies(go_specs, use_spack_go=True)
            
            run_batch_install(deployments_yaml["batch_config"], deployment, env_dir_full_path, logfile, logfilepath, packages_to_install=deployment["packages_to_install"])

        if args.until == "install":
            ev.deactivate()
            logfile.close()
            continue

        # Generate modules
        tty.msg(f"... writing package modules ...")
        
        # Collect all compilers used in the environment for module configuration
        all_compilers = set()
        for spec in env.all_specs():
            if uses_compilers_as_nodes(spec):
                # New model: compiler languages are dependencies
                for language in ("c", "cxx", "fortran"):
                    if language in spec:
                        all_compilers.add(spec[language].name)
            else:
                # Old model: use spec.compiler attribute
                if hasattr(spec, 'compiler') and spec.compiler:
                    all_compilers.add(spec.compiler.name)
        
        subprocess.run(
            ["spack", "--env", env_dir_full_path, "module", "lmod", "refresh", "--yes-to-all", "--upstream-modules"],
            stdout=logfile,
            stderr=logfile,
            check=True,
            text=True,
        )
        
        # Also generate a modules dir with a flat structure, i.e., everything is under Core with no metamodules
        cfg_hierarchy = "modules:default:lmod:hierarchy::[]"
        cfg_compilers = "modules:default:lmod:core_compilers::[%s]" % ",".join(all_compilers)
        cfg_root = "modules:default:roots:lmod:$env/modules_flat"
        subprocess.run(
            [
                "spack", "--env", env_dir_full_path,
                "--config", cfg_hierarchy,
                "--config", cfg_compilers,
                "--config", cfg_root,
                "module", "lmod", "refresh", "--yes-to-all"
            ],
            stdout=logfile,
            stderr=logfile,
            check=True,
            text=True,
        )

        # Meta modules
        tty.msg(f"... writing metamodules ...")
        setup_meta_modules()

        # Close this deployment's logfile and zero out spack.environment's stored config info
        ev.deactivate()
        logfile.close()

        tty.msg(f"... done.")

    return 0
