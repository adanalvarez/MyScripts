# GitHub Actions Dependency Scanner

Python script that **recursively scans** a GitHub repository’s workflows to uncover unpinned or unpinnable dependencies in your GitHub Actions usage. By cloning each referenced action, it checks for pinned Docker references or further nested dependencies in “composite” actions. You can then generate a shareable HTML report for a clear overview of your entire dependency tree.

> **Note on Security**  
> - This script issues OS-level shell commands (`git clone`, `git checkout`, etc.) to recursively download and analyze repositories.  
> - If scanning **untrusted** or **malicious** repositories, do so in a secure or isolated environment (like a VM or container).  
> - This script does **not** implement advanced sandboxing, it should **not** be considered “secure” on its own.  

## Requirements

- **Python 3.7+**  
- **Git** installed and accessible from the command line  
- **PyYAML** (`pip install PyYAML`)  


## Quick Start

1. **Scan your repo** to produce a JSON summary:
   ```bash
   python recursive_composite_scanner.py https://github.com/myuser/myrepo.git scans --json-output > result.json
   ```
   - Clones your repository into `scans/initial_repo`, locates external `owner/repo@version` references, recursively clones each action, and checks for unpinned Docker images.

2. **Generate an HTML report** from that JSON:
   ```bash
   python generate_html_report.py "MySuperRepo" result.json report.html
   ```
   - Produces `report.html` with a collapsible table view, showing actions, pinned/unpinned status, and a dependency map.

3. **Open `report.html`** in your browser:
   - Quickly see all discovered actions, any unpinned Docker images, and the nesting of composite actions.



## Usage Examples

- **JSON Only** (no HTML):
  ```bash
  python recursive_composite_scanner.py https://github.com/owner/some-repo.git scans --json-output > result.json
  ```
  Inspect `result.json` directly or feed it into other tools.

- **Human-Readable Output** (skipping JSON):
  ```bash
  python recursive_composite_scanner.py https://github.com/owner/some-repo.git scans
  ```
  Prints a text summary to standard output (dependencies, Docker warnings, final action list).
