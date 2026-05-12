
from pathlib import Path
from tqdm import tqdm
import json

def get_max_tree_depth(tree: dict):
    """
    recursively get the max depth of the tree
    """
    if not tree:
        return 0
    return 1 + max(get_max_tree_depth(child) for child in tree.values())

def is_deep_proof(data):
    """
    Filter records that has dependency depth >= 2
    """
    # depth = get_max_tree_depth(data["dependency_graph_nested"])
    # if depth < 2:
    #     return False
    return True
    
if __name__ == "__main__":
    paired_dataset_dir = Path("data/existing_datasets/3dependency")
    filtering_dataset_dir = Path("data/existing_datasets/4filtering")
    
    paired_eval_dir = paired_dataset_dir / "eval"
    paired_train_dir = paired_dataset_dir / "train"

    filtering_eval_dir = filtering_dataset_dir / "eval"
    filtering_train_dir = filtering_dataset_dir / "train"

    filtering_eval_dir.mkdir(exist_ok=True, parents=True)
    filtering_train_dir.mkdir(exist_ok=True, parents=True)    

    eval_jsonls = list(paired_eval_dir.glob("*.jsonl"))
    train_jsonls = list(paired_train_dir.glob("*.jsonl"))

    
    for jsonl in tqdm(eval_jsonls + train_jsonls):
        count_deep = 0
        file_name = jsonl.name
        dir_type = jsonl.parent.name
        
        with (
            jsonl.open("r") as fIn,
            (filtering_dataset_dir / dir_type / file_name).open("w") as fOut
        ):
            for line in fIn:
                data = json.loads(line)
                is_deep = is_deep_proof(data)
                if not is_deep:
                    continue
                fOut.write(json.dumps(data) + "\n")
                count_deep += 1

        print(f"Count deep proof: {count_deep} for {file_name}")
                
