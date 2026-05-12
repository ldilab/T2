
import sys
import logging
import json
import os
from pathlib import Path
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

# Add project root to sys.path to import src.utils
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.utils.dependency_extractor import DependencyExtractor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Use mathlib4 as the context (verified compatible with Jixia v4.24.0)
# Make sure to use absolute path
CONTEXT_PATH = PROJECT_ROOT.parent / "data/existing_datasets/tmp"
extractor = DependencyExtractor()

def extract_dependency(data):
    code = data.get("formal_language", "")
    if len(code) == 0:
        assert len(code) > 0, "formal_language is empty"

    try:
        # Use simple string extraction
        # We use the built adele-ring repo as context for imports
        code_map, dep_tree = extractor.extract_from_string(code, str(CONTEXT_PATH))
        
        data["code_metadata"] = code_map
        data["dependency_graph"] = dep_tree
        data["extraction_status"] = "success"
        
    except Exception as e:
        logger.warning(f"Extraction failed for {data.get('id', 'unknown')}: {e}")
        data["extraction_status"] = f"failed: {str(e)}"
        data["code_metadata"] = {}
        data["dependency_graph"] = {}
        
    return data

def process_record_wrapper(line):
    try:
        data = json.loads(line)
        return extract_dependency(data)
    except Exception as e:
        logger.error(f"Failed to process line: {e}")
        # Return failing data structure or just raw if load failed
        try:
             d = json.loads(line)
             d["extraction_status"] = f"failed_wrapper: {str(e)}"
             return d
        except:
             return {"extraction_status": "json_error"}

if __name__ == "__main__":
    FORCE_REPROCESS = True

    
    paired_dataset_dir = PROJECT_ROOT / "data/existing_datasets/2paired"
    dependency_dataset_dir = PROJECT_ROOT / "data/existing_datasets/3dependency"
    
    paired_eval_dir = paired_dataset_dir / "eval"
    paired_train_dir = paired_dataset_dir / "train"

    dependency_eval_dir = dependency_dataset_dir / "eval"
    dependency_train_dir = dependency_dataset_dir / "train"

    dependency_eval_dir.mkdir(exist_ok=True, parents=True)
    dependency_train_dir.mkdir(exist_ok=True, parents=True)    

    eval_jsonls = list(paired_eval_dir.glob("*.jsonl"))
    train_jsonls = list(paired_train_dir.glob("*.jsonl"))

    # Determine CPU count for workers
    num_workers = min(multiprocessing.cpu_count(), 32) # Cap at 32 or usage might be too high if many cores
    print(f"Using {num_workers} parallel workers.")

    for jsonl in tqdm(eval_jsonls + train_jsonls, desc="Processing datasets"):
        file_name = jsonl.name
        dir_type = jsonl.parent.name
        
        output_path = dependency_dataset_dir / dir_type / file_name
        
        if not FORCE_REPROCESS and output_path.exists():
            logger.info(f"Skipping {jsonl} -> {output_path}")
            continue
        
        logger.info(f"Processing {jsonl} -> {output_path}")
        
        if not jsonl.exists():
            continue
            
        # Count lines first for tqdm (fast and low memory)
        try:
             with jsonl.open("rb") as f:
                 total_lines = sum(1 for _ in f)
        except Exception as e:
             logger.warning(f"Failed to count lines for {jsonl}: {e}")
             total_lines = None

        if total_lines == 0:
            continue

        # Check if output exists and is complete
        if output_path.exists():
            try:
                with output_path.open("rb") as f:
                    output_lines = sum(1 for _ in f)
                if output_lines == total_lines and not FORCE_REPROCESS:
                    logger.info(f"Skipping {jsonl} -> {output_path}: Output file exists and has matching line count ({output_lines}).")
                    continue
                else:
                    logger.info(f"Reprocessing {jsonl} -> {output_path}: Output line count ({output_lines}) mismatches input ({total_lines}).")
            except Exception as e:
                logger.warning(f"Failed to check output file {output_path}: {e}")
        
        # Use streaming approach
        with jsonl.open("r") as fIn, output_path.open("w") as fOut:
             if num_workers > 1:
                 # Executor consumes iterator line by line + internal buffering
                 with ProcessPoolExecutor(max_workers=num_workers) as executor:
                     results = executor.map(process_record_wrapper, fIn)
                     for data in tqdm(results, total=total_lines, desc=f"  Extracting {file_name}", leave=False):
                         fOut.write(json.dumps(data) + "\n")
                         fOut.flush()
             else:
                 # Single process mode - better for debugging and environment preservation
                 results = (process_record_wrapper(line) for line in fIn)
                 for data in tqdm(results, total=total_lines, desc=f"  Extracting {file_name}", leave=False):
                     fOut.write(json.dumps(data) + "\n")
                     fOut.flush()
                
