#!/bin/bash

# Default Arguments
TYPE="research"
PROP_TYPE="prop"
MODEL=""

# Parse positional arguments if provided (up to 3: TYPE, PROP_TYPE, MODEL)
# We only consume them if they are not flags (start with --)
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
GROUND_TRUTH=false
ALL_EXPERIMENTS=false
ABLATION_TYPE=""

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
        --force) FORCE_MODE=true ;;
        --ground_truth) GROUND_TRUTH=true ;;
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
    esac
    shift
done

if [ "$TYPE" == "research" ]; then
     REPO_ROOT="data/research_papers/0raw/lean4"
else
    echo "Error: Invalid TYPE '$TYPE'. Valid options: existing, research."
    exit 1
fi

perform_evaluation() {
    local TARGET_ROOT=$1
    local TARGET_DIR="${TARGET_ROOT}/${TYPE}/${PROP_TYPE}"
    
    if [ -n "$MODEL" ]; then
        TARGET_DIR="${TARGET_DIR}/${MODEL}"
    fi
    RESULTS_MD="${TARGET_DIR}/results.md"

    if [ ! -d "$TARGET_DIR" ]; then
        echo "Warning: Target directory $TARGET_DIR does not exist. Skipping."
        return
    fi

    echo "=== Running Evaluation for $TARGET_DIR ==="

    if [ "$GROUND_TRUTH" = true ]; then
        echo "Evaluating Ground Truth..."
        eval_file="${TARGET_DIR}/evaluation_gt.json"

        if [ -f "$eval_file" ] && [ "$FORCE_MODE" = false ]; then
            echo "Skipping Ground Truth Evaluation ($eval_file exists, use --force to re-evaluate)"
        else
            if [ -f "$eval_file" ] && [ "$FORCE_MODE" = true ]; then
                echo "Force mode: Removing existing $eval_file"
                rm "$eval_file"
            fi

            python3 src/evaluations/evaluate_research.py \
                --input_path "$TARGET_DIR" \
                --output_path "$eval_file" \
                --repo_root "$REPO_ROOT" \
                --num_workers 8 \
                --eval_ground_truth
            
            if [ $? -eq 0 ]; then
                echo "Ground Truth Evaluation complete: $eval_file"
            else
                echo "Error evaluating Ground Truth"
            fi
        fi
        
    else
        echo "Scanning $TARGET_DIR for results..."
        
        # Find all candidates first
        # Limit depth to avoid slow searches
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
        else
             # Find the latest one by sorting timestamp (parent directory name)
             # Python snippet to sort by parent dir name and picking the last one
             latest_file=$(echo "$candidates" | python3 -c "
import sys
from pathlib import Path
lines = [l.strip() for l in sys.stdin if l.strip()]
if lines:
    # Sort by parent directory name (timestamp) 
    # This works for YYYYMMDD_HHMMSS
    latest = max(lines, key=lambda p: Path(p).parent.name)
    print(latest)
")
             echo "Defaulting to most recent experiment: $latest_file (Use --all to evaluate all)"
             files_to_process="$latest_file"
        fi

        echo "$files_to_process" | while read -r input_file; do
            if [ -z "$input_file" ]; then continue; fi
            
            dir=$(dirname "$input_file")
            eval_file="${dir}/evaluation.json"

            # Check if evaluation already exists (unless --force is used)
            if [ -f "$eval_file" ] && [ "$FORCE_MODE" = false ]; then
                echo "Skipping $dir (evaluation.json exists, use --force to re-evaluate)"
                continue
            fi

            if [ -f "$eval_file" ] && [ "$FORCE_MODE" = true ]; then
                echo "Force mode: Re-evaluating $dir (removing existing evaluation.json)"
                rm "$eval_file"
            fi

            echo "Evaluating results in $dir..."

            if [ "$TYPE" == "research" ]; then
                python3 src/evaluations/evaluate_research.py \
                    --input_path "$input_file" \
                    --output_path "$eval_file" \
                    --repo_root "$REPO_ROOT" \
                    --num_workers 8
            fi

            if [ $? -eq 0 ]; then
                echo "Evaluation complete for $dir"
            else
                echo "Error evaluating $dir"
            fi
        done
    fi

    # Generate Summary Table
    if [ -f "src/evaluations/gen_evaluation_summary.py" ]; then
        echo "Generating summary table..."
        python3 src/evaluations/gen_evaluation_summary.py \
            --target_dir "$TARGET_DIR" \
            --output_md "$RESULTS_MD"
    else
        echo "Summary generation script not found, skipping."
    fi
}


ROOT_DIR=${ROOT_DIR:-results}

if [ -n "$ABLATION_TYPE" ]; then
    # Single ablation run
    if [ "$ABLATION_TYPE" == "standard" ]; then
        ROOT="${ROOT_DIR}/autoformalize"
    else
        ROOT="${ROOT_DIR}/autoformalize_${ABLATION_TYPE}"
    fi
    perform_evaluation "$ROOT"
else
    # Run all matching autoformalize* directories
    # Check standard directory
    if [ -d "${ROOT_DIR}/autoformalize" ]; then
        perform_evaluation "${ROOT_DIR}/autoformalize"
    fi
    
    # Check other ablation directories
    find "${ROOT_DIR}" -maxdepth 1 -type d -name "autoformalize_*" | sort | while read -r dir; do
        perform_evaluation "$dir"
    done
fi
