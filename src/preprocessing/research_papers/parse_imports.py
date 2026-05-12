import os
import json
import re

# Logic:
# 1. Iterate over each subdirectory (repository) in the input directory.
# 2. Recursively find all `.lean` files.
# 3. Read each file and use regex `^import\s+([^\s]+)` to extract imports.
# 4. Store in a dictionary data structure.
# 5. Save as `${repo_name}.json` in the output directory.

INPUT_DIR = "data/research_papers/0raw/lean4"
OUTPUT_DIR = "data/research_papers/1dependency/lean4"

def get_lean_files(repo_path):
    lean_files = []
    for root, dirs, files in os.walk(repo_path):
        for file in files:
            if file.endswith(".lean"):
                lean_files.append(os.path.join(root, file))
    return lean_files

def parse_imports(file_path):
    imports = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Match strict import at the beginning of the line
                match = re.search(r'^import\s+([^\s]+)', line.strip())
                if match:
                    imports.append(match.group(1))
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return imports

def process_repo(repo_dir: Path):
    repo_name = repo_dir.name
    print(f"Processing repository: {repo_name}")
    
    lean_files = get_lean_files(repo_dir)
    
    # 1. Indexing: Map Module Name -> Relative File Path
    # We need to know which modules belong to THIS repository.
    # Note: Lean 4 packages usually have a root directory (e.g., Matchlib/...).
    # We might need to handle the source root (e.g. 'src', 'Mathlib', etc.)
    # For simplicity, we try strictly relative first. if 'Mathlib/Algebra.lean' exists, module is 'Mathlib.Algebra'.
    
    module_to_path: Dict[str, str] = {}
    
    for p in lean_files:
        module_name = derive_module_name(p, repo_dir)
        rel_path = str(p.relative_to(repo_dir))
        module_to_path[module_name] = rel_path
        
    # 2. Parsing: Build Dependency Graph
    dependency_graph: Dict[str, List[str]] = {}
    
    for p in lean_files:
        rel_path = str(p.relative_to(repo_dir))
        imported_modules = parse_imports(p)
        
        internal_dependencies = []
        for mod in imported_modules:
            if mod in module_to_path:
                internal_dependencies.append(module_to_path[mod])
            else:
                pass 
                # External dependency (e.g. Init, Std, or another package not in this repo)
        
        dependency_graph[rel_path] = internal_dependencies
        
    # 3. Output
    output_data = {
        "repository_name": repo_name,
        "dependency_graph": dependency_graph,
        "code_metadata": {} # Leaving empty as user only asked for graph parsing
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
