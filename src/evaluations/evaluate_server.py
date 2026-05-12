
import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

import aiohttp
from tqdm.asyncio import tqdm_asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Default Lean verification server. Override via `--server_url` or by editing this constant.
SERVER_URL = "http://localhost:8003/verify"

async def verify_code(session: aiohttp.ClientSession, url: str, items: List[Dict[str, str]], task_type: str = "full") -> List[Dict[str, Any]]:
    """
    Sends a batch of Lean code to the verification server and returns the results.

    :param session: aiohttp.ClientSession
    :param url: str
    :param items: List[Dict[str, str]] - list of {"code": str, "id": str, "allowed_sorries": List[str] (optional), "target_function": str (optional)}
    :param task_type: str
    :return: List[Dict[str, Any]]
    """
    if not items:
        return []

    # Construct payload
    payload_codes = []
    for item in items:
        payload_codes.append({"code": item["code"], "custom_id": item["id"]})
    
    payload = {"codes": payload_codes}
    
    # Map by ID for easy lookup
    item_map = {item["id"]: item for item in items}
    
    # Default return objects (in case of failure)
    final_results = []
    
    try:
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                raw_response = await response.json()
                results = raw_response.get("results", [])
                
                # Process each result from server
                for result in results:
                    custom_id = result.get("custom_id")
                    if custom_id not in item_map:
                        logger.warning(f"Received result for unknown ID {custom_id}")
                        continue
                        
                    original_item = item_map[custom_id]
                    code = original_item["code"]

                    # Original Logic Reconstruction
                    return_object = {
                        "status": None,
                        "verified": False,
                        "id": custom_id,
                        "code": code,
                    }
                    
                    server_response = result.get("response", {})
                    messages = server_response.get("messages", [])
                    sorries = server_response.get("sorries", [])

                    # Filter messages by severity
                    # (Logic from original function)
                    traces = [x.get("data", "") for x in messages if x.get("severity") == "trace"]
                    infos = [x.get("data", "") for x in messages if x.get("severity") == "info"]
                    warnings = [x.get("data", "") for x in messages if x.get("severity") == "warning"]
                    errors = [x.get("data", "") for x in messages if x.get("severity") == "error"]

                    # Map pos to function name
                    line_num_to_function_name = get_line_function_map(code)

                    info_functions = [line_num_to_function_name.get(x.get("pos", {}).get("line", 0), "") for x in messages if x.get("severity") == "info"]
                    trace_functions = [line_num_to_function_name.get(x.get("pos", {}).get("line", 0), "") for x in messages if x.get("severity") == "trace"]
                    warning_functions = [line_num_to_function_name.get(x.get("pos", {}).get("line", 0), "") for x in messages if x.get("severity") == "warning"]
                    error_functions = [line_num_to_function_name.get(x.get("pos", {}).get("line", 0), "") for x in messages if x.get("severity") == "error"]
                    sorry_functions = [
                        line_num_to_function_name.get(x.get("pos", {}).get("line", 0), "") 
                        for x in messages 
                        if x.get("severity") == "info" and x.get("message", "").startswith("Sorry")
                    ]

                    # filter out empty strings
                    info_functions = [x for x in info_functions if x != ""]
                    trace_functions = [x for x in trace_functions if x != ""]
                    warning_functions = [x for x in warning_functions if x != ""]
                    error_functions = [x for x in error_functions if x != ""]
                    sorry_functions = [x for x in sorry_functions if x != ""]
                    
                    # Status determination
                    if any(x.get("severity") == "error" for x in messages):
                        return_object["status"] = "error"
                    elif len(sorry_functions) > 0:
                        return_object["status"] = "sorry"
                    else:
                        return_object["status"] = "verified"
                        return_object["verified"] = True

                    return_object.update({
                        "raw_response": server_response,
                        "info_functions": info_functions,
                        "trace_functions": trace_functions,
                        "warning_functions": warning_functions,
                        "error_functions": error_functions,
                        "sorry_functions": sorry_functions,
                    })
                    
                    final_results.append(return_object)
                    
            else:
                text = await response.text()
                logger.error(f"Server returned status {response.status} for batch: {text}")
                # Fail all
                for item in items:
                    final_results.append({
                        "id": item["id"],
                        "status": "error",
                        "error_message": f"HTTP {response.status}: {text}",
                        "verified": False
                    })
                    
    except Exception as e:
        logger.error(f"Exception verifying batch: {e}")
        for item in items:
            final_results.append({
                "id": item["id"],
                "status": "exception",
                "error_message": str(e),
                "verified": False
            })
            
    # Ensure all items have a result
    processed_ids = {r["id"] for r in final_results}
    for item in items:
        if item["id"] not in processed_ids:
             final_results.append({
                "id": item["id"],
                "status": "error",
                "error_message": "No response for this item from server",
                "verified": False
            })

    return final_results

