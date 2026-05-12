
from pathlib import Path
from tqdm import tqdm
import json

def convert_to_problem():
    # Input directory containing the nested dependency graph JSON files
    # Note: user provided path data/research_papers/3dependency.type.graph.nested
    # but based on `ls` output, there is a `lean4` subdirectory.
    # The user request mentioned the file directly, but previous context implies `lean4` subfolder usage.
    # The `ls` showed the JSON files are inside `lean4`.
    base_dir = Path("data/research_papers")
    input_dir = base_dir / "3dependency.type.graph.nested/lean4"
    output_dir = base_dir / "4problems/lean4"
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get all json files
    json_files = list(input_dir.glob("*.json"))
    
    print(f"Found {len(json_files)} files to process in {input_dir}")
    
    for json_file in tqdm(json_files, desc="Processing files"):
        repo_name = json_file.stem
        # Output file name: {repo_name}.jsonl
        output_file = output_dir / f"{repo_name}.jsonl"
        
        with json_file.open("r") as f_in, output_file.open("w") as f_out:
            try:
                data = json.load(f_in)
            except json.JSONDecodeError as e:
                print(f"Error decoding {json_file}: {e}")
                continue
            
            # Extract common fields if they exist at top level (heuristic)
            # Actually, per sample, top level has "code_metadata", "dependency_graph", etc.
            # We iterate over code_metadata items.
            
            code_metadata = data.get("code_metadata", {})
            dependency_graph = data.get("dependency_graph", {})
            dependency_graph_nested = data.get("dependency_graph_nested", {})
            extraction_status = data.get("extraction_status", "")
            
            # We iterate over keys in code_metadata (which seem to be unique identifiers)
            for key, meta in code_metadata.items():
                # meta has "type", "is_prop", "code"
                
                # Construct the problem entry
                # Fields based on MiniF2F_train.jsonl example:
                # "name", "split", "informal_prefix", "formal_statement", "goal", 
                # "header", "informal_statement", "id", "natural_language", "formal_language",
                # "code_metadata", "dependency_graph", "extraction_status", "dependency_graph_nested"
                
                # We fill available info, empty for others.
                
                entry = {
                    "name": key,
                    "split": "", # Unknown
                    "informal_prefix": "",
                    "formal_statement": meta.get("code", ""),
                    "goal": "",
                    "header": "",
                    "informal_statement": "",
                    "id": key,
                    "natural_language": "",
                    "formal_language": meta.get("code", ""), # distinct from statement? in example they are slightly different (imports vs theorem), but here we only have the code snippet. using code for now.
                    
                    # Complex objects specific to this key
                    "code_metadata": {
                        key: meta
                    },
                    "dependency_graph": {
                        key: dependency_graph.get(key, [])
                    },
                    "extraction_status": extraction_status,
                    "dependency_graph_nested": {
                        key: dependency_graph_nested.get(key, {})
                    }
                }
                
                f_out.write(json.dumps(entry) + "\n")

if __name__ == "__main__":
    convert_to_problem()
