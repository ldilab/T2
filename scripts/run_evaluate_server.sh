#!/bin/bash

# Arguments
TYPE=${1:-existing}
PROP_TYPE=${2:-noprop}
shift 2

MODEL=""
if [[ "$1" != --* ]] && [ -n "$1" ]; then
    MODEL=$1
    shift
fi

FORCE_MODE=false
GROUND_TRUTH_MODE=false
ABLATION_TYPE=""

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --force) FORCE_MODE=true ;;
        --ground_truth) GROUND_TRUTH_MODE=true ;;
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

if [ "$TYPE" == "existing" ]; then
    if [ "$PROP_TYPE" == "prop" ]; then
        ORIGINAL_DATA_PATH="data/final/existing_datasets.prop.jsonl"
    elif [ "$PROP_TYPE" == "noprop" ]; then
        ORIGINAL_DATA_PATH="data/final/existing_datasets.noprop.jsonl"
    else
        echo "Error: Invalid PROP_TYPE '$PROP_TYPE'. Valid options for existing: prop, noprop."
        exit 1
    fi
else
    echo "Error: Invalid TYPE '$TYPE'. Valid options: existing."
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
        mkdir -p "$TARGET_DIR"
        echo "Created target directory $TARGET_DIR"
    fi

    echo "=== Running Evaluation for $TARGET_DIR ==="
    echo "Using original data: $ORIGINAL_DATA_PATH"

    if [ "$GROUND_TRUTH_MODE" = true ]; then
        echo "Running GROUND TRUTH evaluation..."
        EVAL_FILE="${TARGET_DIR}/ground_truth_evaluation.json"
        
        python3 src/evaluations/evaluate_server.py \
            --output_path "$EVAL_FILE" \
            --dataset_path "$ORIGINAL_DATA_PATH" \
            --num_workers 20 \
            --task_type "$PROP_TYPE" \
            --eval_ground_truth
            
        if [ $? -eq 0 ]; then
            echo "Ground Truth Evaluation complete. Report: $EVAL_FILE"
        else
            echo "Error evaluating Ground Truth"
        fi
        return # Continue to next directory instead of exit
    fi

    echo "Scanning $TARGET_DIR for results..."

    find "$TARGET_DIR" -type f -name "results_merged.json" | while read -r input_file; do
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

        python3 src/evaluations/evaluate_server.py \
            --input_path "$input_file" \
            --output_path "$eval_file" \
            --dataset_path "$ORIGINAL_DATA_PATH" \
            --num_workers 20 \
            --task_type "$PROP_TYPE"

        if [ $? -eq 0 ]; then
            echo "Evaluation complete for $dir"
        else
            echo "Error evaluating $dir"
        fi
    done

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
