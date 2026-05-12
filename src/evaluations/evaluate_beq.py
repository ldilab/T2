#!/usr/bin/env python3
"""
BEq/BEq+ Evaluation for chibench

Evaluates semantic equivalence between generated Lean code and ground truth
using Bidirectional Extended Definitional Equivalence (BEq/BEq+).

Follows the same approach as evaluate_research.py: copies raw repos to a
writable temp directory, modifies source files with BEq comparison code,
and runs `lake env lean <file>` to check equivalence.

Reference: Poiroux et al., "Reliable Evaluation and Benchmarks for Statement
           Autoformalization" (EMNLP 2025, arxiv:2406.07222)

Usage:
    python evaluate_beq.py --input_path <results_merged.json> --output_path <output.json> [options]
"""

import argparse
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120

DATASET_LEAN_PATHs = {
    "adele-ring_locally-compact": "",
    "Directed-Topology-Lean-4": "",
    "Duper_ITP_Paper_Artifact": "duper",
    "EmptyHexagonLean": "Lean",
    "Math2001": "",
    "math2001": "",
    "Untangle": "",
    "WhitneyGraustein": "",
    "lean-derived-categories": "",
    "PrimeNumberTheoremAnd": "",
}

# ============================================================
# Theorem Statement Extraction
# ============================================================


def strip_lean_attributes_and_docs(code: str) -> str:
    """Strip Lean attributes (@[...]) and doc comments (/-- ... -/) from code prefix."""
    s = code.strip()
    changed = True
    while changed:
        changed = False
        if s.startswith("/--"):
            end = s.find("-/")
            if end != -1:
                s = s[end + 2 :].strip()
                changed = True
        if s.startswith("@["):
            depth = 0
            for i, c in enumerate(s):
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        s = s[i + 1 :].strip()
                        changed = True
                        break
    return s


def extract_theorem_statement(code: str) -> str | None:
    """
    Extract the theorem/lemma statement (without proof) from Lean code.
    Returns the statement up to but not including ':= by', ':= sorry', etc.
    Returns None if no theorem/lemma found.
    """
    stripped = strip_lean_attributes_and_docs(code)

    # Check if it starts with a theorem/lemma keyword
    thm_match = re.match(
        r"((?:(?:noncomputable|protected|private)\s+)*(?:theorem|lemma)\s)", stripped
    )
    if not thm_match:
        return None

    # Find ':=' that indicates start of proof
    # Need to handle nested structures (parens, brackets)
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    i = 0
    while i < len(stripped):
        c = stripped[i]
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "[":
            depth_bracket += 1
        elif c == "]":
            depth_bracket -= 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif (
            c == ":"
            and i + 1 < len(stripped)
            and stripped[i + 1] == "="
            and depth_paren == 0
            and depth_bracket == 0
            and depth_brace == 0
        ):
            return stripped[:i].rstrip()
        # Skip string literals
        elif c == '"':
            i += 1
            while i < len(stripped) and stripped[i] != '"':
                if stripped[i] == "\\":
                    i += 1
                i += 1
        i += 1

    # No ':=' found — might be a statement-only declaration
    return stripped.rstrip()


def rename_theorem(statement: str, new_name: str) -> str | None:
    """Rename a theorem/lemma statement to a new name."""
    # Match: (modifiers) (theorem|lemma) <name> ...
    pattern = r"((?:(?:noncomputable|protected|private)\s+)*(?:theorem|lemma)\s+)(\S+)"
    match = re.match(pattern, statement)
    if not match:
        return None
    return match.group(1) + new_name + statement[match.end() :]


# ============================================================
# File Manipulation
# ============================================================


def parse_id_to_filepath(entry_id: str) -> str:
    """Extract file path from entry ID."""
    lean_idx = entry_id.find(".lean")
    if lean_idx == -1:
        raise ValueError(f"Invalid ID format (no .lean found): {entry_id}")
    return entry_id[: lean_idx + 5]


def find_target_in_file(file_content: str, target_code: str) -> int:
    """Find the position of target_code in file content. Returns -1 if not found."""
    return file_content.find(target_code)


