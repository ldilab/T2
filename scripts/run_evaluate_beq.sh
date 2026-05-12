#!/bin/bash
# run_evaluate_beq.sh - Run BEq/BEq+ evaluation across all experiment variants
#
# Uses `lake env lean` on writable repo copies (no REPL needed).
# Works with any Lean version present in the raw repos.
#
# Usage:
#   ./scripts/run_evaluate_beq.sh [TYPE] [PROP_TYPE] [MODEL] [options]
#
# Examples:
#   ./scripts/run_evaluate_beq.sh research prop                  # Latest prop experiment
#   ./scripts/run_evaluate_beq.sh research prop claude-sonnet-4-5 # Specific model
#   ./scripts/run_evaluate_beq.sh research prop --all-exp        # All experiments per group
#   ./scripts/run_evaluate_beq.sh research prop --all            # All (legacy)
#   ./scripts/run_evaluate_beq.sh --ablation-type wo_nl          # Specific ablation
#
# Prerequisites:
#   export ELAN_HOME=/path/to/your/elan
#   export PATH=$ELAN_HOME/bin:$PATH

# Default Arguments
TYPE="research"
PROP_TYPE="prop"
MODEL=""

# Parse positional arguments if provided
if [[ -n "$1" && "$1" != --* ]]; then
    TYPE="$1"
    shift
    if [[ -n "$1" && "$1" != --* ]]; then
        PROP_TYPE="$1"
        shift
        if [[ -n "$1" && "$1" != --* ]]; then
            MODEL="$1"
            shift
        fi
    fi
fi

FORCE_MODE=false
ALL_EXPERIMENTS=false
ALL_EXP_PER_GROUP=false
ABLATION_TYPE=""
TIMEOUT=120
LIMIT=0
ROOT_DIR="results"
REPO_ROOT=""
WORKER_DIR="./beq_workers"
VERBOSE=""
RESUME=""

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --model)
            if [ -n "$2" ]; then
                MODEL="$2"
                shift
            else
                echo "Error: --model requires a value."
                exit 1
            fi
            ;;
        --all) ALL_EXPERIMENTS=true ;;
        --all-exp) ALL_EXP_PER_GROUP=true ;;
        --force) FORCE_MODE=true ;;
        --timeout)
            if [ -n "$2" ]; then
                TIMEOUT="$2"
                shift
            else
                echo "Error: --timeout requires a value."
                exit 1
            fi
            ;;
        --limit)
            if [ -n "$2" ]; then
                LIMIT="$2"
                shift
            else
                echo "Error: --limit requires a value."
                exit 1
            fi
            ;;
        --ablation-type)
            if [ -n "$2" ]; then
                ABLATION_TYPE="$2"
                shift
            else
                echo "Error: --ablation-type requires a value."
                exit 1
            fi
            ;;
        --root-dir)
            if [ -n "$2" ]; then
                ROOT_DIR="$2"
                shift
            else
                echo "Error: --root-dir requires a value."
                exit 1
            fi
            ;;
        --worker-dir)
            if [ -n "$2" ]; then
                WORKER_DIR="$2"
                shift
            else
                echo "Error: --worker-dir requires a value."
                exit 1
            fi
            ;;
        --repo-root)
            if [ -n "$2" ]; then
                REPO_ROOT="$2"
                shift
            else
                echo "Error: --repo-root requires a value."
                exit 1
            fi
            ;;
        --resume) RESUME="--resume" ;;
        --verbose) VERBOSE="--verbose" ;;
    esac
    shift
done

