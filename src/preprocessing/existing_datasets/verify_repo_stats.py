import json
import os
import glob
from tqdm import tqdm

def count_stats(input_dir):
    files = glob.glob(os.path.join(input_dir, "**/*.jsonl"), recursive=True)
    # Filter only original files (not .nosorry or .sorry)
    input_files = [f for f in files if not f.endswith('.nosorry.jsonl') and not f.endswith('.sorry.jsonl')]
    
    grand_total = 0
    grand_kept = 0
    grand_prop = 0
    
    print(f"{'Filename':<40} | {'Total':<8} | {'Kept':<8} | {'% Filt':<6} | {'Prop':<6} | {'NonProp':<8} | {'F.Prop':<8} | {'F.NonP':<8}")
    print("-" * 120)
    
    for in_f in input_files:
        params_f = in_f.replace('5filtering', '0final').replace('.jsonl', '.nosorry.jsonl')
        
        # Count input
        try:
            with open(in_f, 'r') as f:
                total = sum(1 for _ in f)
        except Exception:
            total = 0
            
        # Count output
        kept = 0
        prop = 0
        if os.path.exists(params_f):
            with open(params_f, 'r') as f:
                for line in f:
                    kept += 1
                    try:
                        rec = json.loads(line)
                        if rec.get('is_prop'):
                            prop += 1
                    except:
                        pass
        
        filtered = total - kept
        filt_pct = (filtered / total * 100) if total > 0 else 0
        non_prop = kept - prop
        
        grand_total += total
        grand_kept += kept
        grand_prop += prop
        
        # Count prop/nonprop if they exist
        prop_f = params_f.replace('.nosorry.jsonl', '.nosorry.prop.jsonl')
        nonprop_f = params_f.replace('.nosorry.jsonl', '.nosorry.nonprop.jsonl')
        
        prop_file_count = 0
        if os.path.exists(prop_f):
             with open(prop_f, 'r') as f:
                 prop_file_count = sum(1 for _ in f)
                 
        nonprop_file_count = 0
        if os.path.exists(nonprop_f):
             with open(nonprop_f, 'r') as f:
                 nonprop_file_count = sum(1 for _ in f)
        
        filename = os.path.basename(in_f)
        print(f"{filename[:40]:<40} | {total:<8} | {kept:<8} | {filt_pct:6.1f}% | {prop:<6} | {non_prop:<8} | {prop_file_count:<8} | {nonprop_file_count:<8}")
        
    print("-" * 120)
    grand_filtered = grand_total - grand_kept
    grand_filt_pct = (grand_filtered / grand_total * 100) if grand_total > 0 else 0
    grand_nonprop = grand_kept - grand_prop
    
    print(f"{'TOTAL':<50} | {grand_total:<10} | {grand_kept:<10} | {grand_filtered:<10} | {grand_filt_pct:6.2f}% | {grand_prop:<8} | {grand_nonprop:<8}")

if __name__ == "__main__":
    count_stats("data/research_papers/5filtering/lean4")
