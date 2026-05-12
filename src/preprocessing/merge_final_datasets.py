import json
import os
import glob
from tqdm import tqdm

def get_dataset_name(filename):
    parts = filename.split('.')
    return parts[0]

def merge_files(source_dir, pattern, output_path, dataset_type="existing"):
    """
    source_dir: Directory containing jsonl files
    pattern: Glob pattern relative to source_dir (e.g. "**/*.prop.jsonl")
    output_path: Final merged output path
    dataset_type: "existing" or "repo" (to handle specific filtering logic if needed)
    """
    print(f"Merging {pattern} from {source_dir} to {output_path}...")
    
    files = glob.glob(os.path.join(source_dir, pattern), recursive=True)
    

    final_files = []
    for f in files:
        fname = os.path.basename(f)
        
        if dataset_type == "repo":
            is_all = "all.jsonl" in output_path
            
            if is_all:
                if "prop.jsonl" in fname or "nonprop.jsonl" in fname:
                    continue
            
        elif dataset_type == "existing":
            pass
            
        final_files.append(f)
        
    print(f"Found {len(final_files)} files matching criteria.")
    
    total_written = 0
    with open(output_path, 'w') as out_f:
        for fpath in tqdm(final_files):
            dname = get_dataset_name(os.path.basename(fpath))
            
            with open(fpath, 'r') as in_f:
                for line in in_f:
                    if not line.strip(): continue
                    try:
                        rec = json.loads(line)
                        rec['dataset_name'] = dname
                        out_f.write(json.dumps(rec) + "\n")
                        total_written += 1
                    except:
                        pass
    
    print(f"Written {total_written} records to {output_path}.\n")

def main():
    base_out = "data/final_raw"
    
    # 1. Existing Datasets
    existing_src = "data/existing_datasets/0final.ref1"
    
    # Patterns for existing
    # Prop
    merge_files(existing_src, "**/*.prop.jsonl", os.path.join(base_out, "existing_datasets.prop.jsonl"), "existing")
    # NonProp
    merge_files(existing_src, "**/*.nonprop.jsonl", os.path.join(base_out, "existing_datasets.noprop.jsonl"), "existing")
    # All
    merge_files(existing_src, "**/*.all.jsonl", os.path.join(base_out, "existing_datasets.all.jsonl"), "existing")
    
    # 2. Research Papers (Repo)
    repo_src = "data/research_papers/0final.ref1"
    
    # Patterns for repo
    
    # Nosorry
    merge_files(repo_src, "**/*.nosorry.prop.jsonl", os.path.join(base_out, "research_papers.nosorry.prop.jsonl"), "repo")
    merge_files(repo_src, "**/*.nosorry.nonprop.jsonl", os.path.join(base_out, "research_papers.nosorry.noprop.jsonl"), "repo")
    merge_files(repo_src, "**/*.nosorry.jsonl", os.path.join(base_out, "research_papers.nosorry.all.jsonl"), "repo")
    
    # Sorry
    merge_files(repo_src, "**/*.sorry.prop.jsonl", os.path.join(base_out, "research_papers.sorry.prop.jsonl"), "repo")
    merge_files(repo_src, "**/*.sorry.nonprop.jsonl", os.path.join(base_out, "research_papers.sorry.noprop.jsonl"), "repo")
    merge_files(repo_src, "**/*.sorry.jsonl", os.path.join(base_out, "research_papers.sorry.all.jsonl"), "repo")

if __name__ == "__main__":
    main()
