import json
import sys
import os
from tqdm import tqdm

from pathlib import Path

FIELDS_TO_KEEP = [
    "id",
    "target_code",
    "formal_language",
    "natural_language",
    "target_code_name",
    "before_target_code",
    "after_target_code",
    "header",
    "dataset_name"
]

def process_file(input_path, output_path):
    print(f"Processing {input_path} -> {output_path}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(input_path, 'r') as f_in, open(output_path, 'w') as f_out:
        for line in tqdm(f_in):
            if not line.strip():
                continue
            data = json.loads(line)
            new_data = {k: data.get(k) for k in FIELDS_TO_KEEP if k in data}
            f_out.write(json.dumps(new_data) + "\n")

if __name__ == "__main__":
    # if len(sys.argv) < 3:
    #     print("Usage: python extract_final_fields.py <input_file> <output_file>")
    #     sys.exit(1)
    
    # input_file = sys.argv[1]
    # output_file = sys.argv[2]
    # process_file(input_file, output_file)

    PROJECT_DIR = Path(".")
    INPUT_DIR = PROJECT_DIR / "data/final_raw"
    OUTPUT_DIR = PROJECT_DIR / "data/final"

    input_jsonl_files = list(INPUT_DIR.rglob("*.jsonl"))
    for input_file in tqdm(input_jsonl_files):
        output_file = OUTPUT_DIR / input_file.name
        process_file(input_file, output_file)
