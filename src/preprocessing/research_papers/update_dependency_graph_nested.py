import os
import json
from tqdm import tqdm

SOURCE_DIR = "data/research_papers/3dependency.type.graph/lean4"
TARGET_DIR = "data/research_papers/3dependency.type.graph.nested/lean4"
MAX_DEPTH = 5 # Reasonable depth to avoid massive files and infinite loops

def build_nested_graph(current_key, adjacency_map, path, depth):
    """
    Recursively builds a nested dependency dictionary using the adjacency_map.
    path: set of visited keys in the current branch (to detect cycles).
    depth: current recursion depth.
    """
    if depth >= MAX_DEPTH:
        return {} # Stop expanding
        
    nested = {}
    
    # Get direct dependencies from the pre-computed flat graph
    direct_deps = adjacency_map.get(current_key, [])
    
    for dep in direct_deps:
        if dep in path:
            # Cycle detected, explicitly mark with empty dict but don't recurse
            nested[dep] = {} 
        else:
            # Recurse
            # Use frozenset or just a new set? new set copy is safer for recursion
            new_path = path | {dep}
            nested[dep] = build_nested_graph(dep, adjacency_map, new_path, depth + 1)
            
    return nested

def process_file(filename):
    src_path = os.path.join(SOURCE_DIR, filename)
    dst_path = os.path.join(TARGET_DIR, filename)
    
    try:
        with open(src_path, 'r') as f:
            data = json.load(f)
        
        # This is the flat graph we computed earlier
        adjacency_map = data.get('dependency_graph', {})
        if not adjacency_map:
            # If no graph (e.g. empty file), just copy and add empty nested
            data['dependency_graph_nested'] = {}
        else:
            nested_graph = {}
            # Build nested structure for each key
            # Since adjacency_map contains all keys that have dependencies (or empty list)
            # We can iterate over it.
            for key in tqdm(adjacency_map.keys(), desc=f"Nesting {filename}", leave=True):
                nested_graph[key] = build_nested_graph(key, adjacency_map, {key}, 0)
                
            data['dependency_graph_nested'] = nested_graph
        
        with open(dst_path, 'w') as f:
            json.dump(data, f, indent=2)
            
        # print(f"Processed {filename}: Saved nested graph")

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
