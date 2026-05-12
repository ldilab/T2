import os
import json
import re
from pathlib import Path
from tqdm import tqdm

SOURCE_ROOT = Path("data/existing_datasets/3dependency")

def get_short_name(key):
    """
    Extracts the declaration name from the key.
    """
    # Keys in existing datasets might be fully qualified or paths
    parts = key.split('/')
    if len(parts) > 0:
        return parts[-1]
    return ""

def get_tokens(text):
    """
    Split text into tokens based on non-alphanumeric characters.
    """
    return set(re.split(r'[^a-zA-Z0-9_]+', text))

def process_file(file_path: Path):
    temp_path = file_path.with_suffix('.tmp')
    
    try:
        updated_lines = []
        with file_path.open('r') as f_in, temp_path.open('w') as f_out:
             # Count lines for tqdm
            file_in_for_count = open(file_path, 'r')
            total_lines = sum(1 for _ in file_in_for_count)
            file_in_for_count.close()

            # reset read
            f_in.seek(0)
            
            for line in tqdm(f_in, total=total_lines, desc=f"Processing {file_path.name}", leave=False):
                if not line.strip():
                    continue
                    
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                code_map = record.get('code_metadata', {})
                if not code_map:
                    f_out.write(json.dumps(record) + "\n")
                    continue

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
                
                for current_key, meta in code_map.items():
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
                
                record['dependency_graph'] = dependency_graph
                f_out.write(json.dumps(record) + "\n")
        
        # Replace original with new
        temp_path.replace(file_path)

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        if temp_path.exists():
            temp_path.unlink()

def main():
    if not SOURCE_ROOT.exists():
        print(f"Source directory not found: {SOURCE_ROOT}")
        return

    # Process both train and eval directories
    raw_files = list(SOURCE_ROOT.rglob("*.jsonl"))
    print(f"Found {len(raw_files)} JSONL files.")
    
    for file_path in tqdm(raw_files, desc="Total Files"):
        process_file(file_path)

if __name__ == "__main__":
    main()
