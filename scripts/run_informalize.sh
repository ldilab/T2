#!/bin/bash

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <type> [prop_type] [model]"
    echo "Types: existing, research"
    echo "Prop types: prop, noprop"
    echo "Default prop_type: prop"
    echo "Default model: claude-sonnet-4-5"
    exit 1
fi

TYPE=$1
PROP_TYPE=${2:-prop}
MODEL=${3:-claude-sonnet-4-5}

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

DATETIME=$(date +'%Y%m%d_%H%M%S')
EXPERIMENT_NAME="informalize/${TYPE}/${PROP_TYPE}"

echo "Running informalization experiment for type: $TYPE ($SUBDIR/$PROP_TYPE) with model: $MODEL"

# New config path structure with prop/noprop subdirectory
TARGET_YAML="experiments/configs/informalize/${SUBDIR}/${PROP_TYPE}/${MODEL}.yaml"

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
 --max_concurrency=100 \
 --save_on=True \
 --rerun=False - run - merge_json - lark_message - exit