perform_beq_evaluation() {
    local TARGET_ROOT=$1
    local TARGET_DIR="${TARGET_ROOT}/${TYPE}/${PROP_TYPE}"

    if [ -n "$MODEL" ]; then
        TARGET_DIR="${TARGET_DIR}/${MODEL}"
    fi

    if [ ! -d "$TARGET_DIR" ]; then
        echo "Warning: Target directory $TARGET_DIR does not exist. Skipping."
        return
    fi

    echo "=== Running BEq Evaluation for $TARGET_DIR ==="
    echo "    Timeout: ${TIMEOUT}s, Worker dir: $WORKER_DIR"

    # Find candidates
    MAX_DEPTH=3
    if [ -n "$MODEL" ]; then
        MAX_DEPTH=2
    fi
    candidates=$(find "$TARGET_DIR" -maxdepth "$MAX_DEPTH" -type f -name "results_merged.json")

    if [ -z "$candidates" ]; then
        echo "No results_merged.json found in $TARGET_DIR"
        return
    fi

    files_to_process=""

    if [ "$ALL_EXPERIMENTS" = true ]; then
        files_to_process="$candidates"
    elif [ "$ALL_EXP_PER_GROUP" = true ]; then
        # All experiments across all groups
        files_to_process="$candidates"
        echo "Evaluating all experiments across all groups (--all-exp)"
    else
        # Default: For each experiment group, find the latest by timestamp (parent directory name)
        latest_files=$(echo "$candidates" | python3 -c "
import sys
from pathlib import Path
from collections import defaultdict
lines = [l.strip() for l in sys.stdin if l.strip()]
if lines:
    groups = defaultdict(list)
    for p in lines:
        key = str(Path(p).parent.parent)
        groups[key].append(p)
    for key in sorted(groups):
        latest = max(groups[key], key=lambda p: Path(p).parent.name)
        print(latest)
")
        echo "Defaulting to most recent experiment per group (Use --all-exp to evaluate all):"
        echo "$latest_files"
        files_to_process="$latest_files"
    fi

    echo "$files_to_process" | while read -r input_file; do
        if [ -z "$input_file" ]; then continue; fi

        dir=$(dirname "$input_file")
        eval_file="${dir}/beq_evaluation.json"

        # Check if evaluation already exists (unless --force is used)
        if [ -f "$eval_file" ] && [ "$FORCE_MODE" = false ] && [ -z "$RESUME" ]; then
            echo "Skipping $dir (beq_evaluation.json exists, use --force to re-evaluate)"
            continue
        fi

        if [ -f "$eval_file" ] && [ "$FORCE_MODE" = true ]; then
            echo "Force mode: Re-evaluating $dir (removing existing beq_evaluation.json)"
            rm "$eval_file"
            rm -f "${dir}/beq_evaluation.summary.json"
        fi

        echo "Running BEq evaluation for $dir..."

        EXTRA_ARGS=""
        if [ "$LIMIT" -gt 0 ]; then
            EXTRA_ARGS="$EXTRA_ARGS --limit $LIMIT"
        fi
        if [ -n "$REPO_ROOT" ]; then
            EXTRA_ARGS="$EXTRA_ARGS --repo_root $REPO_ROOT"
        fi

        python3 src/evaluations/evaluate_beq.py \
            --input_path "$input_file" \
            --output_path "$eval_file" \
            --worker_dir "$WORKER_DIR" \
            --timeout "$TIMEOUT" \
            $RESUME $EXTRA_ARGS $VERBOSE

        if [ $? -eq 0 ]; then
            echo "BEq evaluation complete for $dir"
        else
            echo "Error in BEq evaluation for $dir"
        fi
    done
}

# Run evaluations
if [ -n "$ABLATION_TYPE" ]; then
    # Single ablation run
    if [ "$ABLATION_TYPE" == "standard" ]; then
        ROOT="${ROOT_DIR}/autoformalize"
    else
        ROOT="${ROOT_DIR}/autoformalize_${ABLATION_TYPE}"
    fi
    perform_beq_evaluation "$ROOT"
else
    # Run all matching autoformalize* directories
    if [ -d "${ROOT_DIR}/autoformalize" ]; then
        perform_beq_evaluation "${ROOT_DIR}/autoformalize"
    fi

    # Check other ablation directories
    find "${ROOT_DIR}" -maxdepth 1 -type d -name "autoformalize_*" | sort | while read -r dir; do
        perform_beq_evaluation "$dir"
    done
fi
