import argparse
import json
import logging
import multiprocessing
import os
import shutil
import subprocess
import signal
import time
import math
from collections import Counter
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Base path for worker temporary directories
WORKER_TEMP_BASE = "/tmp/chibench_eval_workers"

DATASET_LEAN_PATHs = {
    "adele-ring_locally-compact": "",
    "Directed-Topology-Lean-4": "",
    "Duper_ITP_Paper_Artifact": "duper",
    "EmptyHexagonLean": "Lean",
    "Math2001": "",
    "Untangle": "",
    "WhitneyGraustein": ""
}

def parse_id(entry_id: str) -> tuple[str, str]:
    """
    Parses the entry ID to extract the file path and function name.
    Example ID: AdeleRingLocallyCompact/path/to/File.lean/func_name.after_target_code=...
    Returns: (file_path, function_name)
    """
    # Find the .lean extension
    lean_idx = entry_id.find(".lean")
    if lean_idx == -1:
        raise ValueError(f"Invalid ID format (no .lean found): {entry_id}")
    
    # The file path includes .lean
    file_path = entry_id[:lean_idx + 5] # +5 for ".lean"
    
    rest = entry_id[lean_idx + 6:] # +6 to skip ".lean/"
    
    return file_path

def get_worker_id():
    """Get a unique ID for the current process to assign a workspace."""
    # current_process()._identity gives a tuple of indices (e.g., (1,)) for process pool workers.
    # If not available (main process), return 0.
    p = multiprocessing.current_process()
    if hasattr(p, '_identity') and p._identity:
        return p._identity[0]
    return 0

def setup_worker_env(worker_id: int, dataset_name: str, raw_repos_path: str):
    """
    Ensures the worker's temporary directory has the correct repository.
    Returns the path to the repository root in the worker's dir.
    """
    worker_dir = Path(WORKER_TEMP_BASE) / f"worker_{worker_id}"
    repo_dest = worker_dir / dataset_name
    metadata_file = worker_dir / "current_repo.txt"
    
    # Check if we already have this repo
    current_repo = None
    if metadata_file.exists():
        current_repo = metadata_file.read_text().strip()
    
    if current_repo == dataset_name and repo_dest.exists():
        return repo_dest
    
    # Data mismatch or first run: Clean and copy
    # We remove the ENTIRE worker dir to be safe and clean previous repos
    if worker_dir.exists():
        shutil.rmtree(worker_dir)
    
    worker_dir.mkdir(parents=True, exist_ok=True)
    
    source_path = Path(raw_repos_path) / dataset_name
    if not source_path.exists():
         raise FileNotFoundError(f"Raw repository not found at {source_path}")
         
    logger.info(f"[Worker {worker_id}] Copying {dataset_name} from {source_path} to {repo_dest}")
    # Use cp -r for speed
    subprocess.run(["cp", "-r", str(source_path), str(repo_dest)], check=True)
    
    metadata_file.write_text(dataset_name)
    return repo_dest

