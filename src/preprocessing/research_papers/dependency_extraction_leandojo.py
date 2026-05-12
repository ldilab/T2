
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

from git import Repo

from typing import Optional

# Add project root to sys.path to import src.utils
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# Add LeanDojo to sys.path
LEAN_DOJO_PATH = PROJECT_ROOT.parent / "third_party/LeanDojo/src"
sys.path.append(str(LEAN_DOJO_PATH))
from lean_dojo import *
from lean_dojo.data_extraction.ast import (
    CommandDeclarationNode, IdentNode, CommandTheoremNode, 
    CommandDefinitionNode, CommandExampleNode, Node
)
from lean_dojo import TracedFile
from lean_dojo.data_extraction.lean import get_repo_type
import lean_dojo.data_extraction.ast as ast_module
from dataclasses import dataclass
from typing import Dict, Any, Optional

# Load GITHUB_ACCESS_TOKEN (and any other secrets) from a local .env file.
# .env is gitignored; see .env.example for the required variables.
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")
if not os.environ.get("GITHUB_ACCESS_TOKEN"):
    logging.warning(
        "GITHUB_ACCESS_TOKEN not set; LeanDojo may hit GitHub rate limits"
    )

# --- Monkey Patch for CommandSectionNode ---
@dataclass(frozen=True)
class PatchedCommandSectionNode(ast_module.Node):
    name: Optional[str]

    @classmethod
    def from_data(
        cls, node_data: Dict[str, Any], lean_file: ast_module.LeanFile
    ) -> "PatchedCommandSectionNode":
        # Relaxed assertion: assert node_data["info"] == "none"
        start, end = None, None
        children = ast_module._parse_children(node_data, lean_file)

        # Removed strict assertions on children count/types to prevent crashes
        # Original: assert len(children) == 2
        
        name = None
        # Try to find the name if possible, otherwise None
        if len(children) >= 2:
             if isinstance(children[1], ast_module.NullNode) and len(children[1].children) >= 1:
                  ident = children[1].children[0]
                  if isinstance(ident, ast_module.IdentNode):
                       name = ident.val

        return cls(lean_file, start, end, children, name)

logger.info("Applying monkey patch for CommandSectionNode")
ast_module.CommandSectionNode = PatchedCommandSectionNode
# -------------------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Context path logic
BASE_CONTEXT_PATH = PROJECT_ROOT / "data/existing_datasets/tmp"


# Helper functions for AST
def get_decl_node(node: Node):
    """Refine declaration node to specific type if wrapped."""
    if isinstance(node, CommandDeclarationNode):
        return node.children[1]
    return node

def extract_dependencies_from_decl(node: Node, traced_file: TracedFile):
    """Extract dependencies (premises) from a declaration node."""
    deps = set()
    
    def _callback(n: Node, _):
        if isinstance(n, IdentNode):
            if n.full_name and n.full_name != "[anonymous]":
                deps.add(n.full_name)
    
    node.traverse_preorder(_callback, node_cls=IdentNode)
    return list(deps)

def process_repo(repo_dir: Path, target_dir: Optional[Path], target_name: Optional[str]):
    # Check for lean-toolchain
    toolchain_path = repo_dir / "lean-toolchain"
    assert toolchain_path.exists(), "This directory is not Lean."
    
    # get hashcode of given repo
    # git_repo = Repo(repo_dir)
    # commit_hash = git_repo.head.commit.hexsha

    logger.info(f"Preparing project: {repo_dir}")
    # Use from_path for local repositories
    repo_obj = LeanGitRepo.from_path(repo_dir)

    print()
    try:
        try:
             # Run `lake build`
            build_result = subprocess.run(["lake", "build"], cwd=repo_dir, capture_output=True, text=True, check=False)
            
            if build_result.returncode != 0:
                logger.warning(f"Build failed for {repo_dir.name}:\n{build_result.stderr}")
            else:
                logger.info(f"Build successful for {repo_dir.name}")
        except Exception as e:
                logger.error(f"Build process exception for {repo_dir}: {e}")

        logger.info(f"Tracing repository: {repo_dir.name}")
        traced_repo = trace(repo_obj, build_deps=False)
        
        # Data structures
        code_metadata = {}
        dependency_graph = {}
        fullname_to_path = {}

        # Prepare filtering
        filter_path_obj = None
        if target_dir:
            filter_path_obj = target_dir.resolve()
            logger.info(f"Filtering for files in {filter_path_obj}")

        # Iterate through traced files
        for traced_file in traced_repo.traced_files:
             # Check filtering
            if filter_path_obj:
                original_file_path = repo_dir.resolve() / traced_file.path
                try:
                    original_file_path.relative_to(filter_path_obj)
                except ValueError:
                    # Not in target directory
                    continue
            
            rel_path = traced_file.path
            lean_file = traced_file.lean_file
            
            def _visit_decl(node: Node, _):
                if isinstance(node, CommandDeclarationNode):
                    if not node.name:
                        return # Anonymous
                        
                    full_name = node.full_name
                    if not full_name:
                         full_name = node.name 
                    
                    key = f"{rel_path}/{node.name}"
                    
                    # Store mapping
                    fullname_to_path[full_name] = str(rel_path)
                    
                    # Extract code
                    start, end = node.get_closure()
                    if start and end:
                        code = lean_file[start:end]
                    else:
                        code = ""
                        
                    # Determine type
                    decl_type = "unknown"
                    try:
                        inner = node.children[1]
                        type_name = inner.__class__.__name__
                        if "Theorem" in type_name or "Lemma" in type_name:
                            decl_type = "theorem"
                            is_prop = True
                        elif "Definition" in type_name:
                            decl_type = "definition"
                            is_prop = False 
                        elif "Example" in type_name:
                            decl_type = "example"
                            is_prop = False
                        else:
                            decl_type = type_name.replace("Command", "").replace("Node", "").lower()
                            is_prop = False
                    except:
                        is_prop = False

                    code_metadata[key] = {
                        "type": decl_type,
                        "is_prop": is_prop,
                        "code": code,
                        "full_name": full_name
                    }
                    
                    # Extract dependencies
                    deps = extract_dependencies_from_decl(node, traced_file)
                    dependency_graph[key] = deps # Store full names temporarily

            traced_file.ast.traverse_preorder(_visit_decl, node_cls=CommandDeclarationNode)

        # Refined map (resolve full names to keys where possible)
        fullname_to_key = { meta["full_name"]: key for key, meta in code_metadata.items() }
        
        final_dependency_graph = {}
        for key, deps in dependency_graph.items():
            resolved_deps = []
            for dep_fullname in deps:
                if dep_fullname in fullname_to_key:
                    resolved_deps.append(fullname_to_key[dep_fullname])
                else:
                    resolved_deps.append(dep_fullname) 
            final_dependency_graph[key] = resolved_deps

        return {
            "repository_name": repo_dir.name,
            "code_metadata": code_metadata,
            "dependency_graph": final_dependency_graph,
            "extraction_status": "success"
        }
    except Exception as e:
        logger.error(f"Failed to process repo {repo_dir.name}: {e}")
        import traceback
        traceback.print_exc()
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
    
    # Process one repo for testing
    res = process_repo(*raw_target_dirs[0])
    print(res["extraction_status"])
    if res["extraction_status"] == "success":
        # Save output for test
        out = dependency_dataset_dir / f"{res['repository_name']}.test.json"
        with open(out, "w") as f:
            json.dump(res, f, indent=2)
        print(f"Saved to {out}")

    # Restore full parallel execution if needed, but for now just test first.


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

    