#!/usr/bin/env python3

"""
Recursive Composite Scanner

This script scans a GitHub repository and recursively checks all external actions.

It issues OS-level commands like 'git clone', so run in a secure environment
if you're scanning unknown or untrusted repositories.
"""

import os
import re
import shutil
import subprocess
import sys
import json
from pathlib import Path
from typing import Set, Tuple, Dict, List
from collections import OrderedDict

import yaml  # pip install PyYAML


# --------------------------------------------------------------------
# Utility: Print logs to STDERR so they don't mix with JSON on STDOUT.
# --------------------------------------------------------------------

def eprint(*args, **kwargs):
    """Print to stderr."""
    print(*args, file=sys.stderr, **kwargs)


# --------------------------------------------------------------------
# run_cmd: Execute a command quietly (-q), with optional logging.
# --------------------------------------------------------------------

def run_cmd(cmd_list, cwd=None, log_msg=None, output_json=False):
    """
    Runs a command in a subprocess quietly (-q). For Git commands, we include the '-q' flag.
    If output_json=True, we log to eprint (stderr).
    Otherwise, we log to normal stdout.
    """
    if log_msg:
        if output_json:
            eprint(log_msg)
        else:
            print(log_msg)

    try:
        subprocess.check_call(cmd_list, cwd=cwd)
    except subprocess.CalledProcessError as exc:
        raise exc


# --------------------------------------------------------------------
# GIT & SHELL COMMANDS (quiet)
# --------------------------------------------------------------------

def git_clone_quiet(repo_url: str, target_dir: str, cwd=None, output_json=False):
    """Runs 'git clone -q <repo_url> <target_dir>' quietly."""
    run_cmd([
        'git', 'clone', '-q', repo_url, target_dir
    ], cwd=cwd, log_msg=f"Cloning {repo_url} => {target_dir}", output_json=output_json)


def git_fetch_all_quiet(repo_dir: str, output_json=False):
    """Runs 'git fetch -q --all' quietly."""
    run_cmd([
        'git', 'fetch', '-q', '--all'
    ], cwd=repo_dir, log_msg="Fetching all branches...", output_json=output_json)


def git_fetch_tags_quiet(repo_dir: str, output_json=False):
    """Runs 'git fetch -q --tags' quietly."""
    run_cmd([
        'git', 'fetch', '-q', '--tags'
    ], cwd=repo_dir, log_msg="Fetching tags...", output_json=output_json)


def git_checkout_quiet(repo_dir: str, version: str, output_json=False):
    """Runs 'git checkout -q <version>' quietly."""
    run_cmd([
        'git', 'checkout', '-q', version
    ], cwd=repo_dir, log_msg=f"Checking out {version}...", output_json=output_json)


# --------------------------------------------------------------------
# ACTION SCANNING
# --------------------------------------------------------------------

def is_external_action(uses_value: str) -> bool:
    """Check if 'uses_value' looks like 'owner/repo@version'."""
    return ("/" in uses_value) and ("@" in uses_value)


def parse_uses_value(uses_value: str) -> Tuple[str, str, str]:
    """Parse 'owner/repo@version' => (owner, repo, version)."""
    match = re.match(r"^([^/]+)/([^@]+)@(.+)$", uses_value)
    if not match:
        raise ValueError(f"Cannot parse uses string: {uses_value}")
    return match.group(1), match.group(2), match.group(3)


def find_workflow_files(repo_dir: str) -> List[Path]:
    """Return all .yml/.yaml in .github/workflows/, recursively."""
    wf_dir = Path(repo_dir) / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    return list(wf_dir.rglob("*.yml")) + list(wf_dir.rglob("*.yaml"))


def get_actions_from_workflows(repo_dir: str) -> Set[Tuple[str, str, str]]:
    """Parse each workflow file, look for external actions in steps => uses."""
    found = set()
    files = find_workflow_files(repo_dir)
    for wf in files:
        try:
            doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue

        jobs = doc.get("jobs", {})
        if not isinstance(jobs, dict):
            continue

        for _, job_data in jobs.items():
            if not isinstance(job_data, dict):
                continue
            steps = job_data.get("steps", [])
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                uses_val = step.get("uses")
                if uses_val and is_external_action(uses_val):
                    try:
                        found.add(parse_uses_value(uses_val))
                    except ValueError:
                        pass
    return found


def is_unpinned_docker_image(image_str: str) -> bool:
    """If 'docker://...' and not pinned by @sha256: => unpinned."""
    if not image_str.startswith("docker://"):
        return False
    ref = image_str[len("docker://"):]
    return ("@sha256:" not in ref)