def evaluate_entry(entry: dict, raw_repos_path: str, eval_ground_truth: bool = False):
    """
    Evaluates a single entry.
    """
    worker_id = get_worker_id()
    dataset_name = entry.get("dataset_name")
    entry_id = entry.get("id")
    target_code = entry.get("target_code")
    
    # Prepare list of proofs to evaluate
    early_exit = False
    formal_proofs = []
    if eval_ground_truth:
        formal_proofs = [entry.get("target_code", "")]
    else:
        fp = entry.get("formal_proof", "")
        error = entry.get("error", "")
        if fp == "" and error != "":
            # Generation already failed, no point in trying to verify
            early_exit = True
            
        # Handle list or string
        if isinstance(fp, list):
            formal_proofs = fp
        else:
            formal_proofs = [fp]
            
    # Remove empty or just error string if needed? No, let's try to verify what we got.
    
    if early_exit:
        results = []
        for idx in range(len(formal_proofs)):
            res = {
                "id": f"{entry_id}:::{idx}",
                "dataset_name": dataset_name,
                "verified": False,
                "status": "exception",
                "error_message": "Generation failed",
                "formal_code_target": None
            }
            results.append(res)
        return results

    results = []
    
    # Setup environment ONCE for all proofs in this entry
    try:
        repo_path = setup_worker_env(worker_id, dataset_name, raw_repos_path)
    except Exception as e:
        # If setup fails, all fail
        for idx in range(len(formal_proofs)):
            res = {
                "id": f"{entry_id}:::{idx}",
                "dataset_name": dataset_name,
                "verified": False,
                "status": "exception",
                "error_message": f"Setup failed: {e}",
                "formal_code_target": None
            }
            results.append(res)
        return results

    # Identify file ONCE
    try:
        rel_file_path = parse_id(entry_id)
        file_path = repo_path / DATASET_LEAN_PATHs.get(dataset_name, "") / rel_file_path
    except Exception as e:
        for idx in range(len(formal_proofs)):
            res = {
                "id": f"{entry_id}:::{idx}",
                "dataset_name": dataset_name,
                "verified": False,
                "status": "exception",
                "error_message": f"Path parsing failed: {e}",
                "formal_code_target": None
            }
            results.append(res)
        return results

    if not file_path.exists():
        for idx in range(len(formal_proofs)):
            res = {
                "id": f"{entry_id}:::{idx}",
                "dataset_name": dataset_name,
                "verified": False,
                "status": "exception",
                "error_message": f"File not found: {file_path}",
                "formal_code_target": None
            }
            results.append(res)
        return results

    # Read original content
    try:
        original_content = file_path.read_text(encoding='utf-8')
    except Exception as e:
         for idx in range(len(formal_proofs)):
            res = {
                "id": f"{entry_id}:::{idx}",
                "dataset_name": dataset_name,
                "verified": False,
                "status": "exception",
                "error_message": f"Read failed: {e}",
                "formal_code_target": None
            }
            results.append(res)
         return results

    # Verify target code existence
    code_to_replace = target_code
    if code_to_replace not in original_content:
         for idx in range(len(formal_proofs)):
            res = {
                "id": f"{entry_id}:::{idx}",
                "dataset_name": dataset_name,
                "verified": False,
                "status": "error",
                "error_message": "Target code not found in file",
                "formal_code_target": None
            }
            results.append(res)
         print("==========TARGET CODE UNFOUND=============")
         return results

    # Iterate over proofs
    for idx, formal_proof in enumerate(formal_proofs):
        res = {
            "id": f"{entry_id}:::{idx}",
            "dataset_name": dataset_name,
            "verified": False,
            "status": "error",
            "error_message": "",
            "formal_code_target": None
        }
        
        # Clean up markdown
        formal_proof_str = str(formal_proof).strip()
        if formal_proof_str.startswith("```lean"):
            formal_proof_str = formal_proof_str.replace("```lean", "", 1)
        if formal_proof_str.startswith("```"):
            formal_proof_str = formal_proof_str.replace("```", "", 1)
        if formal_proof_str.endswith("```"):
            formal_proof_str = formal_proof_str[:-3]
        
        formal_proof_str = formal_proof_str.strip()
        res["formal_code_target"] = formal_proof_str

        # Apply change
        new_content = original_content.replace(code_to_replace, formal_proof_str)
        
        # Write new content
        file_path.write_text(new_content, encoding='utf-8')

        # Run lake build
        cmd = ["lake", "build"]
        
        try:
            with subprocess.Popen(
                cmd, 
                cwd=str(repo_path), 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                start_new_session=True
            ) as p:
                try:
                    stdout, stderr = p.communicate(timeout=1200)
                    proc = subprocess.CompletedProcess(args=cmd, returncode=p.returncode, stdout=stdout, stderr=stderr)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                    raise
            
            if proc.returncode == 0:
                res["verified"] = True
                res["status"] = "verified"
                res["pass_no_after"] = True
            else:
                res["status"] = "error"
                # Truncate error message to avoid memory explosion with large logs
                err_msg = proc.stderr if proc.stderr else ""
                if len(err_msg) > 5000:
                    err_msg = err_msg[:5000] + "... [TRUNCATED]"
                res["error_message"] = err_msg
                # Try pass_no_after check if build failed
                # 1. Insert #exit immediately after the proof
                content_no_after = original_content.replace(code_to_replace, formal_proof_str + "\n\n#exit\n")
                
                try:
                    file_path.write_text(content_no_after, encoding='utf-8')
                    # 2. Run lake env lean
                    cmd_no_after = ["lake", "env", "lean", str(file_path)]
                    
                    with subprocess.Popen(
                        cmd_no_after,
                        cwd=str(repo_path),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        start_new_session=True
                    ) as p_na:
                        try:
                            stdout_na, stderr_na = p_na.communicate(timeout=600)
                            proc_na = subprocess.CompletedProcess(args=cmd_no_after, returncode=p_na.returncode, stdout=stdout_na, stderr=stderr_na)
                        except subprocess.TimeoutExpired:
                            os.killpg(os.getpgid(p_na.pid), signal.SIGKILL)
                            raise
                    
                    if proc_na.returncode == 0:
                        res["pass_no_after"] = True
                    else:
                        res["pass_no_after"] = False
                        # Optional: append partial error message?
                        # res["error_message"] += f"\n[No After Check Failed]: {proc_na.stderr}"

                except Exception as e_na:
                     res["pass_no_after"] = False
                     logger.error(f"pass_no_after check failed with exception: {e_na}")

        except subprocess.TimeoutExpired:
            res["status"] = "timeout"
            res["error_message"] = "Build timed out"
            res["pass_no_after"] = False # Timeout usually means stuck, likely fail
        except Exception as e:
            res["status"] = "exception"
            res["error_message"] = str(e)
            res["pass_no_after"] = False
        finally:
            # Revert changes for next iteration
            try:
                 file_path.write_text(original_content, encoding='utf-8')
            except:
                 pass 
        
        results.append(res)

    return results

