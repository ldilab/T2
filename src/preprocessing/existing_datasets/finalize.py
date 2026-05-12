import json
import os
import glob
from tqdm import tqdm

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
            
    return code.startswith("lemma")

def process_file(input_file, output_path_base):
    # output_path_base e.g. /path/to/0final/eval/Proofnet_lean4.jsonl
    # We want: 
    #   /path/to/0final/eval/Proofnet_lean4.all.jsonl
    #   /path/to/0final/eval/Proofnet_lean4.prop.jsonl
    #   /path/to/0final/eval/Proofnet_lean4.nonprop.jsonl
    
    base_dir = os.path.dirname(output_path_base)
    filename = os.path.basename(output_path_base)
    
    if filename.endswith(".jsonl"):
        stem = filename[:-6]
    else:
        stem = filename
        
    os.makedirs(base_dir, exist_ok=True)
    
    out_all = os.path.join(base_dir, f"{stem}.all.jsonl")
    out_prop = os.path.join(base_dir, f"{stem}.prop.jsonl")
    out_nonprop = os.path.join(base_dir, f"{stem}.nonprop.jsonl")
    
    print(f"Processing {input_file}")
    print(f"  -> {out_all}")
    print(f"  -> {out_prop}")
    print(f"  -> {out_nonprop}")
    
    print(f"Processing {input_file}")
    print(f"  -> {out_all}")
    print(f"  -> {out_prop}")
    print(f"  -> {out_nonprop}")
    
    filtered_count = 0
    total_count = 0
    kept_count = 0
    
    list_all = []
    list_prop = []
    list_nonprop = []

    # 1. Read all records
    raw_records = []
    with open(input_file, 'r') as f:
        lines = f.readlines()
        total_count = len(lines)
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                raw_records.append(record)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON line in {input_file}")
                continue

    # 2. Build reverse dependency map (referenced by)
    # id -> set of ids that depend on it
    referenced_by = {}
    name_to_id = {} # Map short name (key in code_metadata) to full ID

    # First pass: Build name_to_id map
    for r in raw_records:
        r_id = r.get('id')
        if not r_id: continue
        
        # Map the ID itself
        name_to_id[r_id] = r_id
        
        # Map target_code_name -> ID
        # This is the unique identifier for this record within the original file context
        target_name = r.get('target_code_name')
        if target_name:
            name_to_id[target_name] = r_id
    
    # Second pass: Build referenced_by
    for r in raw_records:
        r_id = r.get('id')
        if not r_id: 
            continue
            
        deps = r.get('target_code_dependency', {})
        dep_names = []
        if isinstance(deps, dict):
            dep_names = list(deps.keys())
        elif isinstance(deps, list):
            dep_names = deps
            
        for d_name in dep_names:
            # Resolve d_name to ID
            d_id = name_to_id.get(d_name, d_name)
            
            if d_id not in referenced_by:
                referenced_by[d_id] = set()
            referenced_by[d_id].add(r_id)

    # 3. Process records
    for record in raw_records:
        # (1) Filter: target_code_dependency nested dictionary depth >= 1
        deps = record.get('target_code_dependency', {})
        if not deps or len(deps) == 0:
            filtered_count += 1
            continue
        
        kept_count += 1
        
        # Add referenced field
        my_id = record.get('id')
        if my_id in referenced_by:
            record['referenced'] = sorted(list(referenced_by[my_id]))
        else:
            record['referenced'] = []
        
        # (2) Split formal_language into before/after target_code
        formal_lang = record.get('formal_language', '')
        target_code = record.get('target_code', '')
        
        before_code = ""
        after_code = ""
        
        if target_code and target_code in formal_lang:
            parts = formal_lang.split(target_code)
            before_code = parts[0]
            after_code = target_code.join(parts[1:])
        else:
            # print(f"Warning: target_code not found in formal_language for id {record.get('id')}")
            before_code = ""
            after_code = ""

        # Handle header
        header = record.get('header', '')
        if not header or header.strip() == "":
            header = "import Mathlib"
            record['header'] = header
        
        # Remove header from before_code
        if header:
            h_s = header.strip()
            b_s = before_code.strip()
            
            # Case 1: before_code starts with header (Standard case)
            if b_s.startswith(h_s):
                    # careful with indices since we stripped.
                    # using replace on raw strings is safer if they match exactly
                    if before_code.startswith(header):
                        before_code = before_code[len(header):]
                    else:
                        # try to replace first occurrence
                        before_code = before_code.replace(header, "", 1)
            
            # Case 2: Header contains before_code (Overlap/Redundancy in header)
            # If the header *fully contains* the code that appears before target, 
            # then before_code is redundant.
            elif h_s.startswith(b_s):
                before_code = ""
        
        record['before_target_code'] = before_code
        record['after_target_code'] = after_code
        
        # (3) Update target_code_name and determine is_prop
        target_name_key = record.get('target_code_name', '')
        code_metadata = record.get('code_metadata', {})
        
        is_prop = False # Default
        
        if target_name_key and target_name_key in code_metadata:
            meta = code_metadata[target_name_key]
            # Determine Prop status
            is_prop = meta.get('is_prop', False)
            block_type = meta.get('type', '')

            # Heuristic: if target_code starts with 'lemma', it is a prop and type is lemma
            # Robust check ignoring comments/attributes
            if check_is_lemma(target_code):
                is_prop = True
                if not block_type or block_type == 'unknown':
                    block_type = 'lemma'
            
            # Format: ${block type} ${block name}
            if block_type:
                record['target_code_name'] = f"{block_type} {target_name_key}"
        
        # Reorder fields
        ordered_keys = [
            'id', 
            'target_code', 
            'target_code_dependency',
            'referenced',
            'formal_language', 
            'natural_language', 
            'target_code_name', 
            'before_target_code', 
            'after_target_code'
        ]
        ordered_record = {}
        for k in ordered_keys:
            if k in record:
                ordered_record[k] = record[k]
        
        for k, v in record.items():
            if k not in ordered_keys:
                ordered_record[k] = v

        # Distribute to lists
        list_all.append(ordered_record)
        if is_prop:
            list_prop.append(ordered_record)
        else:
            list_nonprop.append(ordered_record)

    # Write outputs
    def save_jsonl(path, data):
        with open(path, 'w') as f:
            for rec in data:
                f.write(json.dumps(rec) + '\n')

    save_jsonl(out_all, list_all)
    save_jsonl(out_prop, list_prop)
    save_jsonl(out_nonprop, list_nonprop)
            
    return total_count, kept_count, filtered_count, len(list_prop), len(list_nonprop)

