import json
import os
import glob
from tqdm import tqdm

IMPORTS_DIR = "data/research_papers/3dependency.imports/lean4"

# Helper to detect if code starts with lemma, ignoring comments/attributes
def check_is_lemma(code):
    if not code:
        return False
        
    while True:
        original = code
        code = code.strip()
        
        # 1. Single line comment --
        if code.startswith("--"):
            end_line = code.find('\n')
            if end_line == -1:
                code = ""
            else:
                code = code[end_line:]
            continue
            
        # 2. Block comment /- ... -/ (Handles nesting)
        if code.startswith("/-"):
            nesting = 1
            i = 2
            while i < len(code) - 1 and nesting > 0:
                if code[i:i+2] == '/-':
                    nesting += 1
                    i += 2
                elif code[i:i+2] == '-/':
                    nesting -= 1
                    i += 2
                else:
                    i += 1
            
            if nesting == 0:
                code = code[i:]
                continue
            else:
                # Malformed or incomplete, assume consumed
                code = ""
                continue

        # 3. Attributes @[...]
        if code.startswith("@["):
            close_idx = code.find(']')
            if close_idx != -1:
                code = code[close_idx+1:]
                continue
        
        # If no change, we are at the start of meaningful code
        if code == original:
            break
            
    return code.startswith("lemma") or code.startswith("theorem")

def load_file_records(filepath):
    records = {}
    with open(filepath, 'r') as f:
        for line in f:
            if not line.strip(): continue
            try:
                rec = json.loads(line)
                rid = rec['id']
                records[rid] = rec
            except Exception as e:
                print(f"Error loading line in {filepath}: {e}")
    return records

def get_dependencies_nested(nested_graph):
    """
    Return a list of dependency IDs in topological order (ancestors first)
    from the nested dependency graph.
    """
    visited = set()
    order = []
    
    def dfs(node_dict):
        # node_dict is {id: {sub_deps}}
        for rid, sub_deps in node_dict.items():
            if rid in visited:
                continue
            
            dfs(sub_deps)
            visited.add(rid)
            order.append(rid)
            
    dfs(nested_graph)
    return order

def get_dependencies(target_id, global_deps):
    """
    Return a list of dependency IDs in topological order (ancestors first).
    """
    visited = set()
    order = []
    
    # We want to find all ancestors.
    # dependency_graph stores: item -> [list of direct dependencies]
    
    def dfs(current_id):
        if current_id in visited:
            return
        visited.add(current_id)
        
        deps = global_deps.get(current_id, [])
        for dep_id in deps:
            dfs(dep_id)
            
        order.append(current_id)
    
    
    direct_deps = global_deps.get(target_id, [])
    for dep in direct_deps:
        dfs(dep)
        
    return order

def merge_headers(h1, h2):
    def get_lines(h):
        if not h:
            return set()
        return set(line.strip() for line in h.split('\n') if line.strip())
    
    lines1 = get_lines(h1)
    lines2 = get_lines(h2)
    merged = lines1.union(lines2)
    return '\n'.join(sorted(list(merged)))

