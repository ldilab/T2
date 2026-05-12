import os
import json
from pathlib import Path
from tqdm import tqdm

SOURCE_ROOT = Path("data/existing_datasets/3dependency")
MAX_DEPTH = 5

def build_nested_graph(current_key, adjacency_map, path, depth):
    if depth >= MAX_DEPTH:
        return {}
        
    nested = {}
    direct_deps = adjacency_map.get(current_key, [])
    
    for dep in direct_deps:
        if dep in path:
            nested[dep] = {} 
        else:
            new_path = path | {dep}
            nested[dep] = build_nested_graph(dep, adjacency_map, new_path, depth + 1)
            
    return nested

def process_file(file_path: Path):
    temp_path = file_path.with_suffix('.tmp')
    
    try:
        with file_path.open('r') as f_in, temp_path.open('w') as f_out:
            # Count lines
            file_in_for_count = open(file_path, 'r')
            total_lines = sum(1 for _ in file_in_for_count)
            file_in_for_count.close()
            
            f_in.seek(0)
            
            for line in tqdm(f_in, total=total_lines, desc=f"Nesting {file_path.name}", leave=False):
                if not line.strip():
                    continue
                
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                adjacency_map = record.get('dependency_graph', {})
                if not adjacency_map:
                    record['dependency_graph_nested'] = {}
                else:
                    nested_graph = {}
                    for key in adjacency_map.keys():
                        nested_graph[key] = build_nested_graph(key, adjacency_map, {key}, 0)
                    record['dependency_graph_nested'] = nested_graph
                
                f_out.write(json.dumps(record) + "\n")
        
        temp_path.replace(file_path)

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        if temp_path.exists():
            temp_path.unlink()

def main():
    if not SOURCE_ROOT.exists():
        print(f"Source directory not found: {SOURCE_ROOT}")
        return

    raw_files = list(SOURCE_ROOT.rglob("*.jsonl"))
    
    for file_path in tqdm(raw_files, desc="Total Files"):
        process_file(file_path)

if __name__ == "__main__":
    main()