def main():
    input_dir = "data/existing_datasets/5explode"
    output_dir = "data/existing_datasets/0final.noref"
    
    # Mirror structure: find all jsonl files recursively
    files = glob.glob(os.path.join(input_dir, "**/*.jsonl"), recursive=True)
    
    total_files_processed = 0
    grand_total_records = 0
    grand_kept_records = 0
    grand_prop = 0
    grand_nonprop = 0
    
    for input_file in files:
        # Determine relative path to maintain structure
        rel_path = os.path.relpath(input_file, input_dir)
        output_file_base = os.path.join(output_dir, rel_path)
        
        t, k, f, n_prop, n_nonprop = process_file(input_file, output_file_base)
        
        grand_total_records += t
        grand_kept_records += k
        grand_prop += n_prop
        grand_nonprop += n_nonprop
        
        if t > 0:
            print(f"  Result for {rel_path}: {t} -> {k} (Filt {f}). Prop: {n_prop}, NonProp: {n_nonprop}")
    
    if grand_total_records > 0:
        filtered_total = grand_total_records - grand_kept_records
        print("\n=== Overall Statistics ===")
        print(f"Total Records: {grand_total_records}")
        print(f"Kept Records: {grand_kept_records}")
        print(f"Filtered (Total): {filtered_total} ({filtered_total/grand_total_records*100:.2f}%)")
        print(f"  - Prop: {grand_prop}")
        print(f"  - NonProp: {grand_nonprop}")

if __name__ == "__main__":
    main()