def process_file(input_file):
    input_dir_name = os.path.dirname(input_file)
    base_dir = input_dir_name.replace('5filtering', '0final.noafter')
    os.makedirs(base_dir, exist_ok=True)
    filename = os.path.basename(input_file)
    stem = filename.replace('.jsonl', '').replace('.nosorry', '').replace('.sorry', '').replace('.prop', '').replace('.nonprop', '')
    
    imports_map = {}
    imports_file = os.path.join(IMPORTS_DIR, f"{stem}.json")
    # print(f"DEBUG: Processing {filename}, Stem: {stem}, Imports File: {imports_file}")
    if os.path.exists(imports_file):
        try:
            with open(imports_file, 'r') as f:
                data = json.load(f)
                imports_map = data.get('imports', {})
            # print(f"DEBUG: Loaded {len(imports_map)} imports for {stem}")
        except Exception as e:
            print(f"Error loading imports for {stem}: {e}")
    
    # OUTPUT: Single file per stem
    out_file = os.path.join(base_dir, f"{stem}.jsonl")
    
    records_map = load_file_records(input_file)
    if not records_map:
        return 0, 0, 0
    
    # Build global dependency graph
    global_deps = {}
    for rid, value in records_map.items():
        # record['dependency_graph'] contains local adjacency
        dg = value.get('dependency_graph', {})
        for k, v in dg.items():
            global_deps[k] = v
            
    # Build global referenced (reverse dependency)
    global_referenced = {}
    for src, targets in global_deps.items():
        for tgt in targets:
            if tgt not in global_referenced:
                global_referenced[tgt] = set()
            global_referenced[tgt].add(src)
            
    total_count = len(records_map)
    filtered_count = 0
    list_saved = []

    for rid, rec in records_map.items():
        meta_dict = rec.get('code_metadata', {})
        my_meta = meta_dict.get(rid)
        if not my_meta:
            keys = list(meta_dict.keys())
            if len(keys) == 1:
                my_meta = meta_dict[keys[0]]
            else:
                # Can't find code
                filtered_count += 1
                continue
                
        target_code = my_meta.get('code', '')
        if not target_code:
            filtered_count += 1
            continue
            
        # Get Dependencies
        if 'dependency_graph_nested' in rec:
            deps_ids = get_dependencies_nested(rec['dependency_graph_nested'])
        else:
            deps_ids = get_dependencies(rid, global_deps)

        deps_ids = list(set([d for d in deps_ids if d != rid]))
        
        # Referenced By
        ref_ids = global_referenced.get(rid, [])
        ref_ids = sorted([r for r in ref_ids if r != rid])
        
        # Build Context & Collect Headers
        context_parts = []
        
        seen_imports = set()
        import_lines = []

        def add_header_lines(h_str):
            if not h_str: return
            for line in h_str.split('\n'):
                line = line.strip()
                if not line: continue
                if line not in seen_imports:
                    seen_imports.add(line)
                    import_lines.append(line)

        # 1. Collect dependencies' headers and context
        for dep_id in deps_ids:
            # Header from dependency
            if dep_id in imports_map:
                dep_header = imports_map[dep_id]
            else:
                dep_header = "import Mathlib"
            add_header_lines(dep_header)

            # Context from dependency
            if dep_id in records_map:
                dep_rec = records_map[dep_id]
                dep_meta = dep_rec.get('code_metadata', {}).get(dep_id, {})
                
                if dep_meta and 'code' in dep_meta:
                    context_parts.append(dep_meta['code'])
                    
        context_str = "\n\n".join(context_parts)
        
        # Determine is_prop
        is_prop = my_meta.get('is_prop', False)
        if not is_prop:
            # Double check with heuristic
            is_prop = check_is_lemma(target_code)
            
        # 2. Add own header
        if rid in imports_map:
            original_header = imports_map[rid]
        else:
            original_header = "import Mathlib"
        
        add_header_lines(original_header)

        full_header = "\n".join(import_lines)
        target_code_header = original_header.strip()
        
        # Construct New Record 
        natural_language = rec.get('natural_language', '')
        
        # formal language:
        before_target_code = context_str
        
        # After target code logic is moved to finalize_repo_after.py
        after_target_code = ""

        new_rec = {
            "id": rid,
            "target_code": target_code,
            "target_code_dependency": deps_ids,
            "referenced": ref_ids,
            "formal_language": rec.get('formal_language', ''),
            "natural_language": rec.get('natural_language', ''),
            "target_code_name": rec.get('name', rid),
            "before_target_code": before_target_code,
            "after_target_code": after_target_code,
            "header": full_header,
            "target_code_header": target_code_header, 
            "is_prop": is_prop
        }
        
        # Add other fields
        for k, v in rec.items():
            if k not in new_rec:
                new_rec[k] = v
                
        list_saved.append(new_rec)

    # Save
    with open(out_file, 'w') as f:
        for item in list_saved:
            f.write(json.dumps(item) + "\n")
            
    return total_count, len(list_saved), filtered_count

def main():
    input_dir = "data/research_papers/5filtering/lean4"
    files = glob.glob(os.path.join(input_dir, "**/*.jsonl"), recursive=True)
    
    # We can just check if 'nosorry' or 'sorry' is in the name if filtering is needed,
    # but presumably the input dir 5filtering shouldn't have them yet?
    # Keeping the filter just in case.
    files = [f for f in files if 'nosorry' not in os.path.basename(f) and 'sorry' not in os.path.basename(f)]
    
    print(f"Found {len(files)} files to process.")
    files.sort(key=lambda x: os.path.getsize(x))
    
    grand_total = 0
    grand_saved = 0
    grand_filtered = 0
    
    for fpath in files:
        t, k, f = process_file(fpath)
        grand_total += t
        grand_saved += k
        grand_filtered += f
        
        # filtered_pct = (f / t * 100) if t > 0 else 0
        # print(f"Processed {os.path.basename(fpath)}: {k}/{t} saved")
        
    print("\n=== Overall Statistics ===")
    print(f"Total Records: {grand_total}")
    print(f"Saved Records: {grand_saved}")
    if grand_total > 0:
        filt_pct = (grand_filtered / grand_total) * 100
        print(f"Filtered Out: {grand_filtered} ({filt_pct:.2f}%)")

if __name__ == "__main__":
    main()