def generate_beq_code(
    gt_statement: str,
    gen_statement: str,
    direction: int,
) -> str:
    """
    Generate BEq comparison Lean code for one direction.

    direction=1: GT is base (sorry), Gen is target (prove using GT)
    direction=2: Gen is base (sorry), GT is target (prove using Gen)
    """
    if direction == 1:
        base_stmt = gt_statement
        target_stmt = gen_statement
    else:
        base_stmt = gen_statement
        target_stmt = gt_statement

    base_renamed = rename_theorem(base_stmt, "beq_base_theorem")
    target_renamed = rename_theorem(target_stmt, "beq_target_theorem")

    if base_renamed is None or target_renamed is None:
        return None

    # BEqL: exact? only
    # Use `try` for tactics that may not exist in older Lean versions
    beql_code = f"""{base_renamed} := sorry

{target_renamed} := by
  try intros
  try symm_saturate
  exact?
"""
    return beql_code


def generate_beq_plus_code(
    gt_statement: str,
    gen_statement: str,
    direction: int,
    strategy: str,
) -> str | None:
    """
    Generate BEq+ comparison code for a specific strategy.

    Strategies: "exact", "apply", "convert0"..."convert4"
    """
    if direction == 1:
        base_stmt = gt_statement
        target_stmt = gen_statement
    else:
        base_stmt = gen_statement
        target_stmt = gt_statement

    base_renamed = rename_theorem(base_stmt, "beq_base_theorem")
    target_renamed = rename_theorem(target_stmt, "beq_target_theorem")

    if base_renamed is None or target_renamed is None:
        return None

    solver_tactics = "all_goals intros\\nfirst | (all_goals try tauto) ; (all_goals try simp_all_arith!) ; (all_goals try noncomm_ring) ; (all_goals try exact?) | all_goals ((try tauto) ; (try simp_all_arith!) ; (try noncomm_ring) ; (try exact?))"

    if strategy == "exact":
        proof = "try intros\n  try symm_saturate\n  exact?"
    elif strategy == "apply":
        proof = f"try intros\n  try symm_saturate\n  apply beq_base_theorem\n  {solver_tactics}"
    elif strategy.startswith("convert"):
        n = strategy[-1] if strategy[-1].isdigit() else "0"
        proof = f"try intros\n  try symm_saturate\n  convert (config := .unfoldSameFun) beq_base_theorem using {n}\n  {solver_tactics}"
    else:
        return None

    code = f"""{base_renamed} := sorry

{target_renamed} := by
  {proof}
"""
    return code


# ============================================================
# Evaluation Engine
# ============================================================


