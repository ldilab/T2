
import sys
import logging
import json
import os
import shutil
from pathlib import Path
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import subprocess

from typing import Optional

# Add project root to sys.path to import src.utils
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.utils.dependency_extractor import DependencyExtractor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Context path logic
BASE_CONTEXT_PATH = PROJECT_ROOT / "data/existing_datasets/tmp"
extractor = DependencyExtractor()

def process_repo(repo_dir: Path, target_dir: Optional[Path], target_name: Optional[str]):
    try:
        # Check for lean-toolchain
        toolchain_path = repo_dir / "lean-toolchain"
        if not toolchain_path.exists():
            logger.info(f"Repo {repo_dir.name} missing toolchain. Using BASE_CONTEXT_PATH: {BASE_CONTEXT_PATH}")
            
            # Copy toolchain and lakefile/manifest from BASE_CONTEXT_PATH to repo_dir
            # This makes the repo directory a valid Lean project using the Mathlib environment
            try:
                shutil.copy2(BASE_CONTEXT_PATH / "lean-toolchain", repo_dir / "lean-toolchain")
                
                # Also copy lakefile if missing (needed for lake env)
                if not (repo_dir / "lakefile.lean").exists():
                    shutil.copy2(BASE_CONTEXT_PATH / "lakefile.lean", repo_dir / "lakefile.lean")
                    
                # And manifest if missing
                if not (repo_dir / "lake-manifest.json").exists() and (BASE_CONTEXT_PATH / "lake-manifest.json").exists():
                    shutil.copy2(BASE_CONTEXT_PATH / "lake-manifest.json", repo_dir / "lake-manifest.json")
                    
            except Exception as e:
                logger.error(f"Failed to copy context files to {repo_dir}: {e}")
                # Continue and see if extraction fails (it likely will if build relies on them)

        # check repo_dir 
        logger.info(f"Building project: {repo_dir}")
        try:
            # Run `lake build`
            build_result = subprocess.run(["lake", "build"], cwd=repo_dir, capture_output=True, text=True, check=False)
            
            if build_result.returncode != 0:
                logger.warning(f"Build failed for {repo_dir.name}:\n{build_result.stderr}")
            else:
                logger.info(f"Build successful for {repo_dir.name}")
                    
        except Exception as e:
                logger.error(f"Build process exception for {repo_dir}: {e}")

        logger.info(f"Extracting target directory: {target_dir}")
        code_map, dep_tree = extractor.extract_repository(str(repo_dir), target_dir=str(target_dir) if target_dir is not None else None)
        
        return {
            "repository_name": repo_dir.name,
            "code_metadata": code_map,
            "dependency_graph": dep_tree,
            "extraction_status": "success"
        }
    except Exception as e:
        logger.error(f"Failed to process repo {repo_dir.name}: {e}")
        return {
            "repository_name": repo_dir.name,
            "extraction_status": f"failed: {str(e)}",
            "code_metadata": {},
            "dependency_graph": {}
        }

if __name__ == "__main__":
    # Input: Raw repositories
    raw_dataset_dir = PROJECT_ROOT / "data/research_papers/0raw/lean4"
    # Output: Verified dependency data
    # Tuple of (lean-toolchain root dir, target lean file_dir)
    dependency_dataset_dir = PROJECT_ROOT / "data/research_papers/3dependency/lean4"
    dependency_dataset_dir.mkdir(parents=True, exist_ok=True)

    raw_target_dirs = [
        # (
        #     (raw_dataset_dir / "adele-ring_locally-compact"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "Directed-Topology-Lean-4"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "Duper_ITP_Paper_Artifact" / "duper"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "EmptyHexagonLean" / "Lean"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "lean-derived-categories"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "PrimeNumberTheoremAnd"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "Untangle"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "WhitneyGraustein"), None, None
        # ),
        (   # Mathlib/Analysis/FunctionalSpaces/SobolevInequality.lean
            (raw_dataset_dir / "mathlib4"), (raw_dataset_dir / "mathlib4" / "Mathlib/Analysis/FunctionalSpaces"), "SobolevInequality"

        ),
        (   # Mathlib/Topology/Category/Profinite/Nobeling
            (raw_dataset_dir / "mathlib4"), (raw_dataset_dir / "mathlib4" / "Mathlib/Topology/Category/Profinite/Nobeling"), "Nobeling"

        ),
    ]
    
    # Determine CPU count for workers
    num_workers = min(multiprocessing.cpu_count(), 1)
    print(f"Using {num_workers} parallel workers.")

    # Parallel execution
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        # Submit all tasks
        future_to_repo = {executor.submit(process_repo, d, target_dir, target_name): (d, target_dir, target_name) for d, target_dir, target_name in raw_target_dirs}
        
        for future in tqdm(as_completed(future_to_repo), total=len(raw_target_dirs), desc="Processing Repositories"):
            repo_dir, target_dir, target_name = future_to_repo[future]
            output_path = dependency_dataset_dir / f"{repo_dir.name}.json" if target_name is None else dependency_dataset_dir / f"{repo_dir.name}.{target_name}.json"
            
            try:
                result = future.result()
                with output_path.open("w") as fOut:
                    json.dump(result, fOut, indent=2)
            except Exception as e:
                 logger.error(f"Top level error processing {repo_dir}: {e}")

    