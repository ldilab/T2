import os
import json
import sqlite3
import glob
from tqdm import tqdm

INPUT_BASE = "data/research_papers/0final.noafter"
OUTPUT_BASE = "data/research_papers/0final.noref"

def replace_with_sorry(code_str):
    if ":=" not in code_str:
        return code_str
        
    stack = []
    found_idx = -1
    
    i = 0
    while i < len(code_str):
        char = code_str[i]
        
        if char in '([{':
            stack.append(char)
        elif char in ')]}':
            if stack:
                if (char == ')' and stack[-1] == '(') or \
                   (char == ']' and stack[-1] == '[') or \
                   (char == '}' and stack[-1] == '{'):
                    stack.pop()
        
        if char == ':' and i+1 < len(code_str) and code_str[i+1] == '=':
            if not stack:
                found_idx = i
                break
            i += 1 
            
        i += 1
        
    if found_idx != -1:
        preamble = code_str[:found_idx]
        return preamble + ":= by sorry"
        
    return code_str

def merge_headers(h1, h2):
    def get_lines(h):
        if not h:
            return set()
        return set(line.strip() for line in h.split('\n') if line.strip())
    
    lines1 = get_lines(h1)
    lines2 = get_lines(h2)
    merged = lines1.union(lines2)
    return '\n'.join(sorted(list(merged)))

