import os

TARGET_DIRS = [
    "results/autoformalize",
    "results/autoformalize_wo_both",
    "results/autoformalize_wo_nl",
    "results/autoformalize_wo_ref",

    "results/prev/autoformalize",
    "results/prev/autoformalize_wo_both",
    "results/prev/autoformalize_wo_nl",
    "results/prev/autoformalize_wo_ref",

    "results/prev/n=32/autoformalize",
    "results/prev/n=32/autoformalize_wo_nl",
    "results/prev/n=32/autoformalize_wo_ref",
]

def parse_and_filter_table(file_path):
    if not os.path.exists(file_path):
        # We can return a placeholder or just "File not found."
        return f"File not found: {file_path}"

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    header = ""
    separator = ""
    rows = []
    
    in_table = False
    
    # We assume standard markdown table format
    # | model | date | ...
    
    best_rows = {} # model -> {date, line}

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        
        parts = [p.strip() for p in stripped.strip("|").split("|")]
        if len(parts) < 2: 
            continue

        if "실험 모델" in parts[0] or "Model" in parts[0]:
            header = line
            continue
        
        if set(parts[0]) <= {'-', ' ', ':'}:
            separator = line
            in_table = True
            continue
            
        if not in_table:
            continue

        # Data row
        model = parts[0]
        date_str = parts[1]
        
        # Determine unique key for model. Just the name is enough.
        # Compare dates strings (YYYYMMDD_HHMMSS format sorts lexically correctly)
        if model not in best_rows:
            best_rows[model] = {"date": date_str, "line": line}
        else:
            if date_str > best_rows[model]["date"]:
                 best_rows[model] = {"date": date_str, "line": line}
    
    # Sort by model name for display
    sorted_models = sorted(best_rows.keys())
    
    if not header:
        return f"No valid data block found in {file_path}."

    result_lines = []
    result_lines.append(header.strip())
    result_lines.append(separator.strip())
    for m in sorted_models:
        result_lines.append(best_rows[m]['line'].strip())
        
    return "\n".join(result_lines)

def generate_summary_for_dir(base_dir):
    if not os.path.exists(base_dir):
        print(f"Skipping {base_dir} (Directory not found)")
        return

    output_file = os.path.join(base_dir, "recent_results_summary.md")
    
    paths = {
        "existing": {
            "prop": os.path.join(base_dir, "existing/prop/results.md"),
            "noprop": os.path.join(base_dir, "existing/noprop/results.md"),
        },
        "research": {
            "prop": os.path.join(base_dir, "research/prop/results.md"),
            "noprop": os.path.join(base_dir, "research/noprop/results.md"),
        }
    }
    
    content = ""
    
    # Order: existing -> prop, noprop, then research -> prop, noprop
    
    # 1. Existing
    content += "# existing\n"
    
    ## prop
    content += "## prop\n"
    table_prop = parse_and_filter_table(paths["existing"]["prop"])
    content += table_prop + "\n\n"
    
    ## noprop
    content += "## noprop\n"
    table_noprop = parse_and_filter_table(paths["existing"]["noprop"])
    content += table_noprop + "\n\n"
    
    # 2. Research
    content += "# research\n"
    
    ## prop
    content += "## prop\n"
    table_res_prop = parse_and_filter_table(paths["research"]["prop"])
    content += table_res_prop + "\n\n"
    
    ## noprop
    content += "## noprop\n"
    table_res_noprop = parse_and_filter_table(paths["research"]["noprop"])
    content += table_res_noprop + "\n" # End of file
    
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully generated {output_file}")
    except Exception as e:
        print(f"Failed to write {output_file}: {e}")

def main():
    print("Starting summary generation for specified directories...")
    for target_dir in TARGET_DIRS:
        generate_summary_for_dir(target_dir)

if __name__ == "__main__":
    main()
