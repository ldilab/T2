import sys
import os
import json
import logging
import multiprocessing
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
from typing import Optional

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# Add LeanDojo to sys.path
LEAN_DOJO_PATH = PROJECT_ROOT.parent / "third_party/LeanDojo/src"
sys.path.append(str(LEAN_DOJO_PATH))

# Load GITHUB_ACCESS_TOKEN (and any other secrets) from a local .env file.
# .env is gitignored; see .env.example for the required variables.
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")
if not os.environ.get("GITHUB_ACCESS_TOKEN"):
    logging.warning(
        "GITHUB_ACCESS_TOKEN not set; LeanDojo may hit GitHub rate limits"
    )

try:
    from lean_dojo import LeanGitRepo, trace, TracedRepo, TracedFile, Pos
    from lean_dojo.data_extraction.ast import (
        CommandDeclarationNode, IdentNode, CommandTheoremNode, 
        CommandDefinitionNode, CommandExampleNode, Node
    )
except ImportError as e:
    print(f"Failed to import LeanDojo: {e}")
    print(f"sys.path: {sys.path}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Output directory
OUTPUT_DIR = PROJECT_ROOT / "data/research_papers/1dependency.leandojo/lean4"

def get_decl_node(node: Node):
    """Refine declaration node to specific type if wrapped."""
    # CommandDeclarationNode wraps the specific declaration
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

def process_repo(repo_dir: Path, target_dir: Optional[Path] = None, target_name: Optional[str] = None):
    temp_git_dir = None
    patched_extractor_path = None
    try:
        logger.info(f"Processing repo: {repo_dir.name}")
        
        # --- Runtime Patch for ExtractData.lean ---
        # Fix compatibility issues with older Lean versions (e.g. v4.10.0)
        import lean_dojo
        import lean_dojo.data_extraction.lean as lean_module
        
        # Patch get_repo_type to force REMOTE for GitHub URLs
        original_get_repo_type = lean_module.get_repo_type
        def patched_get_repo_type(url):
            res = original_get_repo_type(url)
            if res == lean_module.RepoType.GITHUB:
                return lean_module.RepoType.REMOTE
            return res
        lean_module.get_repo_type = patched_get_repo_type
        
        # Patch get_lean4_commit_from_config to use git ls-remote instead of GitHub API
        def patched_get_lean4_commit_from_config(config_dict):
            logger.info("Using patched get_lean4_commit_from_config (git ls-remote)")
            content = config_dict["content"].strip()
            version = lean_module.get_lean4_version_from_config(content)
            
            # Use git ls-remote to get hash
            cmd = f"git ls-remote https://github.com/leanprover/lean4 refs/tags/{version}"
            try:
                # We can use original_execute if available or subprocess
                output = subprocess.check_output(cmd, shell=True).decode()
                if output:
                    return output.split()[0]
            except Exception as e:
                logger.warning(f"git ls-remote failed for {version}: {e}")
            
            # Fallback or try resolving as branch/commit?
            if "nightly" in version:
                 cmd = f"git ls-remote https://github.com/leanprover/lean4-nightly {version}"
                 try:
                    output = subprocess.check_output(cmd, shell=True).decode()
                    if output:
                        return output.split()[0]
                 except:
                    pass
            
            # If input is already a hash?
            if lean_module.is_commit_hash(version):
                return version

            raise ValueError(f"Could not resolve commit for {version}")

        lean_module.get_lean4_commit_from_config = patched_get_lean4_commit_from_config
        
        # Patch url_to_repo to avoid cloning huge repos (Mathlib) just for checking commits
        class FakeCommit:
            def __init__(self, sha):
                self.hexsha = sha

        class FakeRepo:
            def __init__(self, url):
                self.url = url
                self.working_dir = "/tmp/fake_repo" # Dummy path
                import os
                os.makedirs(self.working_dir, exist_ok=True)
                # Ensure dummy toolchain exists
                tc_path = os.path.join(self.working_dir, "lean-toolchain")
                if not os.path.exists(tc_path):
                     with open(tc_path, "w") as f:
                         f.write("leanprover/lean4:v4.10.0")
            
            def commit(self, label):
                # Resolve label using git ls-remote
                logger.info(f"Resolving {label} for {self.url} using git ls-remote")
                # If label is already a hash, return it?
                if lean_module.is_commit_hash(label):
                     return FakeCommit(label)
                
                cmd = f"git ls-remote {self.url} {label}"
                try:
                    output = subprocess.check_output(cmd, shell=True).decode()
                    if output:
                        return FakeCommit(output.split()[0])
                    # Try checking tags/heads explicitly
                    cmd = f"git ls-remote {self.url} refs/tags/{label}"
                    output = subprocess.check_output(cmd, shell=True).decode()
                    if output:
                        return FakeCommit(output.split()[0])
                    cmd = f"git ls-remote {self.url} refs/heads/{label}"
                    output = subprocess.check_output(cmd, shell=True).decode()
                    if output:
                         return FakeCommit(output.split()[0])
                except:
                    pass
                raise ValueError(f"Could not resolve {label} for {self.url}")
            
            @property
            def head(self):
                # Need HEAD commit?
                # Use HEAD
                return self.commit("HEAD")

        # Patch _to_commit_hash to avoid API limits on GitHubRepo
        original_to_commit_hash = lean_module._to_commit_hash
        def patched_to_commit_hash(repo, label):
             # Use ls-remote for EVERYTHING to avoid API limits
             # Extract URL
             url = None
             if hasattr(repo, "clone_url"): # PyGithub Repository
                 url = repo.clone_url
             elif hasattr(repo, "url"):
                 url = repo.url
             
             if url:
                 logger.info(f"Using git ls-remote for {url} {label} to avoid API")
                 cmd = f"git ls-remote {url} {label}"
                 try:
                     output = subprocess.check_output(cmd, shell=True).decode()
                     if output:
                         return output.split()[0]
                     # Try refs/tags and refs/heads
                     for prefix in ["refs/tags/", "refs/heads/"]:
                         cmd = f"git ls-remote {url} {prefix}{label}"
                         output = subprocess.check_output(cmd, shell=True).decode()
                         if output:
                             return output.split()[0]
                 except Exception as e:
                     logger.warning(f"git ls-remote failed for {url}: {e}")
             
             # Fallback to original (which might hit API or work for local)
             return original_to_commit_hash(repo, label)

        lean_module._to_commit_hash = patched_to_commit_hash

        # Disable FakeRepo injection - we need real deps to build execution environment
        original_url_to_repo = lean_module.url_to_repo
        def patched_url_to_repo(url, num_retries=2, repo_type=None, tmp_dir=None):
             # Just pass through to original (LeanGitRepo/GitHubRepo)
             # But our _to_commit_hash patch will handle the API limits
             return original_url_to_repo(url, num_retries, repo_type, tmp_dir)
             
        lean_module.url_to_repo = patched_url_to_repo
        lean_module._to_commit_hash = patched_to_commit_hash

        import lean_dojo.utils
        import subprocess
        
        # Monkey patch execute to debug errors
        original_execute = lean_dojo.utils.execute
        def patched_execute(cmd, capture_output=False):
            try:
                # Force capture to print on error
                res = original_execute(cmd, capture_output=True)
                
                # Log success output for debugging
                stdout_str, stderr_str = res
                with open("/tmp/leandojo_success.log", "a") as f:
                    f.write(f"Command: {cmd}\n")
                    f.write(f"Stdout: {stdout_str}\n")
                    f.write(f"Stderr: {stderr_str}\n")
                    f.write("-" * 40 + "\n")

                if capture_output:
                    return res
                
                # If caller didn't want capture, print what we captured
                import sys
                stdout, stderr = res
                if stdout:
                    print(stdout, end='')
                if stderr:
                    print(stderr, file=sys.stderr, end='')
                    
                return None
            except subprocess.CalledProcessError as e:
                import sys
                with open("/tmp/leandojo_error.log", "a") as f:
                    f.write(f"Command failed: {cmd}\n")
                    f.write(f"Stdout: {e.stdout.decode() if e.stdout else ''}\n")
                    f.write(f"Stderr: {e.stderr.decode() if e.stderr else ''}\n")
                    f.write("-" * 40 + "\n")
                raise e
        
        lean_dojo.utils.execute = patched_execute

        import lean_dojo.data_extraction.trace as trace_module
        import tempfile
        import re
        
        # Patch execute in trace module effectively
        trace_module.execute = patched_execute

        def apply_patches(content, fix_get_find, fix_substring):
            original_shouldProcess = (
                'def shouldProcess (path : FilePath) (noDeps : Bool) : IO Bool := do\n'
                '  if (\u2190 path.isDir) \u2228 path.extension != "lean" then\n'
                '    return false\n'
                '\n'
                '  let cwd \u2190 IO.currentDir\n'
                '  let some relativePath := Path.relativeTo path cwd |\n'
                '    throw $ IO.userError s!"Invalid path: {path}"\n'
                '\n'
                '  if noDeps \u2227 Path.isRelativeTo relativePath Path.packagesDir then\n'
                '    return false\n'
                '\n'
                '  let some oleanPath := Path.toBuildDir "lib/lean" relativePath "olean" |\n'
                '    throw $ IO.userError s!"Invalid path: {path}"\n'
                '  return \u2190 oleanPath.pathExists'
            )

            u_and = "\u2227"
            u_or = "\u2228"
            patched_shouldProcess = (
                'def shouldProcess (path : FilePath) (noDeps : Bool) : IO Bool := do\n'
                '  IO.println s!"DEBUG: Checking {path}"\n'
                '  path.isDir >>= fun isDir => do\n'
                f'    if isDir {u_or} path.extension != "lean" then\n'
                '       IO.println "DEBUG: Skipped (dir/non-lean)"\n'
                '       return false\n'
                '    else\n'
                '       IO.currentDir >>= fun cwd => do\n'
                '          let some relativePath := Path.relativeTo path cwd | throw $ IO.userError s!"Invalid path: {path}"\n'
                f'          if noDeps {u_and} Path.isRelativeTo relativePath Path.packagesDir then\n'
                '            IO.println "DEBUG: Skipped (dependency)"\n'
                '            return false\n'
                '          else\n'
                '            let some oleanPath := Path.toBuildDir "lib/lean" relativePath "olean" | throw $ IO.userError s!"Invalid path: {path}"\n'
                '            oleanPath.pathExists >>= fun fileExists => do\n'
                '              IO.println s!"DEBUG: oleanPath: {oleanPath}, exists: {fileExists}"\n'
                '              return fileExists'
            )

            # Patch 1: HashMap.get? -> HashMap.find?
            if fix_get_find and "env.const2ModIdx.get?" in content:
                logger.info("Patching ExtractData.lean: get? -> find?")
                content = content.replace("env.const2ModIdx.get?", "env.const2ModIdx.find?")
            
            # Patch 2: Substring deprecation fixes
            if fix_substring:
                logger.info("Patching ExtractData.lean: Commenting out deprecated ToJson instances")
                content = content.replace("instance : ToJson Substring where", "/- instance : ToJson Substring where")
                content = content.replace("toJson s := toJson s.toString", "toJson s := toJson s.toString -/")
                content = content.replace("instance : ToJson String.Pos where", "/- instance : ToJson String.Pos where")
                content = content.replace("toJson n := toJson n.1", "toJson n := toJson n.1 -/")

            # Patch 3: TSyntax mismatch (Recommended always)
            if "IO.FS.writeFile dep_path (← getImports header)" in content:
                 content = content.replace("IO.FS.writeFile dep_path (← getImports header)", 
                                        "IO.FS.writeFile dep_path (← getImports (unsafeCast header))")

            # Patch 4: Debug Prints
            if "unsafe def main (args : List String) : IO Unit := do" in content:
                content = content.replace("unsafe def main (args : List String) : IO Unit := do",
                                          'unsafe def main (args : List String) : IO Unit := do\n  IO.println "DEBUG: Executing main"')
            
            if "def processAllFiles (noDeps : Bool) : IO Unit := do" in content:
                 content = content.replace("def processAllFiles (noDeps : Bool) : IO Unit := do",
                                           'def processAllFiles (noDeps : Bool) : IO Unit := do\n    IO.println "DEBUG: Inside processAllFiles"')
            
            # Patch 5: Robust shouldProcess replacement
            if original_shouldProcess in content:
                logger.info("Patching ExtractData.lean: Replacing entire shouldProcess function (Exact Match)")
                content = content.replace(original_shouldProcess, patched_shouldProcess)
            else:
                # Regex Robust Match
                start_match = re.search(r"def\s+shouldProcess\s*\(.*?\)\s*\(.*?\)\s*:\s*IO\s*Bool\s*:=\s*do", content)
                end_match = re.search(r"def\s+processAllFiles", content)
                if start_match and end_match:
                     logger.info("Patching ExtractData.lean: Regex Slice Replacement for shouldProcess")
                     start_idx = start_match.start()
                     end_idx = end_match.start()
                     content = content[:start_idx] + patched_shouldProcess + "\n\n" + content[end_idx:]
                else:
                     logger.warning("Could not find shouldProcess signature/end for valid replacement.")

            # Patch 6: Subprocess Output
            if "| Except.ok _ => pure ()" in content:
                 content = content.replace("| Except.ok _ => pure ()", 
                                           '| Except.ok output => IO.println s!"Subprocess output for {path}: {output}"')
            return content

        def patched_data_extractor(fix_get_find=True, fix_substring=False):
            original_path = trace_module.LEAN4_DATA_EXTRACTOR_PATH
            
            try:
                installed_path = Path(trace_module.__file__).resolve().parent / "ExtractData.lean"
            except Exception as e:
                logger.error(f"Failed to find installed ExtractData.lean: {e}")
                return None
            
            if installed_path.exists():
                with open(installed_path, 'r') as f:
                    content = f.read()
                
                content = apply_patches(content, fix_get_find, fix_substring)
                
                patched_temp_dir = tempfile.mkdtemp(prefix='leandojo_patch_')
                patched_file = Path(patched_temp_dir) / "ExtractData.lean"
                with open(patched_file, 'w') as f:
                    f.write(content)
                return patched_file
            return None
        # ------------------------------------------
        # ------------------------------------------
        
        working_repo_path = repo_dir.resolve()
        
        # Initialize LeanGitRepo
        repo = LeanGitRepo.from_path(working_repo_path)
        
        
        # Retry loop for different patch configurations
        # Configs: (fix_get_find, fix_substring)
        # 1. (True, False) -> Old Lean (Default start - for lean-derived-categories etc)
        # 2. (False, True) -> New Lean (for PrimeNumberTheoremAnd)
        # 3. (False, False) -> Original (Least invasive)
        # 4. (True, True) -> Hybrid (Try everything)
        
        configs = [
            (True, False), 
            (False, True),
            (False, False),
            (True, True)
        ]
        
        success = False
        last_error = None
        
        for fix_get_find, fix_substring in configs:
            try:
                logger.info(f"Attempting trace with patches: fix_get_find={fix_get_find}, fix_substring={fix_substring}")
                
                patched_path = patched_data_extractor(fix_get_find=fix_get_find, fix_substring=fix_substring)
                if not patched_path:
                    logger.error("Could not locate ExtractData.lean to patch")
                    return None
                    
                trace_module.LEAN4_DATA_EXTRACTOR_PATH = patched_path
                
                traced_repo = trace(repo, build_deps=True)
                success = True
                logger.info(f"Successfully traced repo: {repo.name}")
                break
            except Exception as e:
                logger.warning(f"Trace attempt failed with config ({fix_get_find}, {fix_substring}): {e}")
                last_error = e
        
        if not success:
            logger.error(f"Failed to trace {repo.name} after all attempts.")
            if last_error:
                raise last_error
            return None
        
        code_metadata = {}
        dependency_graph = {}
        
        # Map full_name to rel_path for internal linking
        fullname_to_path = {}
        
        # Prepare filtering
        filter_path_obj = None
        if target_dir:
            filter_path_obj = target_dir.resolve()
            logger.info(f"Filtering for files in {filter_path_obj}")

        # First pass: Collect all declarations and populate metadata
        for traced_file in traced_repo.traced_files:
            # Check filtering
            if filter_path_obj:
                original_file_path = repo_dir.resolve() / traced_file.path
                # Check if original_file_path is relative to filter_path_obj
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
                        return # Anonymous or failed parse
                        
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

        # Refined map
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
        logger.error(f"Failed to process {repo_dir.name}: {e}", exc_info=True)
        return {
            "repository_name": repo_dir.name,
            "extraction_status": f"failed: {str(e)}",
            "code_metadata": {},
            "dependency_graph": {}
        }
    finally:
        if temp_git_dir and temp_git_dir.exists():
            import shutil
            try:
                shutil.rmtree(temp_git_dir)
            except:
                pass
        # if patched_extractor_path and patched_extractor_path.exists():
        #     try:
        #         # Try to remove the parent temp dir if we created it
        #         # But wait, patched_extractor_path is just the file.
        #         # Using global vars is messy.
        #         # Since we used mkdtemp, we should remove the dir.
        #         shutil.rmtree(patched_extractor_path.parent)
        #     except:
        #         pass

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=str, default=None, help="Specific repo name to filter from target list")
    args = parser.parse_args()

    # Configuration from existing dataset script
    raw_dataset_dir = PROJECT_ROOT / "data/research_papers/0raw/lean4"
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True) # Ensure output dir exists

    # (repo_dir, target_dir, target_name_suffix)
    # (
    #     (raw_dataset_dir / "Duper_ITP_Paper_Artifact" / "duper"), None, None
    #     # (raw_dataset_dir / "Duper_ITP_Paper_Artifact"), None, None
    # ),
    # (
    #     (raw_dataset_dir / "EmptyHexagonLean" / "Lean"), None, None
    #     # (raw_dataset_dir / "EmptyHexagonLean"), None, None
    # ),
    # (
    #     (raw_dataset_dir / "Untangle"), None, None
    # ),
    raw_target_dirs = [
        # (
        #     (raw_dataset_dir / "adele-ring_locally-compact"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "Directed-Topology-Lean-4"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "lean-derived-categories"), None, None
        # ),
        # (
        #     (raw_dataset_dir / "PrimeNumberTheoremAnd"), None, None
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

    # Filter if arg provided
    if args.repo:
        raw_target_dirs = [item for item in raw_target_dirs if item[0].name == args.repo or args.repo in str(item[0])]
        if not raw_target_dirs:
            print(f"No matching repo found for {args.repo}")
            sys.exit(1)

    # Filter out already successfully processed repos
    final_target_dirs = []
    for d, t_dir, t_name in raw_target_dirs:
        # Determine output filename
        out_name = d.name
        if t_name:
             out_name += f".{t_name}"
        out_name += ".json"
        
        output_path = OUTPUT_DIR / out_name
        
        should_skip = False
        if output_path.exists():
            try:
                with open(output_path, "r") as f:
                    data = json.load(f)
                    if data.get("extraction_status") == "success":
                         should_skip = True
                         logger.info(f"Skipping {d.name} (already successful)")
            except Exception as e:
                logger.warning(f"Failed to read existing output for {d.name}, reprocessing: {e}")
        
        if not should_skip:
            final_target_dirs.append((d, t_dir, t_name))
    
    raw_target_dirs = final_target_dirs

    logger.info(f"Using {OUTPUT_DIR} for output")
    logger.info(f"Processing {len(raw_target_dirs)} repositories")

    num_workers = min(multiprocessing.cpu_count(), 1) 
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_repo = {executor.submit(process_repo, d, t_dir, t_name): (d, t_dir, t_name) for d, t_dir, t_name in raw_target_dirs}
        
        for future in tqdm(as_completed(future_to_repo), total=len(raw_target_dirs)):
            repo_dir, target_dir, target_name = future_to_repo[future]
            
            # Determine output filename
            # If target_name is set, append it
            out_name = repo_dir.name
            if target_name:
                 out_name += f".{target_name}"
            out_name += ".json"
            
            output_path = OUTPUT_DIR / out_name
            
            try:
                result = future.result()
                with open(output_path, "w") as f:
                    json.dump(result, f, indent=2)
            except Exception as e:
                logger.error(f"Top level error for {repo_dir.name}: {e}")