def run_lake_env_lean(
    repo_path: Path, file_path: Path, timeout: int
) -> tuple[int, str, str]:
    """Run `lake env lean <file>` and return (returncode, stdout, stderr)."""
    cmd = ["lake", "env", "lean", str(file_path)]
    try:
        with subprocess.Popen(
            cmd,
            cwd=str(repo_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        ) as p:
            try:
                stdout, stderr = p.communicate(timeout=timeout)
                return (p.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                p.wait()
                return (-1, "", "TIMEOUT")
    except Exception as e:
        return (-1, "", str(e))


def check_beq_output(stdout: str, stderr: str) -> dict:
    """
    Parse lean output to check if BEq passed.

    Looks for "Try this:" messages in stderr that reference beq_base_theorem.
    Also checks for absence of errors in the target theorem region.
    """
    result = {"passed": False, "proof": None, "error": None}

    # Lean outputs diagnostics to stderr
    combined = stdout + "\n" + stderr

    # Check for errors
    if "error:" in combined.lower():
        # Check if the error is in the beq_target_theorem region
        result["error"] = "compilation_error"

    # Look for "Try this:" suggestions
    for line in combined.split("\n"):
        if "Try this:" in line:
            proof = line.split("Try this:")[1].strip()
            if "beq_base_theorem" in proof:
                result["passed"] = True
                result["proof"] = proof
                return result

    # Check if the file compiled without errors (no "sorry" warnings means proof found)
    # For non-exact? strategies, check if there are no errors at all
    if "error:" not in combined.lower() and result["error"] is None:
        # If we used a non-exact? strategy and there are no errors,
        # the proof succeeded
        if "sorry" not in combined.lower() or "declaration uses 'sorry'" not in combined:
            # Only base_theorem should have sorry
            sorry_count = combined.count("declaration uses 'sorry'")
            if sorry_count <= 1:  # Only the base_theorem's sorry
                result["passed"] = True

    return result


def setup_worker_repo(
    dataset_name: str, raw_repos_path: str, worker_dir: str
) -> Path:
    """Copy raw repo to writable worker directory."""
    worker_path = Path(worker_dir)
    repo_dest = worker_path / dataset_name

    if repo_dest.exists():
        return repo_dest

    worker_path.mkdir(parents=True, exist_ok=True)

    source_path = Path(raw_repos_path) / dataset_name
    if not source_path.exists():
        raise FileNotFoundError(f"Raw repository not found: {source_path}")

    logger.info(f"Copying {dataset_name} to {repo_dest}...")
    subprocess.run(["cp", "-r", str(source_path), str(repo_dest)], check=True)
    # Ensure writable
    subprocess.run(["chmod", "-R", "u+w", str(repo_dest)], check=False)
    return repo_dest


def evaluate_entry_beq(
    entry: dict,
    repo_path: Path,
    raw_repos_path: str,
    timeout: int,
    is_prop: bool,
) -> list[dict]:
    """Evaluate a single entry using BEq/BEq+."""
    entry_id = entry.get("id", "unknown")
    dataset_name = entry.get("dataset_name", "")
    target_code = entry.get("target_code", "")

    # Get generated code
    formal_proofs = entry.get("formal_proof", [])
    if isinstance(formal_proofs, str):
        formal_proofs = [formal_proofs]

    results = []

    # Find the source file
    try:
        rel_path = parse_id_to_filepath(entry_id)
    except ValueError as e:
        for idx in range(max(len(formal_proofs), 1)):
            results.append(_make_result(entry_id, idx, error=str(e)))
        return results

    lean_subdir = DATASET_LEAN_PATHs.get(dataset_name, "")
    file_path = repo_path / lean_subdir / rel_path

    if not file_path.exists():
        for idx in range(max(len(formal_proofs), 1)):
            results.append(
                _make_result(entry_id, idx, error=f"File not found: {file_path}")
            )
        return results

    # Read original content
    try:
        original_content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        for idx in range(max(len(formal_proofs), 1)):
            results.append(_make_result(entry_id, idx, error=f"Read failed: {e}"))
        return results

    # Find target_code in file
    target_pos = find_target_in_file(original_content, target_code)
    if target_pos == -1:
        for idx in range(max(len(formal_proofs), 1)):
            results.append(
                _make_result(entry_id, idx, error="Target code not found in file")
            )
        return results

    # Extract GT statement from original file
    # Content from target_pos is the full GT (with proof)
    gt_full = original_content[target_pos:]
    # We only need up to a reasonable length
    gt_full = gt_full[:5000]
    gt_statement = extract_theorem_statement(gt_full)

    if gt_statement is None:
        # Not a theorem — might be a definition
        if not is_prop:
            for idx in range(max(len(formal_proofs), 1)):
                results.append(
                    _make_result(
                        entry_id, idx, error="Definition BEq not yet supported via lake"
                    )
                )
            return results
        for idx in range(max(len(formal_proofs), 1)):
            results.append(
                _make_result(entry_id, idx, error="Could not extract theorem statement")
            )
        return results

    # Context = everything before the target
    context = original_content[:target_pos]

    for idx, fp in enumerate(formal_proofs):
        res = _make_result(entry_id, idx)
        start_time = time.time()

        # Clean generated code
        fp_clean = _clean_markdown(str(fp))
        if not fp_clean:
            res["error_message"] = "Empty formal proof"
            res["status"] = "error"
            results.append(res)
            continue

        # Extract generated statement
        gen_statement = extract_theorem_statement(fp_clean)
        if gen_statement is None:
            res["error_message"] = "Could not extract theorem statement from generated code"
            res["status"] = "error"
            results.append(res)
            continue

        # Try BEqL first (exact? both directions)
        beql_pass = True
        for direction in [1, 2]:
            beq_code = generate_beq_code(gt_statement, gen_statement, direction)
            if beq_code is None:
                beql_pass = False
                res["error_message"] = "Failed to generate BEq code"
                break

            # Write modified file: inject BEq import + code
            beq_import = "import Mathlib.Tactic.LibrarySearch\n"
            modified_content = _inject_import(context, beq_import) + beq_code + "\n#exit\n"
            try:
                file_path.write_text(modified_content, encoding="utf-8")
                rc, stdout, stderr = run_lake_env_lean(repo_path, file_path, timeout)
                check = check_beq_output(stdout, stderr)
                if not check["passed"]:
                    beql_pass = False
                    if check.get("error"):
                        res["error_message"] = check["error"]
                    break
            except Exception as e:
                beql_pass = False
                res["error_message"] = str(e)[:500]
                break
            finally:
                # Always restore original
                file_path.write_text(original_content, encoding="utf-8")

        res["beql"] = beql_pass
        if beql_pass:
            res["beq_plus"] = True
            res["strategy"] = "exact"

        # If BEqL failed, try BEq+ strategies
        if not beql_pass:
            beq_plus_pass = _try_beq_plus(
                context, gt_statement, gen_statement, file_path,
                original_content, repo_path, timeout, res
            )
            res["beq_plus"] = beq_plus_pass

        res["status"] = "completed"
        res["time_seconds"] = round(time.time() - start_time, 2)
        results.append(res)

    if not formal_proofs:
        results.append(
            _make_result(entry_id, 0, error="No formal proof generated")
        )

    return results


def _try_beq_plus(
    context: str,
    gt_statement: str,
    gen_statement: str,
    file_path: Path,
    original_content: str,
    repo_path: Path,
    timeout: int,
    res: dict,
) -> bool:
    """Try BEq+ strategies (apply, convert) for both directions."""
    strategies = ["apply", "convert0", "convert1", "convert2", "convert3", "convert4"]

    for strategy in strategies:
        all_dirs_pass = True
        for direction in [1, 2]:
            beq_code = generate_beq_plus_code(
                gt_statement, gen_statement, direction, strategy
            )
            if beq_code is None:
                all_dirs_pass = False
                break

            beq_import = "import Mathlib.Tactic.LibrarySearch\n"
            modified_content = _inject_import(context, beq_import) + beq_code + "\n#exit\n"
            try:
                file_path.write_text(modified_content, encoding="utf-8")
                rc, stdout, stderr = run_lake_env_lean(repo_path, file_path, timeout)
                check = check_beq_output(stdout, stderr)
                if not check["passed"]:
                    all_dirs_pass = False
                    break
            except Exception:
                all_dirs_pass = False
                break
            finally:
                file_path.write_text(original_content, encoding="utf-8")

        if all_dirs_pass:
            res["strategy"] = strategy
            return True

    return False


def _make_result(
    entry_id: str, idx: int, error: str | None = None
) -> dict:
    return {
        "id": f"{entry_id}:::{idx}",
        "beq_plus": False,
        "beql": False,
        "status": "error" if error else "pending",
        "strategy": None,
        "error_message": error,
        "time_seconds": 0.0,
    }


def _inject_import(context: str, import_line: str) -> str:
    """Inject an import statement at the top of the file context (after existing imports)."""
    lines = context.split("\n")
    # Find last import line
    last_import = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("import "):
            last_import = i
    if last_import >= 0:
        lines.insert(last_import + 1, import_line.rstrip())
    else:
        lines.insert(0, import_line.rstrip())
    return "\n".join(lines)


def _clean_markdown(code: str) -> str:
    code = code.strip()
    if code.startswith("```lean"):
        code = code[len("```lean") :]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
    return code.strip()


# ============================================================
# Main
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description="BEq/BEq+ evaluation for chibench"
    )
    parser.add_argument(
        "--input_path",
        required=True,
        help="Path to results_merged.json or directory containing it",
    )
    parser.add_argument(
        "--output_path", required=True, help="Path for output evaluation JSON"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Timeout per lake env lean invocation in seconds (default: 120)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from partial evaluation output",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of entries to evaluate (0 = all)",
    )
    parser.add_argument(
        "--repo_root",
        default="data/research_papers/0raw/lean4",
        help="Path to raw Lean repositories (read-only source)",
    )
    parser.add_argument(
        "--worker_dir",
        default="./beq_workers",
        help="Writable directory for repo copies (default: ./beq_workers)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine if prop or noprop from path
    is_prop = "prop" in args.input_path and "noprop" not in args.input_path

    # Load data
    input_path = Path(args.input_path)
    if input_path.is_dir():
        input_file = input_path / "results_merged.json"
    else:
        input_file = input_path

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        sys.exit(1)

    with open(input_file, "r") as f:
        data = json.load(f)

    logger.info(f"Loaded {len(data)} entries from {input_file}")
    logger.info(f"Mode: {'prop (theorems)' if is_prop else 'noprop (definitions)'}")

    if args.limit > 0:
        data = data[: args.limit]
        logger.info(f"Limited to {len(data)} entries")

    # Load existing results for resume
    evaluated_ids = set()
    existing_results = []
    output_path = Path(args.output_path)
    if args.resume and output_path.exists():
        try:
            with open(output_path, "r") as f:
                existing_results = json.load(f)
            evaluated_ids = {r["id"] for r in existing_results}
            logger.info(
                f"Resuming: {len(evaluated_ids)} individual results already present"
            )
        except Exception as e:
            logger.warning(f"Could not load existing results for resume: {e}")

    # Setup repo copies per dataset
    datasets_needed = set(d.get("dataset_name", "") for d in data)
    repo_paths = {}
    for ds in datasets_needed:
        if not ds:
            continue
        try:
            repo_paths[ds] = setup_worker_repo(
                ds, args.repo_root, args.worker_dir
            )
        except Exception as e:
            logger.error(f"Failed to setup repo for {ds}: {e}")

    # Process entries
    all_results = list(existing_results)
    total = len(data)
    skipped = 0

    for i, entry in enumerate(data):
        entry_id = entry.get("id", f"entry_{i}")
        dataset_name = entry.get("dataset_name", "")

        # Skip already evaluated entries
        if any(f"{entry_id}:::" in eid for eid in evaluated_ids):
            skipped += 1
            continue

        if dataset_name not in repo_paths:
            all_results.append(
                _make_result(entry_id, 0, error=f"No repo for dataset: {dataset_name}")
            )
            continue

        logger.info(f"[{i + 1}/{total}] Evaluating: {entry_id[:80]}...")

        try:
            entry_results = evaluate_entry_beq(
                entry,
                repo_paths[dataset_name],
                args.repo_root,
                args.timeout,
                is_prop,
            )
        except Exception as e:
            logger.error(f"Failed to evaluate {entry_id}: {e}")
            entry_results = [
                _make_result(entry_id, 0, error=str(e)[:500])
            ]

        all_results.extend(entry_results)

        # Log per-entry result
        any_beq_plus = any(r.get("beq_plus") for r in entry_results)
        any_beql = any(r.get("beql") for r in entry_results)
        elapsed = sum(r.get("time_seconds", 0) for r in entry_results)
        logger.info(
            f"  -> BEq+={any_beq_plus}, BEqL={any_beql}, time={elapsed:.1f}s"
        )

        # Write intermediate results every 10 entries
        if (i + 1) % 10 == 0 or (i + 1) == total:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(all_results, f, indent=2)

    if skipped > 0:
        logger.info(f"Skipped {skipped} already-evaluated entries")

    # Write final results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)

    # Generate summary
    entry_beql = {}
    entry_beq_plus = {}
    entry_status = {}

    for r in all_results:
        base_id = r["id"].rsplit(":::", 1)[0] if ":::" in r["id"] else r["id"]
        entry_beql[base_id] = entry_beql.get(base_id, False) or r.get("beql", False)
        entry_beq_plus[base_id] = entry_beq_plus.get(base_id, False) or r.get(
            "beq_plus", False
        )
        if r.get("status") == "completed":
            entry_status[base_id] = "completed"
        elif base_id not in entry_status:
            entry_status[base_id] = r.get("status", "unknown")

    beql_pass = sum(1 for v in entry_beql.values() if v)
    beq_plus_pass = sum(1 for v in entry_beq_plus.values() if v)
    completed = sum(1 for v in entry_status.values() if v == "completed")
    errors = sum(1 for v in entry_status.values() if v == "error")
    exceptions = sum(1 for v in entry_status.values() if v == "exception")

    summary = {
        "total": total,
        "completed": completed,
        "beq_plus_pass": beq_plus_pass,
        "beq_plus_rate": round((beq_plus_pass / total) * 100, 2)
        if total > 0
        else 0.0,
        "beql_pass": beql_pass,
        "beql_rate": round((beql_pass / total) * 100, 2) if total > 0 else 0.0,
        "errors": errors,
        "exceptions": exceptions,
        "timeout_per_check": args.timeout,
        "is_prop": is_prop,
    }

    summary_path = str(output_path.with_suffix(".summary.json"))
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("=" * 60)
    logger.info("BEq Evaluation Summary:")
    logger.info(json.dumps(summary, indent=2))
    logger.info(f"Results saved to: {output_path}")
    logger.info(f"Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
