# T2

[![arXiv](https://img.shields.io/badge/arXiv-2604.23698-b31b1b.svg?logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.23698)
[![GitHub](https://img.shields.io/badge/GitHub-T2-181717.svg?logo=github&logoColor=white)](https://github.com/ldilab/T2)
[![ACL 2026](https://img.shields.io/badge/ACL%202026-Industry%20Track-2C5BB4.svg)](https://2026.aclweb.org/)
[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)

**Benchmarking Testing in Automated Theorem Proving** — code, data, and experiment harness.

> Jongyoon Kim, Hojae Han, Seung-won Hwang.
> *ACL 2026 (Industry Track)*. [arXiv:2604.23698](https://arxiv.org/abs/2604.23698)

T proposes a test-based evaluation for formal theorem proving: a generated theorem is correct iff all its *successor theorems* compile. The benchmark covers 5 Lean 4 repositories — **2,206 problems**, ~41 successor theorems each.

## Setup

```bash
git clone --recurse-submodules <repo-url> T2 && cd T2
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e third_party/expand_langchain

# For Lean evaluation (optional):
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
(cd third_party/mathlib4 && lake exe cache get)
```

Configure LLM access by either pointing `experiments/llms/litellm/env.yaml` at your LiteLLM proxy or exporting provider API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …).

## Data

Shipped under `data/final/` (ref2 + nosorry variant):

| File | Records | |
|---|---:|---|
| `existing_datasets.{prop,noprop,all}.jsonl` | 2 / 120 / 122 | Numina, Kimina, CombiBench, FormalMATH |
| `research_papers.{prop,noprop,all}.jsonl`   | 57 / 1,817 / 1,874 | math2001, Directed-Topology-Lean-4, adele-ring, Untangle, WhitneyGraustein |

`prop` = paper's **Hard** subset (`Prop`-typed targets); `noprop` = non-`Prop` targets; `all` = union. Schema: `id`, `target_code`, `formal_language`, `natural_language`, `target_code_name`, `before_target_code`, `after_target_code`, `header`, `dataset_name`. `natural_language` is filled at the informalize step.

To regenerate from raw Lean repositories, run `src/setups/download_datasets.py`, then the per-track preprocessing scripts in `src/preprocessing/{existing_datasets,research_papers}/`.

## Reproducing experiments

```bash
# 1. Informalize (canonical results already in results/informalize/.../20260125_*/)
bash scripts/run_informalize.sh <track> <prop_type> claude-sonnet-4-5

# 2. Autoformalize
bash scripts/run_autoformalize.sh <track> <prop_type> <model> <ablation>

# 3. Evaluate
bash scripts/run_evaluate_server.sh <track> <prop_type> <model>      # pass@k via Lean server
bash scripts/run_evaluate_beq.sh    <track> <prop_type> <model>      # local BEq / BEq⁺
```

- `<track>` ∈ `existing`, `research`
- `<prop_type>` ∈ `prop`, `noprop`
- `<model>` = filename stem under `experiments/configs/autoformalize/<track>/<prop_type>/`
- `<ablation>` ∈ `standard`, `wo_nl`, `wo_ref`, `wo_both`

Aggregate metrics (one `evaluation.summary.json` per model × ablation × track) are shipped under `results/autoformalize*/`.

## License

Released under **Creative Commons Attribution 4.0 International (CC BY 4.0)** 

## Citation

```bibtex
@inproceedings{kim2026benchmarking,
  title     = {Benchmarking Testing in Automated Theorem Proving},
  author    = {Kim, Jongyoon and Han, Hojae and Hwang, Seung-won},
  booktitle = {Proceedings of the 64th Annual Meeting of the Association for Computational Linguistics (Industry Track)},
  year      = {2026},
  publisher = {Association for Computational Linguistics},
  url       = {https://arxiv.org/abs/2604.23698}
}
```
