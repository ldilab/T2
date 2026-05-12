import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
# JIXIA_BINARY_PATH removed in favor of dynamic resolution

from src.utils.jixia_manager import JixiaVersionManager

class DependencyExtractor:
    def __init__(self, jixia_manager: Optional[JixiaVersionManager] = None):
        if jixia_manager:
            self.jixia_manager = jixia_manager
        else:
             # Default manager
             base_jixia = REPO_ROOT / "third_party/jixia"
             self.jixia_manager = JixiaVersionManager(str(base_jixia))

    def _find_project_root(self, file_path: Path) -> Optional[Path]:
        """
        Finds the root of the Lean project by looking for lakefile.lean or lake-manifest.json.
        """
        current = file_path.resolve().parent
        while current != current.parent:
            if (current / "lakefile.lean").exists() or (current / "lake-manifest.json").exists():
                return current
            current = current.parent
        return None

    def _join_name(self, name_parts: Any) -> str:
        """Helper to join list of name parts into a dot-separated string."""
        if isinstance(name_parts, list):
            return ".".join(str(p) for p in name_parts)
        return str(name_parts)

    def _analyze_file(self, file_path: str) -> Tuple[List[Any], List[Any]]:
        """
        Runs jixia and returns parsed (decl_data, sym_data).
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        project_root = self._find_project_root(path)
        cwd = project_root if project_root else path.parent

        # Prepare output files
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp_sym:
            sym_file = tmp_sym.name
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp_decl:
            decl_file = tmp_decl.name

        try:
            # Determine Lean version and get appropriate binary
            lean_version = "v4.24.0"
            toolchain_file = project_root / "lean-toolchain" if project_root else (path.parent / "lean-toolchain")
            
            if toolchain_file.exists():
                content = toolchain_file.read_text().strip()
                # Format: leanprover/lean4:v4.24.0-rc2
                if ":" in content:
                    lean_version = content.split(":")[-1].strip()
            
            jixia_binary = self.jixia_manager.get_jixia_binary(lean_version)
            
            cmd = ["lake", "env", jixia_binary, "-s", sym_file, "-d", decl_file, str(path)]

            
            # Helper to run command
            result = subprocess.run(
                cmd, 
                cwd=cwd, 
                capture_output=True, 
                text=True, 
                check=False
            )

            if result.returncode != 0:
                logger.error(f"Jixia failed: {result.stderr}")
                raise RuntimeError(f"Jixia failed: {result.stderr}")

            if not os.path.exists(decl_file) or os.path.getsize(decl_file) == 0:
                 raise RuntimeError("Jixia did not produce decl file.")
            with open(decl_file, 'r') as f:
                decl_data = json.load(f)

            if not os.path.exists(sym_file) or os.path.getsize(sym_file) == 0:
                 raise RuntimeError("Jixia did not produce sym file.")
            with open(sym_file, 'r') as f:
                sym_data = json.load(f)
                
            if not sym_data:
                logger.warning(f"Jixia produced empty sym_data for {path}")
                logger.warning(f"CMD: {' '.join(cmd)}")
                logger.warning(f"STDERR: {result.stderr}")
                logger.warning(f"STDOUT: {result.stdout}")
                
            with open(path, 'rb') as f:
                file_content_bytes = f.read()

            return decl_data, sym_data, file_content_bytes

        finally:
            if os.path.exists(sym_file):
                os.remove(sym_file)
            if os.path.exists(decl_file):
                os.remove(decl_file)

    def _process_analysis_results(self, decl_data: List[Any], sym_data: List[Any], file_content: Optional[bytes] = None) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]], Set[str]]:
        """
        Process the raw analysis data into useful structures.
        Returns:
            - code_map: dict of {name: {type, is_prop, code}}
            - adj_list: dict of {name: [dependencies]} (raw adjacency)
            - valid_props: set of names that are original propositions
        """
        # Metadata map from sym_data
        meta_map = {}
        for item in sym_data:
            name = self._join_name(item.get("name", []))
            meta_map[name] = {
                "type": item.get("kind", "unknown"),
                "is_prop": item.get("isProp", False)
            }

        # Original blocks and Code Map
        code_map = {}
        original_blocks = set()
        

        for item in decl_data:
            if not isinstance(item, dict):
                continue
            
            # Legacy/v4.11 Jixia Support
            id_val = item.get("id", {})
            ranges = []
            
            if isinstance(id_val, list) and len(id_val) == 2:
                 # Legacy v4.8: id is range [start, end]
                 is_original = True
                 ranges.append(id_val)
            elif isinstance(id_val, dict):
                 is_original = id_val.get("original", False)
                 # v4.11: id has "range"
                 if id_rng := id_val.get("range"):
                     if isinstance(id_rng, list) and len(id_rng) == 2:
                         ranges.append(id_rng)
            else:
                 is_original = False

            if is_original:
                 name = self._join_name(item.get("name", []))
                 
                 # Extract code
                 # Check for 'pp' (newer jixia)
                 code = item.get("ref", {}).get("pp", "")
                 
                 # Check for 'ref.range' (v4.11 jixia)
                 ref_range = item.get("ref", {}).get("range")
                 
                 if not code and file_content:
                     if ref_range and isinstance(ref_range, list) and len(ref_range) == 2:
                         start, end = ref_range
                         if start >= 0 and end <= len(file_content):
                             code = file_content[start:end].decode('utf-8', errors='replace')
                     
                     elif ranges:
                         # Fallback to reconstructing from other ranges if ref.range missing
                         type_rng = item.get("type")
                         if isinstance(type_rng, list) and len(type_rng) == 2:
                             ranges.append(type_rng)
                         elif isinstance(type_rng, dict) and (rng := type_rng.get("range")):
                             ranges.append(rng)
                             
                         val_rng = item.get("value")
                         if isinstance(val_rng, list) and len(val_rng) == 2:
                             ranges.append(val_rng)
                         elif isinstance(val_rng, dict) and (rng := val_rng.get("range")):
                             ranges.append(rng)
                         
                         if ranges:
                             starts = [r[0] for r in ranges]
                             ends = [r[1] for r in ranges]
                             min_start = min(starts)
                             max_end = max(ends)
                             if min_start >= 0 and max_end <= len(file_content):
                                 code = file_content[min_start:max_end].decode('utf-8', errors='replace')
                 
                 original_blocks.add(name)
                 
                 meta = meta_map.get(name, {"type": "unknown", "is_prop": False})
                 code_map[name] = {
                     "type": meta["type"],
                     "is_prop": meta["is_prop"],
                     "code": code
                 }

        # Valid Propositions (Original + Prop)
        valid_props = set()
        for item in sym_data:
             if not isinstance(item, dict):
                  continue
             name = self._join_name(item.get("name", []))
             if name in original_blocks and item.get("isProp", False):
                 valid_props.add(name)

        # Build Adjacency List for Valid Props
        adj_list = {}
        # Pre-fill all valid props
        for p in valid_props:
            adj_list[p] = []

        for item in sym_data:
            name = self._join_name(item.get("name", []))
            if name not in valid_props:
                continue
            
            refs = set()
            all_refs = item.get("typeReferences", []) or []
            val_refs = item.get("valueReferences", []) or []
            all_refs.extend(val_refs)
            
            for ref_parts in all_refs:
                ref_name = self._join_name(ref_parts)

                
                refs.add(ref_name)
            
            adj_list[name] = list(refs)
            
        return code_map, adj_list, valid_props

    def _build_tree(self, adj_list: Dict[str, List[str]], valid_nodes: Set[str]) -> Dict[str, Any]:
        """
        Builds the nested dictionary tree from an adjacency list and a set of valid nodes.
        Only includes dependencies that are in valid_nodes.
        """
        def build_node(node_name, path):
            if node_name in path:
                return {} # Cycle detected
            
            children = {}
            new_path = path | {node_name}
            
            deps = adj_list.get(node_name, [])
            for dep in deps:
                if dep in valid_nodes:
                    children[dep] = build_node(dep, new_path)
            
            return children

        final_tree = {}
        for node in valid_nodes:
            final_tree[node] = build_node(node, set())
            
        return final_tree
    
    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------

    def extract_code(self, file_path: str) -> Dict[str, Dict[str, Any]]:
        """
        Returns a dictionary mapping block names to metadata/code.
        """
        decl, sym, content = self._analyze_file(file_path)
        code_map, _, _ = self._process_analysis_results(decl, sym, content)
        return code_map

    def extract_dependencies(self, file_path: str) -> Dict[str, Any]:
        """
        Returns a nested dictionary representing the dependency tree.
        """
        decl, sym, content = self._analyze_file(file_path)
        _, adj_list, valid_props = self._process_analysis_results(decl, sym, content)
        return self._build_tree(adj_list, valid_props)

    def extract_from_string(self, code: str, project_context: Optional[str] = None) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        """
        Analyzes a string of Lean code.
        Returns (code_map, dependency_tree).
        """
        # Generate a random module name to satisfy Lean's module system
        # Use a temporary directory for the file
        import random
        import string
        
        rand_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        module_name = f"TmpData{rand_suffix}"
        file_name = f"{module_name}.lean"
        
        full_code = code
        
        tmp_dir = tempfile.gettempdir()

        cwd = Path.cwd()
        if project_context:
            cwd = Path(project_context).resolve()
            if not cwd.exists():
                 raise FileNotFoundError(f"Project context path not found: {project_context}")
        
        # Create temp_extraction directory inside project context to satisfy lake root requirements
        temp_dir = cwd / "temp_extraction"
        temp_dir.mkdir(exist_ok=True)
        
        file_path = temp_dir / file_name
        olean_path = temp_dir / f"{module_name}.olean"

        # Write code to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(full_code)
        
        try:
            path = file_path.resolve()

            lean_bin = "lean"
            compile_cmd = ["lake", "env", lean_bin, "-o", str(olean_path), str(path)]
            # logger.info(f"Compiling: {' '.join(compile_cmd)}")
        
            compile_result = subprocess.run(
                compile_cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if compile_result.returncode != 0:
                # If compilation fails, we can't extract dependency properly likely
                logger.error(f"Compilation failed for {file_name}")
                logger.error(f"Command: {' '.join(compile_cmd)}")
                logger.error(f"STDOUT: {compile_result.stdout}")
                logger.error(f"STDERR: {compile_result.stderr}")
                logger.error(f"Code Snippet: {full_code[:200]}...")
                raise RuntimeError(f"Compilation failed: {compile_result.stderr}")

            # Prepare output files
            with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp_sym:
                sym_file = tmp_sym.name
            with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp_decl:
                decl_file = tmp_decl.name

            try:
                # Command: lake env <jixia> -s <sym_file> -d <decl_file> <input_file>
                input_path_arg = str(path)
                
                lean_version = "v4.24.0"
                if cwd:
                    toolchain_file = cwd / "lean-toolchain"
                    if toolchain_file.exists():
                        content = toolchain_file.read_text().strip()
                        if ":" in content:
                            lean_version = content.split(":")[-1].strip()
                
                jixia_binary = self.jixia_manager.get_jixia_binary(lean_version)
                
                cmd = ["lake", "env", jixia_binary, "-s", sym_file, "-d", decl_file, input_path_arg]
                
                # logger.info(f"Running Jixia (String): {' '.join(cmd)} in {cwd}")
                
                result = subprocess.run(
                    cmd, 
                    cwd=cwd, 
                    capture_output=True, 
                    text=True, 
                    check=False
                )

                if result.returncode != 0:
                    logger.error(f"Jixia failed: {result.stderr}")
                    raise RuntimeError(f"Jixia failed: {result.stderr}")

                if not os.path.exists(decl_file) or os.path.getsize(decl_file) == 0:
                     raise RuntimeError("Jixia did not produce decl file.")
                with open(decl_file, 'r') as f:
                    decl_data = json.load(f)

                if not os.path.exists(sym_file) or os.path.getsize(sym_file) == 0:
                     raise RuntimeError("Jixia did not produce sym file.")
                with open(sym_file, 'r') as f:
                    sym_data = json.load(f)

            finally:
                if os.path.exists(sym_file):
                    os.remove(sym_file)
                if os.path.exists(decl_file):
                    os.remove(decl_file)
            
            with open(file_path, 'rb') as f:
                tmp_content = f.read()
            
            code_map, adj_list, valid_props = self._process_analysis_results(decl_data, sym_data, tmp_content)
            dep_tree = self._build_tree(adj_list, valid_props)
            return code_map, dep_tree
            
        finally:
            if file_path.exists():
                os.remove(file_path)
            if olean_path.exists():
                os.remove(olean_path)

    def extract_repository(self, repo_path: str, target_dir: Optional[str] = None) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        """
        Analyzes all .lean files in a repository.
        Returns merged (code_map, dependency_tree).
        Keys are prefixed with relative file path: "{rel_path}/{name}"
        """
        root = Path(repo_path).resolve()
        if not root.exists():
             raise FileNotFoundError(f"Repository not found: {repo_path}")
        
        logger.info(f"Extracting repository: {repo_path}")
        
        if target_dir:
            search_path = str(Path(target_dir).resolve())
            if not Path(search_path).exists():
                 raise FileNotFoundError(f"Target directory not found: {target_dir}")
            logger.info(f"Scoping extraction to: {search_path}")
        else:
            search_path = repo_path

        lean_files = []
        for r, dirs, files in os.walk(search_path):
            # Exclude .lake (and lake-packages if present separately)
            if '.lake' in dirs:
                dirs.remove('.lake')
            if 'lake-packages' in dirs:
                dirs.remove('lake-packages')
                
            for file in files:
                if file.endswith(".lean"):
                    lean_files.append(Path(r) / file)
        
        logger.info(f"Found {len(lean_files)} Lean files in {repo_path}")
        
        file_results = []
        name_to_file = {}
        
        for file_path in lean_files:
            if file_path.name == "lakefile.lean":
                continue
                
            try:
                rel_path = file_path.relative_to(root)
                decl, sym, content = self._analyze_file(str(file_path))
                c_map, adj, props = self._process_analysis_results(decl, sym, content)
                
                # Register definitions to this file
                for name in c_map:
                    name_to_file[name] = str(rel_path)
                
                file_results.append((str(rel_path), c_map, adj, props))
                
            except Exception as e:
                logger.error(f"Failed to analyze {file_path}: {e}")
                # Continue processing other files even if one fails
                continue
        
        # Merge results with path prefixing
        all_code_map = {}
        all_adj_list = {}
        all_valid_props = set()
        
        for rel_path, c_map, adj, props in file_results:
            for name, meta in c_map.items():
                new_key = f"{rel_path}/{name}"
                all_code_map[new_key] = meta
                
            for name in props:
                all_valid_props.add(f"{rel_path}/{name}")
                
            for name, deps in adj.items():
                new_key = f"{rel_path}/{name}"
                new_deps = []
                for dep in deps:
                    # Resolve dependency path
                    if dep in name_to_file:
                        dep_file = name_to_file[dep]
                        new_deps.append(f"{dep_file}/{dep}")
                    else:
                        # External or not found, keep original
                        # (These won't be in valid_props so won't appear in tree usually)
                        new_deps.append(dep)
                all_adj_list[new_key] = new_deps
        
        # Build unified tree from merged data
        dep_tree = self._build_tree(all_adj_list, all_valid_props)
        return all_code_map, dep_tree

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract Lean 4 dependencies using Jixia")
    parser.add_argument("path", help="Path to the Lean file OR directory")
    parser.add_argument("--string", help="Analyze raw string (treat path as project context if provided)", action="store_true")
    parser.add_argument("--code", help="Raw code input when using --string", default="")
    
    args = parser.parse_args()
    extractor = DependencyExtractor()

    try:
        if args.string:
            # path argument is treated as context path if code is provided via flag, 
            # or if we are piping stdin? For simplicity let's stick to Python API mainly.
            # CLI usage for string: python ... --string --code "..." <context_path>
            code_map, tree = extractor.extract_from_string(args.code, args.path if args.path != "." else None)
            print(json.dumps({"code": code_map, "dependencies": tree}, indent=2))
            
        elif os.path.isdir(args.path):
            code_map, tree = extractor.extract_repository(args.path)
            print(json.dumps({"code": code_map, "dependencies": tree}, indent=2))
            
        else:
            # Single file
            # If user wants full output (code + dep), we haven't exposed a combined method for single file yet in CLI
            # But we can split calls
            code_map = extractor.extract_code(args.path)
            tree = extractor.extract_dependencies(args.path)
            print(json.dumps({"code": code_map, "dependencies": tree}, indent=2))
            
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        exit(1)