def prepare_entry(entry: Dict[str, Any], original_record: Dict[str, Any], task_type: str = "full") -> List[Dict[str, Any]]:
    """
    Prepares the full code for verification but does not call the server.
    """
    entry_id = entry.get("id")
    
    # Context
    before = entry.get("before_target_code", "") or original_record.get("before_target_code", "")
    after = entry.get("after_target_code", "") or original_record.get("after_target_code", "")
    header = entry.get("header", "") or original_record.get("header", "")
    
    # Generated Code

    generated_list = []
    generated = entry.get("formal_proof")
    if not generated:
        generated = entry.get("formal_code_target")
    if not generated and "response" in entry:
        generated = entry["response"]
        
    if generated is None:
        generated = []
    elif isinstance(generated, str):
        generated_list = [generated]
    elif isinstance(generated, list):
        generated_list = generated
    
    if not generated_list:
        return [{"id": entry_id, "status": "empty_generation", "verified": False}]

    prepared_items = []
    for idx, gen in enumerate(generated_list):
        gen = str(gen).strip()
        if gen.startswith("```lean"):
            gen = gen.replace("```lean", "").replace("```", "")
        elif gen.startswith("```"):
             gen = gen.replace("```", "")
        
        gen = gen.strip()
        full_code = f"{header}\n\n{before}\n{gen}\n{after}"
        full_code = re.sub(r'\n\n+', '\n\n', full_code)
        
        item_id = f"{entry_id}:::{idx}"
        prepared_items.append({"id": item_id, "code": full_code})

        # No After Code
        full_code_no_after = f"{header}\n\n{before}\n{gen}"
        full_code_no_after = re.sub(r'\n\n+', '\n\n', full_code_no_after)
        item_id_no_after = f"{entry_id}:::{idx}:::no_after"
        prepared_items.append({"id": item_id_no_after, "code": full_code_no_after})

    return prepared_items

async def process_entries(entries: List[Dict[str, Any]], original_data_map: Dict[str, Dict], server_url: str, num_workers: int, task_type: str) -> List[Dict[str, Any]]:
    # 1. Prepare all items
    items_to_verify = []
    final_results = []
    
    for entry in entries:
        entry_id = entry.get("id")
        if entry_id not in original_data_map:
            logger.warning(f"ID {entry_id} not found in original dataset. Skipping.")
            continue
            
        original = original_data_map[entry_id]
        prepared_list = prepare_entry(entry, original, task_type)
        
        if not prepared_list:
            continue

        for prepared in prepared_list:
            if "code" in prepared:
                items_to_verify.append(prepared)
            else:
                final_results.append(prepared)
            
    # 2. Batching
    BATCH_SIZE = 32  # Can be tuned
    batches = [items_to_verify[i:i + BATCH_SIZE] for i in range(0, len(items_to_verify), BATCH_SIZE)]
    
    logger.info(f"Total items to verify: {len(items_to_verify)}. Created {len(batches)} batches.")

    # 3. Process batches
    connector = aiohttp.TCPConnector(limit=num_workers)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for batch in batches:
            tasks.append(verify_code(session, server_url, batch, task_type))
        
        batch_results = await tqdm_asyncio.gather(*tasks, desc="Verifying proofs")
        
        # Flatten results
        for batch_res in batch_results:
            final_results.extend(batch_res)
            
    return final_results