def analyze_dockerfile(dockerfile_path: Path) -> List[str]:
    """Naive Dockerfile parser, warns if FROM lines lack @sha256:"""
    warnings = []
    try:
        with dockerfile_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip().upper().startswith("FROM "):
                    ref = line.strip()[5:].strip()
                    if "@sha256:" not in ref:
                        warnings.append(f"Unpinned Docker FROM => '{ref}'")
    except Exception as e:
        warnings.append(f"Could not read Dockerfile: {e}")
    return warnings


def find_top_level_action_file(repo_dir: str) -> Path:
    for name in ("action.yml", "action.yaml"):
        candidate = Path(repo_dir) / name
        if candidate.is_file():
            return candidate
    return None


def get_actions_and_docker_warnings_from_action_file(action_file: Path):
    """Check if it's docker or composite, gather sub-actions & docker warnings."""
    discovered = set()
    docker_warns = []
    try:
        doc = yaml.safe_load(action_file.read_text(encoding="utf-8"))
    except Exception as e:
        docker_warns.append(f"Could not parse {action_file.name}: {e}")
        return discovered, docker_warns

    if not isinstance(doc, dict):
        return discovered, docker_warns

    runs = doc.get("runs", {})
    if not isinstance(runs, dict):
        return discovered, docker_warns

    using = runs.get("using")

    if using == "docker":
        image = runs.get("image")
        if isinstance(image, str):
            if image.startswith("docker://"):
                # check pinned?
                if is_unpinned_docker_image(image):
                    docker_warns.append(f"Unpinned Docker image => {image}")
            elif image == "Dockerfile":
                df_path = action_file.parent / "Dockerfile"
                if df_path.is_file():
                    docker_warns.extend(analyze_dockerfile(df_path))
                else:
                    docker_warns.append("runs.image='Dockerfile' but no Dockerfile found in root.")
        return discovered, docker_warns

    if using == "composite":
        steps = runs.get("steps", [])
        if isinstance(steps, list):
            for step in steps:
                uses_val = step.get("uses")
                if uses_val and is_external_action(uses_val):
                    try:
                        discovered.add(parse_uses_value(uses_val))
                    except ValueError:
                        pass
    return discovered, docker_warns


# --------------------------------------------------------------------
# CLONE & CHECKOUT
# --------------------------------------------------------------------

def clone_repo(owner: str, repo: str, version: str, base_dir: str, output_json=False) -> str:
    """Clone & checkout the action repo quietly."""
    repo_url = f"https://github.com/{owner}/{repo}.git"
    clone_name = f"{owner}_{repo}_{version}".replace("/", "_").replace("@", "_")
    clone_path = os.path.join(base_dir, clone_name)

    if os.path.exists(clone_path):
        shutil.rmtree(clone_path)

    git_clone_quiet(repo_url, clone_name, cwd=base_dir, output_json=output_json)
    git_fetch_all_quiet(clone_path, output_json=output_json)
    git_fetch_tags_quiet(clone_path, output_json=output_json)

    try:
        git_checkout_quiet(clone_path, version, output_json=output_json)
    except subprocess.CalledProcessError:
        raise RuntimeError(f"Failed to checkout '{version}' in {owner}/{repo}")

    return clone_path


# --------------------------------------------------------------------
# RECURSIVE DISCOVERY
# --------------------------------------------------------------------

def recursively_discover_actions(initial_repo_url: str, base_dir: str, output_json: bool=False):
    """
    1. Clones the initial repo.
    2. Finds external actions from .github/workflows.
    3. For each discovered action, clones & checks out the repo => checks for composite or docker references.

    Returns:
      all_discovered: set of all (owner, repo, version)
      dependencies_graph: dict(parent -> set(children))
      docker_warnings_map: dict(parent -> list(warnings))
    """
    initial_clone_path = os.path.join(base_dir, "initial_repo")
    if os.path.exists(initial_clone_path):
        shutil.rmtree(initial_clone_path)

    msg = f"Cloning initial repository: {initial_repo_url}"
    if output_json:
        eprint(msg)
    else:
        print(msg)

    # clone quietly
    git_clone_quiet(initial_repo_url, "initial_repo", cwd=base_dir, output_json=output_json)

    discovered = get_actions_from_workflows(initial_clone_path)

    to_visit = set(discovered)
    visited = set()
    all_discovered = set(discovered)

    dependencies_graph: Dict[Tuple[str, str, str], Set[Tuple[str, str, str]]] = OrderedDict()
    MAIN_KEY = ("__MAIN_REPO__", "", "")
    dependencies_graph[MAIN_KEY] = set(discovered)

    docker_warnings_map: Dict[Tuple[str, str, str], List[str]] = {}
    docker_warnings_map[MAIN_KEY] = []

    while to_visit:
        owner, repo, version = to_visit.pop()
        if (owner, repo, version) in visited:
            continue
        visited.add((owner, repo, version))

        dependencies_graph.setdefault((owner, repo, version), set())
        docker_warnings_map.setdefault((owner, repo, version), [])

        # attempt to clone & parse action
        try:
            cloned_path = clone_repo(owner, repo, version, base_dir, output_json=output_json)
        except Exception as e:
            wmsg = f"WARNING: Unable to clone/check out {owner}/{repo}@{version}: {e}"
            if output_json:
                eprint(wmsg)
            else:
                print(wmsg)
            continue

        action_file = find_top_level_action_file(cloned_path)
        if not action_file:
            # not a composite or docker-based action => no further references
            continue

        sub_actions, docker_warns = get_actions_and_docker_warnings_from_action_file(action_file)
        if docker_warns:
            docker_warnings_map[(owner, repo, version)].extend(docker_warns)

        for sa in sub_actions:
            dependencies_graph[(owner, repo, version)].add(sa)
            if sa not in all_discovered:
                all_discovered.add(sa)
                to_visit.add(sa)

    return all_discovered, dependencies_graph, docker_warnings_map


