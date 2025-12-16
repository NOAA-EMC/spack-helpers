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

import spack.llnl.util.tty as tty
import spack.cmd
import spack.environment as ev
from spack.error import SpackError
from spack.extensions.helpers.check_duplicates import check_duplicate_packages

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
    return "-".join([base, deployment["compiler"]])


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
    config_dict["site"] = get_site_and_tier(deployment=deployment)[0]
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
    config_dict["compiler"] = deployment["compiler"]

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
            if "packages_to_install" not in deployment:
                deployment["packages_to_install"] = []
            if "only_concretize_requested_packages" not in deployment:
                deployment["only_concretize_requested_packages"] = False
            env_dir_basename = get_env_dir_basename(deployment)
            deployments[env_dir_basename] = deployment
            tty.msg(f"  Registered deployment: {deployment['template']}/{deployment['compiler']} ({env_dir_basename})")

    tty.msg("=" * 30)

    # Create and install each deployment
    for env_dir_basename, deployment in deployments.items():
        if not is_deployment_requested(env_dir_basename, deployment, args, spack_stack_dir):
            tty.msg(f"Skipping deployment: {deployment['template']}/{deployment['compiler']} ({env_dir_basename})")
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
        
        logfilepath = os.path.join(logdir, nowdate + f".{deployment['template']}.{deployment['compiler']}.log")
        tty.msg(f"Log file: {logfilepath}")
        logfile = open(logfilepath, "a", buffering=1)
        logfile.write(str(deployment) + "\n")
        logfile.write(str(stack_settings) + "\n")
        
        tty.msg(f"Creating environment for {deployment['template']}/{deployment['compiler']}")
        tty.msg(f"  at {env_dir_full_path} ...")
        
        # Use equivalent of 'spack stack create env'
        stack_env = StackEnv(**stack_settings)
        stack_env.write()
        stack_env.check_umask()
        env = ev.Environment(env_dir_full_path)
        ev.activate(env)

        # Filter out unwanted packages before concretization
        if deployment["only_concretize_requested_packages"]:
            for root_spec in env.roots():
                if root_spec.name not in deployment["packages_to_install"]:
                    env.remove(root_spec)
            env.write()

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

        # Fail if there packages that shouldn't be built with GCC are built with GCC:
        all_compilers = set()
        for spec in env.all_specs():
            for language in ("c", "cxx", "fortran"):
                if language not in spec:
                    continue
                compiler_name = spec[language].name
                all_compilers.add(compiler_name)
                if "allowed_gcc_packages" in deployment:
                    is_legal = not (compiler_name == "gcc" and spec.name not in deployment["allowed_gcc_packages"])
                    if not is_legal:
                        raise SpackError(f"spec '{spec.name}/{spec.dag_hash()}' to be built with GCC but not in 'allowed_gcc_packages'!")

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
        tty.msg("... installing", end="")
        if deployment["packages_to_install"]:
            tty.msg(" specs: " + " ".join(deployment["packages_to_install"]), end="")
        tty.msg(" ...")
        
        if args.no_scheduler:
            specs = env.all_matching_specs(*(" ".join(deployment["packages_to_install"])))
            env.install_specs(specs)
        else:
            logfile.write("Starting install jobs via job scheduler...\n")
            if not args.skip_go_rust_handling:
                run_batch_install(deployments_yaml["batch_config"], deployment, env_dir_full_path, logfile, logfilepath, packages_to_install=["rust", "go"], suffix=".rustgo")
                shell_env = os.environ.copy()
                shell_env["SPACK_ENV"] = env_dir_full_path
                subprocess.run(
                    os.path.join(spack_stack_dir, "util", "fetch_cargo_deps.py"),
                    env=shell_env,
                    stdout=logfile,
                    stderr=logfile,
                    check=True,
                    text=True,
                )
                subprocess.run(
                    os.path.join(spack_stack_dir, "util", "fetch_go_deps.py"),
                    env=shell_env,
                    stdout=logfile,
                    stderr=logfile,
                    check=True,
                    text=True,
                )
            run_batch_install(deployments_yaml["batch_config"], deployment, env_dir_full_path, logfile, logfilepath, packages_to_install=deployment["packages_to_install"])

        if args.until == "install":
            ev.deactivate()
            logfile.close()
            continue

        # Generate modules
        tty.msg(f"... writing package modules ...")
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
