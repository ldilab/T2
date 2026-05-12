
from pathlib import Path
from tqdm import tqdm
import json

"""
| IS | FS | IP | FP | FILE_NAME
-------------------------------
|  O |  O |  X |  X | MiniF2F_train.jsonl
|  O |  O |  X |  X | Proofnet_lean4.jsonl
|  O |  O |  X |  X | combibebch_test.jsonl
|  X |  X |  O |  O | formalmath.jsonl
|  O |  O |  O |  O | Herald_train.jsonl
|  O |  O |  X |  X | Kimina_prover_train.jsonl
|  O |  O |  O |  X | Numina_train.jsonl
"""

def prepend_mathlib(code: str) -> str:
    if "import Mathlib" not in code:
        return "import Mathlib\n\n" + code
    return code

def finish_statement(statement: str) -> str:
    stripped_statement = statement.strip()
    if stripped_statement.endswith("by sorry"):
        return statement
    elif stripped_statement.endswith("by"):
        return statement + " sorry"
    else:
        return statement + " by sorry"

def pair_data(row: dict, file_name: str) -> list[str]:
    """
    pair IS - FS as natural_language - formal_language
    pair IP - FP as natural_language - formal_language
    therefore for herald we can obtain two combinations.
    in this case update id as ${id}_statement, ${id}_proof
    
    if there is header field then prepend on the formal language
    """

    pairs = []
    if file_name == "Herald_train.jsonl":
        _id = row["id"]
        nl = row["informal_statement"]
        fl = finish_statement(row["formal_statement"])
        pairs.append({
            "id": f"{_id}.statement",
            "natural_language": nl,
            "formal_language": fl
        })

        nl = row["informal_proof"]
        fl = row["formal_proof"]
        pairs.append({
            "id": f"{_id}.proof",
            "natural_language": nl,
            "formal_language": fl
        })
    else:
        if file_name in [
            "MiniF2F_train.jsonl", 
            "Proofnet_lean4.jsonl", 
            "combibebch_test.jsonl", 
            "Kimina_prover_train.jsonl", 
            "Numina_train.jsonl", 
            "formalmath.jsonl"
        ]:  
            _id = row["id"]
            nl = row["informal_statement"]
            fl = finish_statement(row["formal_statement"])
        
        pairs.append({
            "id": _id,
            "natural_language": nl,
            "formal_language": fl
        })

    if "header" in row:
        header = row["header"]
        new_pairs = []
        for pair in pairs:
            fl = pair["formal_language"]
            new_fl = f"{header}\n{fl}"
            new_pairs.append({
                "id": pair["id"],
                "natural_language": pair["natural_language"],
                "formal_language": new_fl
            })
        pairs = new_pairs

    for pair in pairs:
        row.update({
            "id": pair["id"],
            "natural_language": pair["natural_language"],
            "formal_language": prepend_mathlib(pair["formal_language"]),
        })

    return row



if __name__ == "__main__":
    formatted_dataset_dir = Path("data/existing_datasets/1formatted")
    paired_dataset_dir = Path("data/existing_datasets/2paired")
    
    formatted_eval_dir = formatted_dataset_dir / "eval"
    formatted_train_dir = formatted_dataset_dir / "train"

    paired_eval_dir = paired_dataset_dir / "eval"
    paired_train_dir = paired_dataset_dir / "train"

    paired_eval_dir.mkdir(exist_ok=True, parents=True)
    paired_train_dir.mkdir(exist_ok=True, parents=True)
    

    eval_jsonls = list(formatted_eval_dir.glob("*.jsonl"))
    train_jsonls = list(formatted_train_dir.glob("*.jsonl"))


    for jsonl in tqdm(eval_jsonls + train_jsonls):
        file_name = jsonl.name
        dir_type = jsonl.parent.name
        
        with (
            jsonl.open("r") as fIn,
            (paired_dataset_dir / dir_type / file_name).open("w") as fOut
        ):
            for line in fIn:
                data = json.loads(line)
                data = pair_data(data, file_name)
                fOut.write(json.dumps(data) + "\n")
                
