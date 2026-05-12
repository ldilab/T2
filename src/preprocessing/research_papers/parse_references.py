import os
import re
import json
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "data/research_papers/0raw/lean4"
INPUT_DIR = PROJECT_ROOT / "data/research_papers/3dependency.type.graph.nested/lean4"
OUTPUT_DIR = PROJECT_ROOT / "data/research_papers/3dependency.imports/lean4"

def get_lean_files(repo_path: Path) -> List[Path]:
    """Recursively find all .lean files in the repository."""
    return list(repo_path.rglob("*.lean"))

def derive_module_name(file_path: Path, repo_root: Path) -> str:
    """
    Derive the Lean module name from the file path relative to the repo root.
    Example: repo/Mathlib/Algebra/Group.lean -> Mathlib.Algebra.Group
    """
    rel_path = file_path.relative_to(repo_root)
    # Remove .lean extension
    rel_path_no_ext = rel_path.with_suffix("")
    # Convert path separators to dots
    parts = list(rel_path_no_ext.parts)
    return ".".join(parts)

def parse_imports(file_path: Path) -> List[str]:
    """
    Extract imported module names from a Lean file.
    Matches lines starting with 'import '.
    """
    imports = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("import "):
                    content = line[len("import "):].split("--")[0].strip()

                    extracted = content.split()
                    imports.extend(extracted)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return imports

def process_repo(repo_dir: Path):
    repo_name = repo_dir.name
    print(f"Processing repository: {repo_name}")
    
    # 1. Identify Target Files from Input JSON
    input_file = INPUT_DIR / f"{repo_name}.json"
    if not input_file.exists():
        print(f"Skipping {repo_name}: Input JSON not found at {input_file}")
        return

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            input_data = json.load(f)
    except Exception as e:
         print(f"Error loading input JSON {input_file}: {e}")
         return
    
    graph = input_data.get("dependency_graph", {})
    assert graph, f"No dependency graph found for {repo_name}"

    imports = defaultdict(list)
    for key in graph.keys():
        # RepoName/Path/To/File.lean/Declaration
        file_path = key.split(".lean/")[0] + ".lean"
        target_file_path = repo_dir / file_path
        if not target_file_path.exists():
            print(f"Skipping {repo_name}: Target file not found at {target_file_path}")
            continue
            
        # read target file
        target_file_imports = parse_imports(target_file_path)
        imp_files = defaultdict(list)
        for imp in target_file_imports:
            imp_files["/".join(imp.split(".")[:-1])].append(imp)

        for imp_file in imp_files:
            for graph_key in graph.keys():
                if imp_file in graph_key:
                    break
            else:
                imports[key].extend(imp_files[imp_file])
                break
        else:
            imports[key] = []
                
    imports_header = {
        k: "\n".join([f"import {v}" for v in vs]) 
        for k, vs in imports.items()
    }
    
    
    # 4. Output
    output_data = {
        "repository_name": repo_name,
        "imports": imports_header,
        "code_metadata": {} 
    }
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{repo_name}.json"
    
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    print(f"Saved dependency graph to {output_file}")

def main():
    if not RAW_DATA_DIR.exists():
        print(f"Raw data directory not found: {RAW_DATA_DIR}")
        return

    # Process each repository in raw folder
    for repo_dir in RAW_DATA_DIR.iterdir():
        if repo_dir.is_dir():
            process_repo(repo_dir)

if __name__ == "__main__":
    main()
