import os
import json

# Updated source directory as per user request
SOURCE_DIR = "data/research_papers/1dependency/lean4"
TARGET_DIR = "data/research_papers/3dependency/lean4"

# Specific files to handle
JIXIA_FILES = {
    "Directed-Topology-Lean-4.json",
    "WhitneyGraustein.json",
    "adele-ring_locally-compact.json"
}

def should_keep(path):
    """
    Check if the path represents a local file (True) or a dependency (False).
    We use strict filtering here because the 1dependency files have clean internal paths.
    Any path starting with .lake/ or lake-packages/ is considered external.
    """
    path = path.strip()
    if path.startswith(".lake/") or path.startswith("lake-packages/"):
        return False
    if "/.lake/" in path:
        return False
    return True

def process_file(filename):
    src_path = os.path.join(SOURCE_DIR, filename)
    dst_path = os.path.join(TARGET_DIR, filename)
    
    try:
        with open(src_path, 'r') as f:
            data = json.load(f)
        
        # 1. Identify valid local keys
        # We also need to handle the case where keys might not be paths?
        # In 1dependency, keys looked like "Repo/File.lean/Name". This is good.
        valid_keys = set()
        if 'code_metadata' in data:
            for k in data['code_metadata']:
                if should_keep(k):
                    valid_keys.add(k)
        
        # 2. Filter code_metadata
        if 'code_metadata' in data:
            new_metadata = {
                k: v for k, v in data['code_metadata'].items() 
                if k in valid_keys
            }
            data['code_metadata'] = new_metadata
        
        # 3. Filter dependency_graph
        if 'dependency_graph' in data:
            new_graph = {}
            for k, v in data['dependency_graph'].items():
                if should_keep(k): # Only keep graph entries for internal code
                    # v can be a LIST or a DICT (in Jixia format). 
                    # We normalize to LIST of keys.
                    dependencies = []
                    if isinstance(v, list):
                        dependencies = v
                    elif isinstance(v, dict):
                        dependencies = list(v.keys())
                    
                    # Filter the dependencies
                    # We only keep dependencies that are ALSO internal (in valid_keys)
                    new_deps = [d for d in dependencies if d in valid_keys]
                    new_graph[k] = new_deps
            data['dependency_graph'] = new_graph
            
        filtered_metadata_count = len(data.get('code_metadata', {}))
        
        with open(dst_path, 'w') as f:
            json.dump(data, f, indent=2)
            
        print(f"Processed {filename}: {len(valid_keys)} kept entries (from {src_path})")
        
    except Exception as e:
        print(f"Error processing {filename}: {e}")

def main():
    if not os.path.exists(SOURCE_DIR):
        print(f"Source directory not found: {SOURCE_DIR}")
        return

    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)
        print(f"Created target directory: {TARGET_DIR}")
        
    for filename in sorted(list(JIXIA_FILES)):
        path = os.path.join(SOURCE_DIR, filename)
        if os.path.exists(path):
            process_file(filename)
        else:
            print(f"File not found in source: {filename}")

if __name__ == "__main__":
    main()