# --------------------------------------------------------------------
# OUTPUT LOGIC
# --------------------------------------------------------------------

def key_to_str(k: Tuple[str, str, str]) -> str:
    if k[0] == "__MAIN_REPO__":
        return "Main Repository"
    return f"{k[0]}/{k[1]}@{k[2]}"


def build_json_output(
    all_actions: Set[Tuple[str, str, str]],
    deps_graph: Dict[Tuple[str, str, str], Set[Tuple[str, str, str]]],
    docker_map: Dict[Tuple[str, str, str], List[str]]
):
    """Convert the scanning results into a JSON-compatible dict."""
    deps_json = {}
    for parent, children in deps_graph.items():
        p_str = key_to_str(parent)
        c_list = sorted(key_to_str(ch) for ch in children)
        deps_json[p_str] = c_list

    warns_json = {}
    for parent, warns in docker_map.items():
        p_str = key_to_str(parent)
        warns_json[p_str] = warns[:]

    all_list = sorted(key_to_str(a) for a in all_actions)

    return {
        "dependencies": deps_json,
        "docker_warnings": warns_json,
        "all_actions": all_list
    }


def print_human_readable(
    all_actions: Set[Tuple[str, str, str]],
    deps_graph: Dict[Tuple[str, str, str], Set[Tuple[str, str, str]]],
    docker_map: Dict[Tuple[str, str, str], List[str]]
):
    """Print a text-based summary of the scanning results."""
    print("\n=== Dependency Map ===")
    for parent, children in deps_graph.items():
        print(f"\nDependencies for {key_to_str(parent)}:")
        if not children:
            print("  (No further dependencies)")
        else:
            for ch in sorted(children):
                print(f"  - {key_to_str(ch)}")

    print("\n=== Docker Warnings ===")
    any_warn = False
    for parent, warns in docker_map.items():
        if warns:
            any_warn = True
            print(f"\nDocker warnings for {key_to_str(parent)}:")
            for w in warns:
                print(f"  - {w}")
    if not any_warn:
        print("(No Docker-related warnings)")

    print("\n=== Unique external actions discovered ===")
    sorted_actions = sorted(all_actions, key=lambda x: (x[0], x[1], x[2]))
    for a in sorted_actions:
        print(f"- {a[0]}/{a[1]}@{a[2]}")
    print(f"\nTotal unique external actions found: {len(all_actions)}")


# --------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------

def main():
    """
    Usage:
      python recursive_composite_scanner.py <github_repo_url> [clone_dir] [--json-output]

    Example:
      python recursive_composite_scanner.py https://github.com/myuser/myrepo.git scans --json-output > result.json
    """
    if len(sys.argv) < 2:
        eprint("Usage: python recursive_composite_scanner.py <github_repo_url> [clone_dir] [--json-output]")
        sys.exit(1)

    args = sys.argv[1:]
    github_repo_url = args[0]
    output_json = False
    clone_dir = "repo_scans"

    for arg in args[1:]:
        if arg == "--json-output":
            output_json = True
        else:
            clone_dir = arg

    if not os.path.exists(clone_dir):
        os.makedirs(clone_dir)

    # Recursively discover
    all_actions, deps_graph, docker_map = recursively_discover_actions(github_repo_url, clone_dir, output_json)

    # Output
    if output_json:
        result = build_json_output(all_actions, deps_graph, docker_map)
        print(json.dumps(result, indent=2))  # pure JSON to stdout
    else:
        print_human_readable(all_actions, deps_graph, docker_map)


if __name__ == "__main__":
    main()
