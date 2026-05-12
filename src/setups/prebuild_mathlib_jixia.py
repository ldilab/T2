
import sys
from pathlib import Path
import logging

# Repo Root (<repo-root>)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(REPO_ROOT))

from src.utils.jixia_manager import JixiaVersionManager

logging.basicConfig(level=logging.INFO)

def prebuild():
    # Jixia is in third_party/jixia
    base_jixia = REPO_ROOT / "third_party/jixia"
    # Jixia environments cache
    env_cache = REPO_ROOT / "third_party/jixia_envs"
       
    manager = JixiaVersionManager(str(base_jixia))
    
    # List of all Anchor Versions to pre-build
    anchor_versions = [
        "v4.8.0",
        "v4.10.0",
        "v4.11.0-rc1",
        "v4.13.0",
        "v4.16.0",
        "v4.19.0",
        "v4.24.0"
    ]
    
    failed_builds = []
    
    for version in anchor_versions:
        try:
            print(f"=== Specifying Jixia env for {version} ===")
            binary = manager.get_jixia_binary(version)
            print(f"SUCCESS: {version} -> {binary}")
        except Exception as e:
            print(f"FAILURE: {version} - {e}")
            failed_builds.append(version)
            
    if failed_builds:
        print(f"The following versions failed to build: {failed_builds}")
        sys.exit(1)
    else:
        print("All Jixia environments built successfully.")

if __name__ == "__main__":
    prebuild()
