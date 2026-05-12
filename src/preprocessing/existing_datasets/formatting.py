
from pathlib import Path
from tqdm import tqdm
import json

parsing_map = {
    "MiniF2F_train.jsonl": {
        "informal_prefix": "informal_statement",
        "name": "id"
    },
    "Proofnet_lean4.jsonl": {
        "informal_prefix": "informal_statement",
        "name": "id"
    },
    "combibebch_test.jsonl": {
        "natural_language": "informal_statement",
        "theorem_name": "id"
    },
    "Herald_train.jsonl": {
        "formal_theorem": "formal_statement",
        "informal_theorem": "informal_statement",
    },
    "Kimina_prover_train.jsonl": {
        "natural_language": "informal_statement",
        "statement_id": "id"
    },
    "Numina_train.jsonl": {
        "problem": "informal_statement",
        "formal_ground_truth": "formal_proof",
        "uuid": "id"
    },
    "formalmath.jsonl": {
        "theorem_names": "id",
        "informal_problem": "informal_statement",
        "formal_problem": "formal_statement"
    }

}


if __name__ == "__main__":
    raw_dataset_dir = Path("data/existing_datasets/0raw")
    formatted_dataset_dir = Path("data/existing_datasets/1formatted")
   
    eval_dir = raw_dataset_dir / "eval"
    train_dir = raw_dataset_dir / "train"

    formatted_eval_dir = formatted_dataset_dir / "eval"
    formatted_train_dir = formatted_dataset_dir / "train"

    formatted_eval_dir.mkdir(exist_ok=True, parents=True)
    formatted_train_dir.mkdir(exist_ok=True, parents=True)

    eval_jsonls = list(eval_dir.glob("*.jsonl"))
    train_jsonls = list(train_dir.glob("*.jsonl"))


    for jsonl in tqdm(eval_jsonls + train_jsonls):
        file_name = jsonl.name
        dir_type = jsonl.parent.name
        if file_name not in parsing_map:
            print(f"Skipping {file_name}")
            continue
        
        with (
            jsonl.open("r") as fIn,
            (formatted_dataset_dir / dir_type / file_name).open("w") as fOut
        ):
            for line in fIn:
                data = json.loads(line)
                for key, value in parsing_map[file_name].items():
                    data[value] = data[key]

                if file_name == "formalmath.jsonl":
                    drop_keys = ["refined_statement", "autoformalization", "solution"]
                    for drop_key in drop_keys:
                        data.pop(drop_key)
                    if type(data["informal_proof"]) is list:
                        data["informal_proof"] = data["informal_proof"][0]
                    

                fOut.write(json.dumps(data) + "\n")