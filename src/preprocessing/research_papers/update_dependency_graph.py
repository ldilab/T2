import os
import json
import re
from tqdm import tqdm

SOURCE_DIR = "data/research_papers/3dependency.type/lean4"
TARGET_DIR = "data/research_papers/3dependency.type.graph/lean4"

def get_short_name(key):
    """
    Extracts the declaration name from the key.
    Example: Repo/Path.lean/Namespace.Name -> Name
    """
    parts = key.split('/')
    if len(parts) > 0:
        return parts[-1]
    return ""

def get_tokens(text):
    """
    Split text into tokens based on non-alphanumeric characters.
    This mimics \b matching for whole words.
    """
    return set(re.split(r'[^a-zA-Z0-9_]+', text))

def process_file(filename):
    src_path = os.path.join(SOURCE_DIR, filename)
    dst_path = os.path.join(TARGET_DIR, filename)
    
    try:
        with open(src_path, 'r') as f:
            data = json.load(f)
        
        code_map = data.get('code_metadata', {})
        if not code_map:
            return

        # 1. Build index of Name -> [Keys]
        name_to_keys = {}
        all_keys = sorted(code_map.keys())
        
        for key in all_keys:
            name = get_short_name(key)
            if name:
                if name not in name_to_keys:
                    name_to_keys[name] = []
                name_to_keys[name].append(key)
        
        # 2. Build dependency graph (Flat)
        dependency_graph = {}
        all_known_names = set(name_to_keys.keys())
        
        for current_key, meta in tqdm(code_map.items(), desc=f"Processing {filename}", leave=False):
            code = meta.get('code', "")
            if not code:
                dependency_graph[current_key] = []
                continue
            
            dependencies = set()
            code_tokens = get_tokens(code)
            potential_matches = code_tokens.intersection(all_known_names)
            
            for name in potential_matches:
                target_keys = name_to_keys[name]
                for target_key in target_keys:
                    if target_key != current_key:
                        dependencies.add(target_key)
            
            dependency_graph[current_key] = sorted(list(dependencies))
            
        data['dependency_graph'] = dependency_graph
        
        with open(dst_path, 'w') as f:
            json.dump(data, f, indent=2)

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
    
    for filename in tqdm(sorted(files), desc="Total Files"):
        process_file(filename)

if __name__ == "__main__":
    main()
