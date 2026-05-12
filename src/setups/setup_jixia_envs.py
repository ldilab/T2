
import sys
import os
import logging
from pathlib import Path

# Add src to path
# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

# Workspace root for finding third_party
WORKSPACE_ROOT = PROJECT_ROOT.parent

from src.utils.jixia_manager import JixiaVersionManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    base_jixia = WORKSPACE_ROOT / "third_party/jixia"
    envs_root = WORKSPACE_ROOT / "third_party/jixia_envs"
    
    manager = JixiaVersionManager(str(base_jixia), str(envs_root))
    
    # List of versions to pre-build
    # These cover major epochs of Lean 4
    versions = [
        "v4.8.0",
        "v4.11.0",
        "v4.13.0",
        "v4.16.0",
        "v4.19.0",
        "v4.24.0"
    ]
    
    logger.info(f"Starting Jixia pre-warming for versions: {versions}")
    
    results = {}
    
    for version in versions:
        logger.info(f"--- Processing {version} ---")
        try:
            bin_path = manager.get_jixia_binary(version)
            logger.info(f"SUCCESS: {version} -> {bin_path}")
            results[version] = "Success"
        except Exception as e:
            logger.error(f"FAILURE: {version} -> {e}")
            results[version] = f"Failed: {e}"
            
    logger.info("\n=== Summary ===")
    for ver, status in results.items():
        logger.info(f"{ver}: {status}")

if __name__ == "__main__":
    main()