def load_data(path: str) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        if path.suffix == '.jsonl':
            return [json.loads(line) for line in f if line.strip()]
        else:
            return json.load(f)

def extract_originally_sorrys(full_code: str) -> List[str]:
    """
    This function extracts the function names that were marked as "sorry" in the original code.
    """
    import re
    # Matches Lean declarations (theorem, lemma, def, instance) that are completed with 'sorry'
    pattern = r"(?:theorem|lemma|def|instance|example)\s+([^\s\(\{\:]+)(?:(?!\n\n).)*?:=\s*(?:by\s+)?sorry"
    return re.findall(pattern, full_code, re.DOTALL)

def get_line_function_map(code: str) -> Dict[int, str]:
    """
    Returns a map from line number (1-based) to the name of the function/theorem defined at or before that line.
    """
    import re
    lines = code.split('\n')
    mapping = {}
    current_decl = None
    
    # Simple regex to catch start of declarations
    # Adjust regex to better match Lean 4 syntax
    # e.g. "theorem foo ...", "def bar ...", "lemma baz ..."
    # It might span multiple lines, but we just want to know "which block are we in".
    pattern = re.compile(r"^\s*(?:theorem|lemma|def|instance|example)\s+([^\s\(\{\:]+)")
    
    for i, line in enumerate(lines):
        line_num = i + 1
        match = pattern.match(line)
        if match:
            current_decl = match.group(1) # The name
        
        if current_decl:
            mapping[line_num] = current_decl
            
    return mapping