def calculate_em(prediction: str, reference: str) -> int:
    """Exact Match score (0 or 1)."""
    return 1 if prediction.strip() == reference.strip() else 0

def calculate_bleu(prediction: str, reference: str) -> float:
    """
    Calculate BLEU-4 score.
    Simple implementation dependency-free.
    Returns score 0-100.
    """
    prediction = prediction.strip()
    reference = reference.strip()
    
    if not prediction:
        return 0.0
    if not reference:
        return 0.0

    # Simple tokenizer: whitespace split
    cand_tokens = prediction.split()
    ref_tokens = reference.split()
    
    if not cand_tokens:
        return 0.0

    # 1. N-gram precisions
    precisions = []
    for n in range(1, 5):
        cand_ngrams = [tuple(cand_tokens[i:i+n]) for i in range(len(cand_tokens)-n+1)]
        ref_ngrams = [tuple(ref_tokens[i:i+n]) for i in range(len(ref_tokens)-n+1)]
        
        if not cand_ngrams:
            precisions.append(0.0)
            continue
            
        cand_counts = Counter(cand_ngrams)
        ref_counts = Counter(ref_ngrams)
        
        clipped_counts = {ngram: min(count, ref_counts[ngram]) for ngram, count in cand_counts.items()}
        precision = sum(clipped_counts.values()) / len(cand_ngrams)
        precisions.append(precision)

    # 2. Geometric mean of precisions
    if any(p == 0.0 for p in precisions):
        geo_mean = 0.0
    else:
        # Use log domain to avoid underflow
        log_sum = sum(math.log(p) for p in precisions)
        geo_mean = math.exp(log_sum / 4) # 4 is max_n

    # 3. Brevity Penalty
    c = len(cand_tokens)
    r = len(ref_tokens)
    
    if c > r:
        bp = 1.0
    else:
        if c == 0: bp = 0.0 # avoid div by zero, though checked above
        else: bp = math.exp(1 - r/c)

    return geo_mean * bp * 100

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_path", required=True)
    parser.add_argument("--gt_path", default="")
    parser.add_argument("--output_path", required=True)
    parser.add_argument("--repo_root", default="data/research_papers/0raw/lean4")
    parser.add_argument("--num_workers", type=int, default=4)
    parser.add_argument("--eval_ground_truth", action="store_true", help="Use formal_language as formal_proof for ground truth evaluation")
    args = parser.parse_args()


    is_prop = "prop" in args.input_path and "noprop" not in args.input_path
    eval_type = "prop" if is_prop else "noprop"

    args.gt_path = f"data/final/research_papers.nosorry.{eval_type}.jsonl"

    if args.eval_ground_truth:
        logger.info("Evaluating ground truth")
        
        args.input_path = args.gt_path
        data = []
        with open(args.input_path, 'r') as f:
            for line in f:
                data.append(json.loads(line))
    
    else:
        with open(args.input_path, 'r') as f:
            data = json.load(f)
    
    logger.info(f"Loaded {len(data)} entries")

    data.sort(key=lambda x: x.get("dataset_name", ""))

    results = []
    
    # Clean up any existing worker dirs at start
    if Path(WORKER_TEMP_BASE).exists():
        try:
            shutil.rmtree(WORKER_TEMP_BASE)
        except:
            pass
    Path(WORKER_TEMP_BASE).mkdir(parents=True, exist_ok=True)

    
    # Streaming Processing and Writing
    # Open output file immediately and write results as they come
    # This avoids keeping the entire dataset + results in memory
    
    total_em = 0
    total_bleu = 0
    text_metric_count = 0
    
    pass_count = 0
    pass_no_after_count = 0
    error_count = 0
    sorry_count = 0
    timeout_count = 0
    exception_count = 0
    
    # We will write a valid JSON array by managing commas
    try:
        with open(args.output_path, 'w') as f_out:
            f_out.write("[\n")
            
            with ProcessPoolExecutor(max_workers=args.num_workers) as executor:
                # Submit all tasks. 
                # Note: Submitting all tasks creates Future objects. For 10k items this is small (<10MB).
                # If millions, we would need to batch submission too. Assuming <100k here.
                future_to_entry = {
                    executor.submit(evaluate_entry, entry, args.repo_root, args.eval_ground_truth): entry 
                    for entry in data
                }
                
                total = len(data)
                completed = 0
                first_entry_written = False
                
                for future in as_completed(future_to_entry):
                    completed += 1
                    entry = future_to_entry[future]
                    try:
                        entry_results = future.result()
                    except Exception as e:
                        logger.error(f"Critical failure in future for {entry.get('id')}: {e}")
                        entry_results = [] # Should not happen with current evaluate_entry exception handling
                        
                    # remove future to free memory? (as_completed does not retain it, but the dict does)
                    del future_to_entry[future]

                    # --- Process Entry Stats (Moved from post-loop) ---
                    
                    # Sort results by index
                    try:
                        entry_results.sort(key=lambda x: int(x['id'].split(':::')[1]) if ':::' in x['id'] else 0)
                    except:
                        pass

                    generated_list = []
                    gen = entry.get("formal_proof", "")
                    if isinstance(gen, list):
                        generated_list = gen
                    else:
                        generated_list = [gen]
                        
                    reference_text = entry.get("target_code", "")
                    if reference_text is None: reference_text = ""
                    reference_text = str(reference_text).strip()
                    
                    entry_ems = []
                    entry_bleus = []
                    
                    for g in generated_list:
                        g_str = str(g).strip()
                        if g_str.startswith("```lean"):
                            g_str = g_str.replace("```lean", "").replace("```", "")
                        elif g_str.startswith("```"):
                             g_str = g_str.replace("```", "")
                        g_str = g_str.strip()
                        
                        entry_ems.append(calculate_em(g_str, reference_text))
                        entry_bleus.append(calculate_bleu(g_str, reference_text))
                        
                    if entry_ems:
                        avg_em = sum(entry_ems)/len(entry_ems)
                        avg_bleu = sum(entry_bleus)/len(entry_bleus)
                        
                        total_em += avg_em
                        total_bleu += avg_bleu
                        text_metric_count += 1
                        
                        entry['em'] = avg_em
                        entry['bleu'] = avg_bleu
                    else:
                        entry['em'] = 0.0
                        entry['bleu'] = 0.0

                    # Pass@k status
                    statuses = [r.get('status') for r in entry_results]
                    
                    entry['evaluations'] = entry_results
                    
                    if 'verified' in statuses:
                        final_status = 'verified'
                    elif 'sorry' in statuses:
                        final_status = 'sorry'
                    elif 'error' in statuses:
                        final_status = 'error'
                    elif 'timeout' in statuses:
                        final_status = 'timeout'
                    else:
                        final_status = 'exception'
                        
                    entry['status'] = final_status
                    
                    is_pass_no_after = any(r.get('pass_no_after', False) for r in entry_results)
                    entry['pass_no_after'] = is_pass_no_after
                    if is_pass_no_after:
                        pass_no_after_count += 1

                    if final_status == 'verified':
                        pass_count += 1
                    elif final_status == 'error':
                        error_count += 1
                    elif final_status == 'sorry':
                        sorry_count += 1
                    elif final_status == 'timeout':
                        timeout_count += 1
                    elif final_status == 'exception':
                        exception_count += 1
                    
                    # --- Write to file immediately ---
                    if first_entry_written:
                        f_out.write(",\n")
                    json.dump(entry, f_out, indent=2)
                    first_entry_written = True

                    if completed % 10 == 0:
                        logger.info(f"Progress: {completed}/{total}")
            
            f_out.write("\n]")
            
    except Exception as e:
        logger.error(f"Failed during execution loop: {e}")
        # Even if failed, we tried to write partial results.
        raise e

    # Summary
    avg_em = (total_em / text_metric_count * 100) if text_metric_count > 0 else 0
    avg_bleu = (total_bleu / text_metric_count) if text_metric_count > 0 else 0
    
    summary = {
        "total": total,
        "evaluated": total, # or completed
        "verified": pass_count,
        "pass_no_after": pass_no_after_count,
        "error": error_count,
        "sorry": sorry_count,
        "timeout": timeout_count,
        "exception": exception_count,
        "missing": 0,
        "warning": 0, 
        "em_rate": avg_em,
        "bleu_score": avg_bleu
    }
    
    # Calculate rates
    if total > 0:
        summary["pass_rate"] = (summary["verified"] / total) * 100
        summary["pass_rate_no_after"] = (summary["pass_no_after"] / total) * 100
        summary["error_rate"] = (summary["error"] / total) * 100
        summary["sorry_rate"] = (summary["sorry"] / total) * 100
        summary["exception_rate"] = (summary["exception"] / total) * 100
        summary["timeout_rate"] = (summary["timeout"] / total) * 100
    else:
        summary["pass_rate"] = 0.0
        summary["pass_rate_no_after"] = 0.0
        summary["error_rate"] = 0.0
        summary["sorry_rate"] = 0.0
        summary["exception_rate"] = 0.0
        summary["timeout_rate"] = 0.0

    logger.info("Evaluation Summary:")
    logger.info(json.dumps(summary, indent=2))
    logger.info(f"Exact Match:    {avg_em:.2f}%")
    logger.info(f"BLEU Score:     {avg_bleu:.2f}")
    
    # Save summary json
    summary_path = str(Path(args.output_path).with_suffix('.summary.json'))
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

if __name__ == "__main__":
    main()
