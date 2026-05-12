import os
import re
import json
import traceback
from datasets import load_dataset, get_dataset_config_names
import pandas as pd

MARKDOWN_PATH = 'data/existing_datasets/datasets.md'
BASE_PATH = 'data/existing_datasets/0raw'
EVAL_DIR = os.path.join(BASE_PATH, 'eval')
TRAIN_DIR = os.path.join(BASE_PATH, 'train')

os.makedirs(EVAL_DIR, exist_ok=True)
os.makedirs(TRAIN_DIR, exist_ok=True)

def parse_markdown_table(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find table start
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('|'):
            start_idx = i
            break
            
    # Extract headers
    headers = [c.strip() for c in lines[start_idx].split('|') if c.strip()]
    
    data = []
    for line in lines[start_idx+2:]: # Skip header and separator
        if not line.strip().startswith('|'):
            continue
        cols = [c.strip() for c in line.split('|')[1:-1]] # Remove first/last empty from split result of "| ... |"
        if len(cols) != len(headers):
            # Try to handle cases where split might be off, but for now just skip or warn
            # The table seems well formatted
            continue
        row = dict(zip(headers, cols))
        data.append(row)
    return data

def extract_links(cell_content):
    # Matches [text](url)
    matches = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', cell_content)
    # Return list of (text, url)
    return matches

def get_hf_dataset_name(url):
    # e.g. https://huggingface.co/datasets/lanzhang128/Definition-Autoformalization/viewer/...
    if 'huggingface.co' not in url:
        return None
    
    # Remove query params
    url = url.split('?')[0]
    
    # Extract "user/repo"
    # parts: [..., huggingface.co, datasets, user, repo, ...]
    parts = url.split('/')
    try:
        if 'datasets' in parts:
            idx = parts.index('datasets')
            if len(parts) > idx + 2:
                return f"{parts[idx+1]}/{parts[idx+2]}"
        # Allow linking directly to repo root without 'datasets' in path if odd (less likely for HF)
        # But normal HF URLs are huggingface.co/datasets/USER/REPO
    except ValueError:
        pass
    return None

def download_and_save(dataset_name, hf_repo_id, target_dir):
    print(f"Processing {dataset_name} from {hf_repo_id}...")
    
    try:
        # Try to load dataset
        # Handle configs if necessary. For now try default.
        try:
            configs = get_dataset_config_names(hf_repo_id, trust_remote_code=True)
            config = configs[0] if configs else None
        except:
            config = None

        ds = load_dataset(hf_repo_id, config, trust_remote_code=True)
        
        # Save each split
        for split_name, dataset in ds.items():
            out_filename = f"{dataset_name.replace(' ', '_')}_{split_name}.jsonl"
            out_path = os.path.join(target_dir, out_filename)
            
            print(f"  Saving split '{split_name}' to {out_path}...")
            dataset.to_json(out_path, orient='records', lines=True, force_ascii=False)
            
    except Exception as e:
        print(f"FAILED to download {dataset_name} ({hf_repo_id}): {e}")
        traceback.print_exc()

def main():
    rows = parse_markdown_table(MARKDOWN_PATH)
    
    for row in rows:
        dataset_name = row.get('Dataset')
        data_link_cell = row.get('data 링크', '')
        usage = row.get('용도', '')
        
        # Clean checks
        if not dataset_name or 'x' in dataset_name.lower(): 
             # Wait, "x" might be just a marker in other columns. Dataset name "Ours" is valid.
             pass

        if not data_link_cell or data_link_cell.strip() in ['x', '-']:
            continue
            
        links = extract_links(data_link_cell)
        if not links:
            continue
            
        # Determine target directory
        target_dir = None
        if '평가' in usage:
            target_dir = EVAL_DIR
        elif '학습' in usage:
            target_dir = TRAIN_DIR
        
        if not target_dir:
            print(f"Skipping {dataset_name}: Unknown usage '{usage}'")
            continue

        print(f"Dataset: {dataset_name}, Usage: {usage} -> {target_dir}")
        
        for i, (link_text, url) in enumerate(links):
            hf_repo = get_hf_dataset_name(url)
            if hf_repo:
                name_suffix = f"_{i+1}" if len(links) > 1 else ""
                current_dataset_name = f"{dataset_name}{name_suffix}"
                
                download_and_save(current_dataset_name, hf_repo, target_dir)
            else:
                print(f"Skipping non-HF link for {dataset_name}: {url}")

if __name__ == "__main__":
    main()
