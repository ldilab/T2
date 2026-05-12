import os
import json
import re

SOURCE_DIR = "data/research_papers/3dependency/lean4"
OUTPUT_DIR = "data/research_papers/3dependency.type/lean4"

# Regex to find the command.
# Matches optional attributes @[...], optional modifiers, then the command.
COMMAND_PATTERN = re.compile(
    r"^(?:\s*@\[[^\]]*\])*\s*"  # Skip attributes @[...]
    r"(?:(?:\bprotected\b|\bnoncomputable\b|\bprivate\b|\bunsafe\b|\bpartial\b|\bscoped\b|\blocal\b)\s+)*" # Skip modifiers
    r"(?P<command>\btheorem\b|\blemma\b|\bdef\b|\babbrev\b|\bexample\b|\bstructure\b|\binductive\b|\bclass\b|\binstance\b|\baxiom\b|\bopaque\b|\bconstant\b)",
    re.MULTILINE
)

PROP_COMMANDS = {"theorem", "lemma", "axiom"}

def infer_type_and_prop(code_snippet):
    """
    Parses the code snippet to determine the command type and is_prop status.
    Returns (type_str, is_prop_bool) or (None, None) if not found.
    """
    # Use search instead of match to find the command even if it's not on the very first line 
    # (e.g. if there are doc comments /-- ... -/)
    match = COMMAND_PATTERN.search(code_snippet)
    if match:
        cmd = match.group("command")
        is_prop = cmd in PROP_COMMANDS
        return cmd, is_prop
    return None, None

def process_file(filename):
    src_path = os.path.join(SOURCE_DIR, filename)
    dst_path = os.path.join(OUTPUT_DIR, filename)
    
    try:
        with open(src_path, 'r') as f:
            data = json.load(f)
        
        updated_count = 0
        if 'code_metadata' in data:
            for key, meta in data['code_metadata'].items():
                code = meta.get('code', "")
                if not code:
                    continue
                
                cmd, is_prop = infer_type_and_prop(code)
                if cmd:
                    meta['type'] = cmd
                    meta['is_prop'] = is_prop
                    updated_count += 1
        
        # Always write the file to the new directory, even if 0 updates, 
        # so we have a complete dataset in the new location.
        with open(dst_path, 'w') as f:
            json.dump(data, f, indent=2)
            
        if updated_count > 0:
            print(f"Processed {filename}: {updated_count} updates (saved to {dst_path})")
        else:
            print(f"Processed {filename}: No updates found (saved to {dst_path})")
            
    except Exception as e:
        print(f"Error processing {filename}: {e}")

def main():
    if not os.path.exists(SOURCE_DIR):
        print(f"Source directory not found: {SOURCE_DIR}")
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Created output directory: {OUTPUT_DIR}")
        
    files = [f for f in os.listdir(SOURCE_DIR) if f.endswith(".json")]
    print(f"Found {len(files)} JSON files.")
    
    for filename in sorted(files):
        process_file(filename)

if __name__ == "__main__":
    main()
