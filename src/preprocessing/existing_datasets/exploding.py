
from pathlib import Path
from tqdm import tqdm
import json
import copy

def explode_dataset():
    base_dir = Path("data/existing_datasets")
    input_dir = base_dir / "4filtering"
    output_dir = base_dir / "5explode"
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process both train and eval directories if they exist
    for split_dir in input_dir.iterdir():
        if not split_dir.is_dir():
            continue
            
        target_split_dir = output_dir / split_dir.name
        target_split_dir.mkdir(parents=True, exist_ok=True)
        
        jsonl_files = list(split_dir.glob("*.jsonl"))
        
        print(f"Processing {len(jsonl_files)} files in {split_dir}")
        
        for jsonl_file in tqdm(jsonl_files, desc=f"Exploding {split_dir.name}"):
            output_file = target_split_dir / jsonl_file.name
            
            with jsonl_file.open("r") as f_in, output_file.open("w") as f_out:
                for line in f_in:
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                        
                    code_metadata = data.get("code_metadata", {})
                    dependency_graph_nested = data.get("dependency_graph_nested", {})
                    original_id = data.get("id", "")
                    
                    for target_name, target_info in code_metadata.items():
                        new_record = copy.deepcopy(data)
                        
                        new_record["target_code_name"] = target_name
                        new_record["target_code"] = target_info.get("code", "")
                        
                        # Get nested dependency for this target
                        new_record["target_code_dependency"] = dependency_graph_nested.get(target_name, {})
                        
                        # Update ID
                        new_record["id"] = f"{original_id}.{target_name}"
                        
                        # Reorder fields
                        ordered_keys = ["id", "target_code", "target_code_dependency", "formal_language", "natural_language"]
                        ordered_record = {}
                        
                        for key in ordered_keys:
                            if key in new_record:
                                ordered_record[key] = new_record[key]
                                
                        for key, value in new_record.items():
                            if key not in ordered_record:
                                ordered_record[key] = value
                        
                        f_out.write(json.dumps(ordered_record) + "\n")

if __name__ == "__main__":
    explode_dataset()
