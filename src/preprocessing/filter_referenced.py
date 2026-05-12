import json
import os
import glob
from tqdm import tqdm

def process_directory(source_base, targets, file_filter=None):
    """
    source_base: /path/to/0final.noref
    targets: dict mapping suffix to min_ref_count
             e.g. {'': 1, '.ref1': 1, '.ref2': 2}
             Where '' means output to /path/to/0final
    file_filter: function(filename) -> bool. If provided, skips files where returns False.
    """
    parent_dir = os.path.dirname(source_base)
    dir_name = os.path.basename(source_base)
    
    if not dir_name.endswith(".noref"):
        print(f"Skipping {source_base} because it doesn't end with .noref")
        return {}

    base_output_name = dir_name.replace(".noref", "") # 0final
    
    # Verify outputs
    output_configs = []
    for suffix, min_count in targets.items():
        out_dir = os.path.join(parent_dir, base_output_name + suffix)
        output_configs.append((out_dir, min_count))
    
    all_files = glob.glob(os.path.join(source_base, "**/*.jsonl"), recursive=True)
    
    # Apply filter early
    files_to_process = []
    for f in all_files:
        if file_filter and not file_filter(os.path.basename(f)):
            continue
        files_to_process.append(f)
        
    stats = {} # filename -> {total, ref0, ref1_prop, ref1_noprop, ref2_prop, ref2_noprop}
    
    print(f"Processing {source_base} ({len(files_to_process)}/{len(all_files)} files selected)...")
    
    for fpath in tqdm(files_to_process):
        rel_path = os.path.relpath(fpath, source_base)
        filename = os.path.basename(fpath)
        
        c_total = 0
        c_ref0 = 0
        c_ref1_prop = 0
        c_ref1_noprop = 0
        c_ref2_prop = 0
        c_ref2_noprop = 0
        
        # Open handles for writing
        handles = {}
        for out_dir, _ in output_configs:
            out_fpath = os.path.join(out_dir, rel_path)
            os.makedirs(os.path.dirname(out_fpath), exist_ok=True)
            handles[out_dir] = open(out_fpath, 'w')
            
        try:
            with open(fpath, 'r') as f_in:
                for line in f_in:
                    if not line.strip():
                        continue
                    
                    try:
                        rec = json.loads(line)
                    except:
                        continue
                        
                    c_total += 1
                    ref_len = len(rec.get('referenced', []))
                    if not rec.get('after_target_code'):
                         ref_len = 0
                    is_prop = rec.get('is_prop', False)
                    
                    # Update stats
                    if ref_len == 0:
                        c_ref0 += 1
                    
                    if ref_len >= 1:
                        if is_prop:
                            c_ref1_prop += 1
                        else:
                            c_ref1_noprop += 1
                    
                    if ref_len >= 2:
                        if is_prop:
                            c_ref2_prop += 1
                        else:
                            c_ref2_noprop += 1
                            
                    # Write to appropriate outputs
                    for out_dir, min_count in output_configs:
                        if ref_len >= min_count:
                            # Re-serialize to ensures single line
                            handles[out_dir].write(json.dumps(rec) + "\n")
                            
        finally:
            # Close all handles
            for h in handles.values():
                h.close()

        stats[rel_path] = {
            "total": c_total,
            "ref0": c_ref0,
            "ref1_prop": c_ref1_prop,
            "ref1_noprop": c_ref1_noprop,
            "ref2_prop": c_ref2_prop,
            "ref2_noprop": c_ref2_noprop
        }

    return stats

def main():
    existing_dataset_dir = "data/existing_datasets/0final.noref"
    research_dataset_dir = "data/research_papers/0final.noref"
    
    targets = {
        "": 1,
        ".ref1": 1,
        ".ref2": 2
    }
    
    # Process Existing Datasets
    # Only process *.all.jsonl
    existing_stats = {}
    if os.path.exists(existing_dataset_dir):
        existing_stats = process_directory(
            existing_dataset_dir, 
            targets,
            file_filter=lambda f: f.endswith(".all.jsonl")
        )
    
    # Process Research Papers
    # Only process split files (prop/nonprop) for nosorry/sorry
    # Skip canonical combined files (*.nosorry.jsonl, *.sorry.jsonl)
    def research_filter(f):
        if not (f.endswith(".jsonl")): return False
        # Must be either nosorry or sorry
        is_nosorry = "nosorry" in f
        is_sorry = "sorry" in f
        if not (is_nosorry or is_sorry): return False
        
        # Must be explicitly a split file (.prop or .nonprop)
        is_split = ".prop.jsonl" in f or ".nonprop.jsonl" in f
        return is_split

    research_stats = {}
    if os.path.exists(research_dataset_dir):
        research_stats = process_directory(
            research_dataset_dir, 
            targets,
            file_filter=research_filter
        )

    # Aggregation Logic
    final_aggregates = []

    def aggregate_stats(stats_dict, filter_func, name):
        agg = {
            "total": 0, "ref0": 0,
            "ref1_prop": 0, "ref1_noprop": 0,
            "ref2_prop": 0, "ref2_noprop": 0
        }
        count = 0
        for rel_path, s in stats_dict.items():
            if filter_func(rel_path):
                count += 1
                for key in agg:
                    agg[key] += s[key]
        return {"name": name, "stats": agg, "count": count}

    # 1. Existing Datasets
    final_aggregates.append(aggregate_stats(
        existing_stats, 
        lambda p: p.endswith(".all.jsonl"), 
        "Existing Datasets"
    ))

    # 2. Research Papers (Nosorry)
    final_aggregates.append(aggregate_stats(
        research_stats,
        lambda p: "nosorry" in p and ("prop.jsonl" in p or "nonprop.jsonl" in p),
        "Research Papers (Nosorry)"
    ))

    # 3. Research Papers (Sorry)
    final_aggregates.append(aggregate_stats(
        research_stats,
        lambda p: "sorry" in p and "nosorry" not in p and ("prop.jsonl" in p or "nonprop.jsonl" in p),
        "Research Papers (Sorry)"
    ))
            
    print("\n=== DETAILED SUMMARY ===")
    print(f"{'Dataset':<30} | {'noref':<15} | {'ref >= 1':<30} | {'ref >= 2':<30}")
    print(f"{'':<30} | {'-':<15} | {'prop':<15}{'noprop':<15} | {'prop':<15}{'noprop':<15}")
    print("-" * 140)

    for item in final_aggregates:
        dname = item['name']
        s = item['stats']
        t = s['total']
        
        def fmt(n, total):
            pct = (n / total * 100) if total > 0 else 0
            return f"{n} ({pct:.1f}%)"

        noref_str = fmt(s['ref0'], t)
        r1_p_str = fmt(s['ref1_prop'], t)
        r1_n_str = fmt(s['ref1_noprop'], t)
        r2_p_str = fmt(s['ref2_prop'], t)
        r2_n_str = fmt(s['ref2_noprop'], t)
        
        print(f"{dname:<30} | {noref_str:<15} | {r1_p_str:<15}{r1_n_str:<15} | {r2_p_str:<15}{r2_n_str:<15}")

if __name__ == "__main__":
    main()
