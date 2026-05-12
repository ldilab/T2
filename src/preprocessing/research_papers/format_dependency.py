import os
import json

SOURCE_DIR = "data/research_papers/3dependency.unformatted/lean4"
TARGET_DIR = "data/research_papers/3dependency/lean4"

def should_keep(path):
    """
    Check if the path represents a local file (True) or a dependency (False).
    We exclude paths starting with .lake/ or lake-packages/, or containing /.lake/.
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
        
        original_metadata_count = len(data.get('code_metadata', {}))
        
        # 1. Identify valid local keys
        # We only keep keys in code_metadata that pass the 'should_keep' filter.
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
        # Key must be valid (internal).
        # Dependencies must be valid (internal).
        if 'dependency_graph' in data:
            new_graph = {}
            for k, deps in data['dependency_graph'].items():
                if k in valid_keys:
                    # Filter the list of dependencies: keep only if the dependency is also a valid local key
                    new_deps = [d for d in deps if d in valid_keys]
                    new_graph[k] = new_deps
            data['dependency_graph'] = new_graph
            
        filtered_metadata_count = len(data.get('code_metadata', {}))
        
        with open(dst_path, 'w') as f:
            json.dump(data, f, indent=2)
            
        print(f"Processed {filename}: {original_metadata_count} -> {filtered_metadata_count} entries")
        
    except Exception as e:
        print(f"Error processing {filename}: {e}")

def main():
    if not os.path.exists(SOURCE_DIR):
        print(f"Source directory not found: {SOURCE_DIR}")
        return

    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)
        print(f"Created target directory: {TARGET_DIR}")
        
    files = [f for f in os.listdir(SOURCE_DIR) if f.endswith(".json")]
    print(f"Found {len(files)} JSON files to process.")
    
    for filename in sorted(files):
        process_file(filename)

if __name__ == "__main__":
    main()
