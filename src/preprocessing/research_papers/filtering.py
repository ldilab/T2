
from pathlib import Path
from tqdm import tqdm
import json
import sys

# Increase recursion depth for deep dependency trees
sys.setrecursionlimit(20000)

def get_max_tree_depth(tree: dict):
    """
    recursively get the max depth of the tree
    """
    if not tree:
        return 0
    # In case the values are not dicts (leaf nodes might be None or empty dict), handle gracefully if needed.
    # Based on previous context, they are dicts.
    depths = [get_max_tree_depth(child) for child in tree.values()]
    if not depths:
        return 1
    return 1 + max(depths)

def is_deep_proof(data):
    """
    Filter records that has dependency depth >= 2
    """
    # Use nested graph as requested by user
    graph = data.get("dependency_graph_nested", {})
    depth = get_max_tree_depth(graph)
    if depth < 2:
        return False
    return True
    
if __name__ == "__main__":
    paired_dataset_dir = Path("data/research_papers/4problems/lean4")
    filtering_dataset_dir = Path("data/research_papers/5filtering/lean4")
    
    filtering_dataset_dir.mkdir(exist_ok=True, parents=True)
    
    # Process all jsonl files in the flat directory
    jsonl_files = list(paired_dataset_dir.glob("*.jsonl"))
    
    print(f"Found {len(jsonl_files)} files in {paired_dataset_dir}")
    
    for jsonl in tqdm(jsonl_files):
        count_deep = 0
        file_name = jsonl.name
        
        output_file = filtering_dataset_dir / file_name
        
        with jsonl.open("r") as fIn, output_file.open("w") as fOut:
            for line in fIn:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                    
                is_deep = is_deep_proof(data)
                if not is_deep:
                    continue
                fOut.write(json.dumps(data) + "\n")
                count_deep += 1

        print(f"Count deep proof: {count_deep} for {file_name}")
