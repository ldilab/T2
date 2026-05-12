#!/bin/bash

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <type> [prop_type] [model] [ablation_type]"
    echo "Types: existing, research"
    echo "Prop types: prop, noprop"
    echo "Ablation types: standard, wo_nl, wo_ref, wo_both"
    echo "Default prop_type: prop"
    echo "Default model: claude-sonnet-4-5"
    echo "Default ablation_type: standard"
    exit 1
fi

TYPE=$1
PROP_TYPE=${2:-prop}
MODEL=${3:-claude-sonnet-4-5}
ABLATION_TYPE=${4:-standard}

# Validate type and map to directory stub
if [ "$TYPE" == "existing" ]; then
    SUBDIR="exisiting_datasets"
elif [ "$TYPE" == "research" ]; then
    SUBDIR="research_papers"
else
    echo "Error: Invalid type. Choose from 'existing' or 'research'."
    exit 1
fi

# Validate prop_type
if [ "$PROP_TYPE" != "prop" ] && [ "$PROP_TYPE" != "noprop" ]; then
    echo "Error: Invalid prop_type. Choose from 'prop' or 'noprop'."
    exit 1
fi

# Determine config directory and experiment name based on ablation type
if [ "$ABLATION_TYPE" == "standard" ]; then
    CONFIG_ROOT="autoformalize"
else
    CONFIG_ROOT="autoformalize_${ABLATION_TYPE}"
fi

EXPERIMENT_NAME="${CONFIG_ROOT}/${TYPE}/${PROP_TYPE}"

DATETIME=$(date +'%Y%m%d_%H%M%S')

echo "Running autoformalization experiment for type: $TYPE ($SUBDIR/$PROP_TYPE) with model: $MODEL (Ablation: $ABLATION_TYPE)"

# New config path structure
TARGET_YAML="experiments/configs/${CONFIG_ROOT}/${SUBDIR}/${PROP_TYPE}/${MODEL}.yaml"

if [ ! -f "$TARGET_YAML" ]; then
    echo "Error: Config file not found at $TARGET_YAML"
    exit 1
fi

RUN_NAME="${EXPERIMENT_NAME}/${MODEL}/${DATETIME}"
RESULTS_DIR="results/${RUN_NAME}"

mkdir -p $RESULTS_DIR

export PYTHONPATH=$PYTHONPATH:$(pwd)/third_party/expand_langchain

# Use max_concurrency=20 as in the original scripts
python3 third_party/expand_langchain/run.py generator \
 --run_name=${RUN_NAME} \
 --config_path=${TARGET_YAML} \
 --max_concurrency=10 \
 --save_on=True \
 --rerun=False - run - merge_json - lark_message - exit