def process_single_file(input_path):
    tqdm.write(f"Processing File: {input_path}")
    
    rel_path = os.path.relpath(input_path, INPUT_BASE)
    stem = os.path.basename(input_path).replace('.jsonl', '')
    
    # 1. Build Index specific to this file
    db_path = f"temp_{stem}.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA cache_size = 1000000")
    
    c = conn.cursor()
    c.execute("CREATE TABLE records (id TEXT PRIMARY KEY, json_data TEXT)")
    
    count = 0
    total_lines = 0
    with open(input_path, 'r') as f:
        batch = []
        # Pass 1: Indexing with tqdm
        pbar_idx = tqdm(f, desc=f"  Indexing {stem}", unit="lines")
        for line in pbar_idx:
            total_lines += 1
            try:
                data = json.loads(line)
                rid = data.get('id')
                if rid:
                    batch.append((rid, line))
                    count += 1
                    if len(batch) > 10000:
                        c.executemany("INSERT OR REPLACE INTO records VALUES (?, ?)", batch)
                        batch = []
            except Exception as e:
                tqdm.write(f"Error parsing line in {input_path}: {e}")
        if batch:
            c.executemany("INSERT OR REPLACE INTO records VALUES (?, ?)", batch)
    conn.commit()
    tqdm.write(f"  Indexed {count} records. Total lines: {total_lines}")

    # 2. Process File
    base_out_dir = os.path.join(OUTPUT_BASE, os.path.dirname(rel_path))
    os.makedirs(base_out_dir, exist_ok=True)
    
    out_nosorry = os.path.join(base_out_dir, f"{stem}.nosorry.jsonl")
    out_nosorry_prop = os.path.join(base_out_dir, f"{stem}.nosorry.prop.jsonl")
    out_nosorry_nonprop = os.path.join(base_out_dir, f"{stem}.nosorry.nonprop.jsonl")
    
    out_sorry = os.path.join(base_out_dir, f"{stem}.sorry.jsonl")
    out_sorry_prop = os.path.join(base_out_dir, f"{stem}.sorry.prop.jsonl")
    out_sorry_nonprop = os.path.join(base_out_dir, f"{stem}.sorry.nonprop.jsonl")
    
    f_nosorry = open(out_nosorry, 'w')
    f_nosorry_prop = open(out_nosorry_prop, 'w')
    f_nosorry_nonprop = open(out_nosorry_nonprop, 'w')
    
    f_sorry = open(out_sorry, 'w')
    f_sorry_prop = open(out_sorry_prop, 'w')
    f_sorry_nonprop = open(out_sorry_nonprop, 'w')
    
    handles = {
        'nosorry': f_nosorry,
        'nosorry_prop': f_nosorry_prop,
        'nosorry_nonprop': f_nosorry_nonprop,
        'sorry': f_sorry,
        'sorry_prop': f_sorry_prop,
        'sorry_nonprop': f_sorry_nonprop
    }
    
    def save_record(rec, is_s):
        is_p = rec.get('is_prop', False)
        payload = json.dumps(rec) + "\n"
        
        if not is_s:
            handles['nosorry'].write(payload)
            if is_p:
                handles['nosorry_prop'].write(payload)
            else:
                handles['nosorry_nonprop'].write(payload)
        else:
            handles['sorry'].write(payload)
            if is_p:
                handles['sorry_prop'].write(payload)
            else:
                handles['sorry_nonprop'].write(payload)

    with open(input_path, 'r') as fin:
        # Pass 2: Processing with tqdm and total lines known
        for line in tqdm(fin, total=total_lines, desc=f"  Processing {stem}", unit="lines"):
            try:
                record = json.loads(line)
                referenced = record.get('referenced', [])
                if not isinstance(referenced, list):
                    referenced = []
                
                # 1. Save Original
                save_record(record, False)
                
                rec_orig_sorry = record.copy()
                rec_orig_sorry['target_code'] = replace_with_sorry(record.get('target_code', ''))
                save_record(rec_orig_sorry, True)
                
                # 2. Process Refs
                if not referenced:
                    continue
                
                # Current deps: Set of IDs
                current_deps = set(record.get('target_code_dependency', []))
                current_deps.add(record['id'])
                
                for ref_id in referenced:
                    # Look up in LOCAL db
                    c.execute("SELECT json_data FROM records WHERE id=?", (ref_id,))
                    row = c.fetchone()
                    if not row:
                        continue 
                    
                    ref_record = json.loads(row[0])
                    
                    # Create new record
                    new_record = record.copy()
                    new_record['id'] = f"{record['id']}.after_target_code={ref_id}"
                    
                    # Update Headers
                    new_record['target_code_header'] = record.get('header', '')
                    new_record['after_target_code_header'] = ref_record.get('header', '')
                    new_record['header'] = merge_headers(record.get('header', ''), ref_record.get('header', ''))
                    
                    # Calculate Difference in Context
                    ref_deps_list = ref_record.get('target_code_dependency', [])
                    
                    # Identify items in ref_deps that are NOT in current_deps and NOT the ref_id itself
                    # We maintain the order from ref_deps_list (topological)
                    # Use topological order from ref_deps_list
                    diff_ids = [d for d in ref_deps_list if d not in current_deps and d != ref_id and d != record['id']]
                    
                    context_codes = []
                    for dep_id in diff_ids:
                        c.execute("SELECT json_data FROM records WHERE id=?", (dep_id,))
                        d_row = c.fetchone()
                        if d_row:
                            d_rec = json.loads(d_row[0])
                            if d_rec.get('target_code'):
                                context_codes.append(d_rec['target_code'])
                    
                    unique_context_str = "\n\n".join(context_codes)
                    
                    # after_target_code = Unique Context + Comment + Ref Target Code
                    ref_target_code = ref_record.get('target_code', '')
                    
                    # Note: We do not include headers here as they are merged in 'header' field.
                    parts = []
                    if unique_context_str:
                        parts.append(unique_context_str)
                    
                    comment = f"/-- Target code found in referencing module (Id: {ref_id}) -/"
                    parts.append(comment)
                    parts.append(ref_target_code)
                    
                    new_record['after_target_code'] = "\n\n".join(parts)
                    
                    # Also keep context populated if needed, or set to unique context
                    new_record['after_target_code_context'] = unique_context_str
                    
                    save_record(new_record, False)
                    
                    rec_new_sorry = new_record.copy()
                    rec_new_sorry['target_code'] = replace_with_sorry(new_record.get('target_code', ''))
                    save_record(rec_new_sorry, True)
                    
            except Exception as e:
                tqdm.write(f"Error processing line in {input_path}: {e}")
    
    for h in handles.values():
        h.close()
        
    conn.close()
    if os.path.exists(db_path):
        os.remove(db_path)

def main():
    all_files = []
    for root, dirs, files in os.walk(INPUT_BASE):
        for f in files:
            if f.endswith('.jsonl'):
                all_files.append(os.path.join(root, f))
    
    tqdm.write(f"Found {len(all_files)} files.")
    
    # Move Duper_ITP_Paper_Artifact to the end
    duper_files = [f for f in all_files if "Duper_ITP_Paper_Artifact" in f]
    other_files = [f for f in all_files if "Duper_ITP_Paper_Artifact" not in f]
    # all_files = other_files + duper_files
    all_files = other_files
    
    for f in tqdm(all_files, desc="All Files"):
        process_single_file(f)

if __name__ == "__main__":
    main()