def main():
    parser = argparse.ArgumentParser(description="Evaluate proving results")
    parser.add_argument("--input_path", type=str, required=False, help="Path to generation results (JSONL), required unless --eval_ground_truth is set")
    parser.add_argument("--dataset_path", type=str, default="", help="Path to original total.jsonl")
    parser.add_argument("--output_path", type=str, required=True, help="Path to save evaluation report")
    parser.add_argument("--server_url", type=str, default=SERVER_URL, help="Verification server URL")
    parser.add_argument("--num_workers", type=int, default=20, help="Concurrency")
    parser.add_argument("--task_type", type=str, default="prop", choices=["prop", "noprop"], help="Task type: prop or noprop")
    parser.add_argument("--eval_ground_truth", action="store_true", help="Evaluate ground truth instead of generated results")
    
    args = parser.parse_args()


    if args.dataset_path == "":
        if args.task_type == "prop":
            args.dataset_path = "data/final/existing_datasets.prop.jsonl"
        elif args.task_type == "noprop":
            args.dataset_path = "data/final/existing_datasets.noprop.jsonl"

    assert args.dataset_path != "", "Dataset path not specified"

    logger.info(f"Task Type: {args.task_type}")
    
    if args.eval_ground_truth:
        logger.info("Evaluating GROUND TRUTH from reference dataset")
        # Logic to populate generated results from reference dataset
        pass
    else:
        logger.info(f"Loading results from {args.input_path}")
        results_data = load_data(args.input_path)
        logger.info(f"Loaded {len(results_data)} generated records")

    logger.info(f"Loading reference dataset from {args.dataset_path}")
    original_data = load_data(args.dataset_path)
    original_map = {r['id']: r for r in original_data}
    logger.info(f"Loaded {len(original_map)} reference records")
    
    if args.eval_ground_truth:
        # Construct fake results from original data
        results_data = []
        for r in original_data:
            fake_entry = {"id": r["id"]}
            fake_entry["formal_proof"] = r.get("target_code", "")

            results_data.append(fake_entry)
        logger.info(f"Constructed {len(results_data)} ground truth records for evaluation")

    logger.info("Starting verification...")
    # Run verification
    eval_results = asyncio.run(process_entries(results_data, original_map, args.server_url, args.num_workers, args.task_type))
    
    # Merge and Calculate Text Metrics
    final_output = []
    # Map back results to original ID
    # eval_results has items with id "original_id:::idx"
    
    eval_map = {} # Map "original_id" -> list of results
    eval_map_no_after = {} # Map "original_id" -> list of results (no after)
    
    for r in eval_results:
        rid = r.get("id")
        if ":::" in rid:
            parts = rid.split(":::")
            if len(parts) == 3 and parts[2] == "no_after":
                oid = parts[0]
                idx = parts[1] # Keep index for sorting if needed
                if oid not in eval_map_no_after:
                   eval_map_no_after[oid] = []
                eval_map_no_after[oid].append(r)
                continue
            
            # It's one of our sub-tasks (standard)
            oid = parts[0]
            if oid not in eval_map:
                eval_map[oid] = []
            eval_map[oid].append(r)
        else:
            # Should not happen with new logic, but handle legacy/fallback
            if rid not in eval_map:
                eval_map[rid] = []
            eval_map[rid].append(r)

    verified_count = 0
    error_count = 0
    sorry_count = 0
    warning_count = 0
    verified_count = 0
    error_count = 0
    sorry_count = 0
    warning_count = 0
    exception_count = 0
    
    pass_no_after_count = 0

    
    total_processed = 0
    total_number_of_questions = len(original_data)

    total_em = 0
    total_bleu = 0
    text_metric_count = 0
    
    # Track pass@k
    # We will count a question as "verified" (solved) if ANY of its samples are verified.
    # We will also track metrics per sample if needed, but summary usually asks for "problem solve rate".
    
    for entry in results_data:
        eid = entry.get("id")
        
        # Calculate Text Metrics
        # 1. Get Generated Text
        generated_list = []
        generated = entry.get("formal_proof")
        if not generated and "response" in entry:
            generated = entry["response"]
        
        if isinstance(generated, list):
             generated_list = generated
        elif isinstance(generated, str):
             generated_list = [generated]
        elif generated is None:
             generated_list = []
        
        # 2. Get Reference Text
        reference_text = ""
        if eid in original_map:
            original = original_map[eid]
            reference_text = original.get("target_code", "")
        if reference_text is None: reference_text = ""
        reference_text = str(reference_text).strip()
        
        # 3. Calculate Text Metrics (Average over samples)
        entry_ems = []
        entry_bleus = []
        
        for gen in generated_list:
            gen_str = str(gen).strip()
            if gen_str.startswith("```lean"):
                gen_str = gen_str.replace("```lean", "").replace("```", "")
            elif gen_str.startswith("```"):
                 gen_str = gen_str.replace("```", "")
            gen_str = gen_str.strip()
            
            entry_ems.append(calculate_em(gen_str, reference_text))
            entry_bleus.append(calculate_bleu(gen_str, reference_text))
            
        # Store average metrics for this entry
        if entry_ems:
            avg_entry_em = sum(entry_ems) / len(entry_ems)
            avg_entry_bleu = sum(entry_bleus) / len(entry_bleus)
            entry['em'] = avg_entry_em
            entry['bleu'] = avg_entry_bleu
            
            # Add to totals (averaged per question)
            total_em += avg_entry_em
            total_bleu += avg_entry_bleu
            text_metric_count += 1
        else:
            entry['em'] = 0
            entry['bleu'] = 0

        # Attach evaluations
        if eid in eval_map:
            evals = eval_map[eid]
            # Sort by index if possible
            try:
                evals.sort(key=lambda x: int(x['id'].split(':::')[1]) if ':::' in x['id'] else 0)
            except:
                pass
                
            entry['evaluations'] = evals
            
            # Determine overall status for this question
            # Pass if ANY is verified
            is_verified = any(e.get('status') == 'verified' for e in evals)
            
            # If not verified, current status logic:
            # error if any error? or just take the status of the first one?
            # User wants pass@N. "pass" usually means solved.
            # If solved, status = verified.
            # If not solved, what is the status?
            # Maybe 'error' if all are errors, 'sorry' if all are sorry?
            # Let's pick the "best" status. verified > sorry > error > exception
            
            statuses = [e.get('status') for e in evals]
            if 'verified' in statuses:
                final_status = 'verified'
            elif 'sorry' in statuses:
                final_status = 'sorry'
            elif 'error' in statuses:
                final_status = 'error'
            else:
                final_status = 'exception' # or whatever is left
            
            entry['status'] = final_status
            
            has_warnings = any(len(e.get('warning_functions', [])) > 0 for e in evals)
            
            if final_status == 'verified':
                verified_count += 1
                if has_warnings:
                    warning_count += 1
            elif final_status == 'error':
                error_count += 1
            elif final_status == 'sorry':
                sorry_count += 1
            elif final_status == 'exception':
                exception_count += 1
                
            total_processed += 1

        # Check pass_no_after
        if eid in eval_map_no_after:
            evals_no_after = eval_map_no_after[eid]
            is_verified_no_after = any(e.get('status') == 'verified' for e in evals_no_after)
            entry['pass_no_after'] = is_verified_no_after
            if is_verified_no_after:
                pass_no_after_count += 1
        else:
             entry['pass_no_after'] = False
             
        final_output.append(entry)
    
    missing_count = total_number_of_questions - total_processed
    if missing_count < 0:
        missing_count = 0 # Should not happen unless result has more than original
        
    pass_rate = (verified_count / total_number_of_questions * 100) if total_number_of_questions > 0 else 0
    pass_rate_no_after = (pass_no_after_count / total_number_of_questions * 100) if total_number_of_questions > 0 else 0
    error_rate = (error_count / total_number_of_questions * 100) if total_number_of_questions > 0 else 0
    sorry_rate = (sorry_count / total_number_of_questions * 100) if total_number_of_questions > 0 else 0
    warning_rate = (warning_count / total_number_of_questions * 100) if total_number_of_questions > 0 else 0
    exception_rate = (exception_count / total_number_of_questions * 100) if total_number_of_questions > 0 else 0
    missing_rate = (missing_count / total_number_of_questions * 100) if total_number_of_questions > 0 else 0
    
    avg_em = (total_em / text_metric_count * 100) if text_metric_count > 0 else 0
    avg_bleu = (total_bleu / text_metric_count) if text_metric_count > 0 else 0 # BLEU is usually 0-100 scale but let's see implementation

    logger.info("-" * 40)
    logger.info(f"Total Evaluated: {total_processed} / {total_number_of_questions}")
    logger.info(f"Verified:       {verified_count} / {total_number_of_questions} ({pass_rate:.2f}%)")
    logger.info(f"Pass (No After):{pass_no_after_count} / {total_number_of_questions} ({pass_rate_no_after:.2f}%)")
    logger.info(f"Error:          {error_count} / {total_number_of_questions} ({error_rate:.2f}%)")
    logger.info(f"Sorry:          {sorry_count} / {total_number_of_questions} ({sorry_rate:.2f}%)")
    logger.info(f"Warning:        {warning_count} / {total_number_of_questions} ({warning_rate:.2f}%)")
    logger.info(f"Exception:      {exception_count} / {total_number_of_questions} ({exception_rate:.2f}%)")
    logger.info(f"Missing:        {missing_count} / {total_number_of_questions} ({missing_rate:.2f}%)")
    logger.info(f"Exact Match:    {avg_em:.2f}%")
    logger.info(f"BLEU Score:     {avg_bleu:.2f}")
    logger.info("-" * 40)
    
    os.makedirs(os.path.dirname(args.output_path), exist_ok=True)
    with open(args.output_path, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
        
    summary_path = str(Path(args.output_path).with_suffix('.summary.json'))
    summary_data = {
        "total": total_processed,
        "total_questions": total_number_of_questions,
        "verified": verified_count,
        "pass_no_after": pass_no_after_count,
        "error": error_count,
        "sorry": sorry_count,
        "warning": warning_count,
        "exception": exception_count,
        "missing": missing_count,
        "pass_rate": pass_rate,
        "pass_rate_no_after": pass_rate_no_after,
        "error_rate": error_rate,
        "sorry_rate": sorry_rate,
        "warning_rate": warning_rate,
        "exception_rate": exception_rate,
        "missing_rate": missing_rate,
        "em_rate": avg_em,
        "bleu_score": avg_bleu
    }
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, indent=2)
    
    logger.info(f"Saved results to {args.output_path}")

import math
from collections import Counter

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

if __name__ == "__main__":
    main()
