
import os
import subprocess
import shutil
import logging
import re
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class JixiaVersionManager:
    """
    Manages multiple versions of Jixia builds matching different Lean toolchains.
    
    Structure:
    third_party/jixia_envs/
      v4.10.0-rc2/
        ... (full jixia repo with build)
        .lake/build/bin/jixia
      v4.24.0/
        ...
    """
    
    # Map Lean versions to "Anchor Versions" (Environment Names)
    # The value is the VERSION string that will be the directory name in jixia_envs/
    # ANCHOR_MAPPING = {
    #     # 4.0 ~ 4.8.0 -> v4.8.0
    #     r"v4\.0\..*": "v4.8.0", 
    #     r"v4\.1\..*": "v4.8.0", 
    #     r"v4\.2\..*": "v4.8.0", 
    #     r"v4\.3\..*": "v4.8.0", 
    #     r"v4\.4\..*": "v4.8.0", 
    #     r"v4\.5\..*": "v4.8.0", 
    #     r"v4\.6\..*": "v4.8.0", 
    #     r"v4\.7\..*": "v4.8.0", 
    #     r"v4\.8\..*": "v4.8.0", 

    #     # 4.9, 4.10 -> v4.10.0
    #     r"v4\.9\..*": "v4.10.0", 
    #     r"v4\.10\..*": "v4.10.0", 
        
    #     # 4.11 -> v4.11.0-rc1
    #     r"v4\.11\..*": "v4.11.0-rc1",

    #     # 4.12, 4.13 -> v4.13.0
    #     r"v4\.12\..*": "v4.13.0", 
    #     r"v4\.13\..*": "v4.13.0", 

    #     # 4.14 ~ 4.16 -> v4.16.0
    #     r"v4\.14\..*": "v4.16.0", 
    #     r"v4\.15\..*": "v4.16.0", 
    #     r"v4\.16\..*": "v4.16.0", 

    #     # 4.17 ~ 4.19 -> v4.19.0
    #     r"v4\.17\..*": "v4.19.0", 
    #     r"v4\.18\..*": "v4.19.0", 
    #     r"v4\.19\..*": "v4.19.0", 

    #     # 4.20 ~ 4.24 -> v4.24.0
    #     r"v4\.20\..*": "v4.24.0", 
    #     r"v4\.21\..*": "v4.24.0", 
    #     r"v4\.22\..*": "v4.24.0", 
    #     r"v4\.23\..*": "v4.24.0", 
    #     r"v4\.24\..*": "v4.24.0",
        
    #     # Default fallback
    #     "default": "v4.24.0" 
    # }

    ANCHOR_MAPPING = {
        # 4.0 ~ 4.8.0 -> v4.8.0
        r"v4\.0\..*": "v4.8.0", 
        r"v4\.1\..*": "v4.8.0", 
        r"v4\.2\..*": "v4.8.0", 
        r"v4\.3\..*": "v4.8.0", 
        r"v4\.4\..*": "v4.8.0", 
        r"v4\.5\..*": "v4.8.0", 
        r"v4\.6\..*": "v4.8.0", 
        r"v4\.7\..*": "v4.8.0", 
        r"v4\.8\..*": "v4.8.0", 
        r"v4\.9\..*": "v4.8.0", 
        # 4.9, 4.10 -> v4.10.0
        
        r"v4\.10\..*": "v4.10.0", 
        
        # 4.11 -> v4.11.0-rc1
        r"v4\.11\..*": "v4.11.0-rc1",
        r"v4\.12\..*": "v4.11.0-rc1",

        # 4.12, 4.13 -> v4.13.0
        r"v4\.13\..*": "v4.13.0", 
        r"v4\.14\..*": "v4.13.0", 
        r"v4\.15\..*": "v4.13.0", 

        # 4.14 ~ 4.16 -> v4.16.0
        r"v4\.16\..*": "v4.16.0", 
        r"v4\.17\..*": "v4.16.0", 
        r"v4\.18\..*": "v4.16.0", 

        # 4.17 ~ 4.19 -> v4.19.0
        r"v4\.19\..*": "v4.19.0", 
        r"v4\.20\..*": "v4.19.0", 
        r"v4\.21\..*": "v4.19.0", 
        r"v4\.22\..*": "v4.19.0", 
        r"v4\.23\..*": "v4.19.0", 

        # 4.20 ~ 4.24 -> v4.24.0
        r"v4\.24\..*": "v4.24.0",
        r"v4\.25\..*": "v4.24.0",
        r"v4\.26\..*": "v4.24.0",
        r"v4\.27\..*": "v4.24.0",
        
        # Default fallback
        "default": "v4.24.0" 
    }


    # git refs for anchors (if different from version)
    # v4.8.0 (tag)
    # v4.10.0 (branch 'v4.10.0') -> actually just use 'v4.10.0' as ref
    # v4.11.0-rc1 (branch 'update_4.11-rc1') -> need explicit mapping if not tag
    ANCHOR_REFS = {
        "v4.11.0-rc1": "update_4.11-rc1",
        # Others match their version name as tag/branch usually
    }

    def __init__(self, 
                 base_jixia_path: str, 
                 envs_root: str = "third_party/jixia_envs"):
        self.base_jixia_path = Path(base_jixia_path).resolve()
        self.envs_root = Path(envs_root).resolve()
        self.envs_root.mkdir(parents=True, exist_ok=True)
        
    def get_jixia_binary(self, target_lean_version: str) -> str:
        """
        Routes the request to the appropriate Anchor Version environment.
        """
        anchor_version = self._resolve_anchor_version(target_lean_version)
        env_path = self.envs_root / anchor_version
        binary_path = env_path / ".lake/build/bin/jixia"
        
        if self._is_valid_build(binary_path):
            logger.debug(f"Using cached Jixia ({anchor_version}) for request {target_lean_version}")
            return str(binary_path)
            
        logger.info(f"Anchor environment {anchor_version} not found (requested by {target_lean_version}). Building...")
        self._build_env(env_path, anchor_version)
        
        if not self._is_valid_build(binary_path):
             raise RuntimeError(f"Failed to build Jixia for anchor {anchor_version}")
             
        return str(binary_path)

    def _is_valid_build(self, binary_path: Path) -> bool:
        return binary_path.exists() and os.access(binary_path, os.X_OK)

    def _resolve_anchor_version(self, lean_version: str) -> str:
        for pattern, anchor in self.ANCHOR_MAPPING.items():
            if pattern == "default": continue
            if re.match(pattern, lean_version):
                return anchor
        return self.ANCHOR_MAPPING["default"]

    def _build_env(self, env_path: Path, anchor_version: str):
        """
        Builds the Anchor Environment.
        Downloads source code for the specific version tag/branch.
        """
        if env_path.exists():
            shutil.rmtree(env_path)
        
        git_ref = self.ANCHOR_REFS.get(anchor_version, anchor_version)
        logger.info(f"Building env for {anchor_version} using ref {git_ref}")

        # 1. Acquire Source
        repo_url = "https://github.com/frenzymath/jixia.git"
        
        try:
            logger.info(f"Cloning {repo_url} (ref: {git_ref}) to {env_path}...")
            # We clone directly into env_path
            # Note: shallow clone for speed
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", git_ref, repo_url, str(env_path)], 
                check=True, 
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            # If tag fetch fails (maybe it's a commit hash or shallow fails on some refs), try full clone then checkout
            logger.warning(f"Shallow clone failed ({e.stderr.decode().strip()}), trying full clone...")
            subprocess.run(["git", "clone", repo_url, str(env_path)], check=True)
            subprocess.run(["git", "checkout", git_ref], cwd=env_path, check=True)
        
        # 2. Build
        logger.info(f"Building Jixia in {env_path}...")
        env = os.environ.copy()
        
        try:
            # subprocess.run(["lake", "update"], cwd=env_path, check=True, capture_output=True, env=env)
            subprocess.run(["lake", "build"], cwd=env_path, check=True, capture_output=True, env=env)
        except subprocess.CalledProcessError as e:
            logger.error(f"Build failed stderr: {e.stderr.decode()}")
            logger.error(f"Build failed stdout: {e.stdout.decode()}")
            raise RuntimeError(f"Jixia build failed for {anchor_version}")

