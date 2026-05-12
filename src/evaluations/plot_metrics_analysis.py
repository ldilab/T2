
import os
import matplotlib.pyplot as plt
import datetime
import math

# Metadata for models (Approximate sizes in Billions, Release Dates)
# If exact size is unknown, reasonable estimates are used for visualization.
MODEL_METADATA = {
    # OpenAI
    "openai-gpt-5": {"size": 2000, "date": "2025-11", "family": "OpenAI GPT-5"}, # Hypothetical
    "openai-gpt-5-mini": {"size": 200, "date": "2025-11", "family": "OpenAI GPT-5"},
    "openai-gpt-5-nano": {"size": 20, "date": "2025-11", "family": "OpenAI GPT-5"},
    "gpt-4o": {"size": 1000, "date": "2024-05", "family": "OpenAI GPT-4o"},
    "gpt-4o-mini": {"size": 8, "date": "2024-07", "family": "OpenAI GPT-4o"},
    "openai-gpt-oss-120b": {"size": 120, "date": "2025-10", "family": "OpenAI OSS"},
    "openai-gpt-oss-20b": {"size": 20, "date": "2025-10", "family": "OpenAI OSS"},
    
    # Anthropic
    "claude-sonnet-4-5": {"size": 500, "date": "2025-06", "family": "Claude Sonnet"}, # Hypothetical
    "claude-4-sonnet": {"size": 200, "date": "2025-01", "family": "Claude Sonnet"}, # Hypothetical
    "claude-3-7-sonnet": {"size": 100, "date": "2024-10", "family": "Claude Sonnet"}, # Hypothetical
    "claude-3-5-sonnet": {"size": 70, "date": "2024-06", "family": "Claude Sonnet"},
    
    # Meta
    "llama3.1-405b": {"size": 405, "date": "2024-07", "family": "Llama 3.1"},
    "llama3.1-70b": {"size": 70, "date": "2024-07", "family": "Llama 3.1"},
    "llama3.1-8b": {"size": 8, "date": "2024-07", "family": "Llama 3.1"},
    
    # DeepSeek
    "DeepSeek-r1": {"size": 67, "date": "2025-01", "family": "DeepSeek"},
    "DeepSeek-prover-v2-7b": {"size": 7, "date": "2024-06", "family": "DeepSeek"},
    
    # Others / Research
    "Goedel-prover-v2-32b": {"size": 32, "date": "2024-10", "family": "Goedel"},
    "Goedel-prover-v2-8b": {"size": 8, "date": "2024-10", "family": "Goedel"},
    "BFS-prover-v2-32b": {"size": 32, "date": "2024-12", "family": "Other"},
    "Kimina-Prover-Distill-8B": {"size": 8, "date": "2024-11", "family": "Kimina"},
    "Kimina-Autoformalizer-7B": {"size": 7, "date": "2024-11", "family": "Kimina"},
    "Herald_translator": {"size": 0.5, "date": "2024-01", "family": "Other"}, # Unclear, small
    "Real-prover": {"size": 7, "date": "2024-09", "family": "Other"},
}

def get_metadata(model_name):
    # Try exact match first
    for k, v in MODEL_METADATA.items():
        if k.lower() == model_name.lower():
            return v
    
    # Try partial match (longest match wins)
    best_match = None
    best_len = 0
    for k, v in MODEL_METADATA.items():
        if k.lower() in model_name.lower() or model_name.lower() in k.lower():
            if len(k) > best_len:
                best_match = v
                best_len = len(k)
                
    if best_match:
        return best_match
        
    # Default fallback
    return {"size": None, "date": None, "family": "Unknown"}

def parse_date(date_str):
    try:
        return datetime.datetime.strptime(date_str, "%Y-%m")
    except:
        return None

def plot_scatter_generic(data_points, x_getter, y_getter, output_path, title, xlabel, ylabel, log_x=False, is_date_x=False, color_map=None):
    plt.figure(figsize=(12, 8)) # Increased size for better label visibility
    
    valid_points = []
    families = set()
    
    for d in data_points:
        x = x_getter(d)
        y = y_getter(d)
        if x is not None and y is not None:
            # Infer family if not present in main metadata dict (safety fallback is "Unknown")
            family = d.get('family', 'Unknown')
            valid_points.append({'x': x, 'y': y, 'model': d['model'], 'family': family})
            families.add(family)
            
    if not valid_points:
        plt.close()
        return

    # Draw Frontier lines (Group by Family and sort by X)
    for fam in families:
        if fam == 'Unknown' or fam == 'Other':
            continue
            
        fam_points = [p for p in valid_points if p['family'] == fam]
        if len(fam_points) < 2:
            continue
            
        # Sort by X
        fam_points.sort(key=lambda p: p['x'])
        
        fxs = [p['x'] for p in fam_points]
        fys = [p['y'] for p in fam_points]
        
        # Color line same as family if color_map provided, else gray
        line_color = color_map.get(fam, 'gray') if color_map else 'gray'
        plt.plot(fxs, fys, linestyle='--', color=line_color, alpha=0.5, linewidth=1)


    xs = [p['x'] for p in valid_points]
    ys = [p['y'] for p in valid_points]
    names = [p['model'] for p in valid_points]
    
    # Determine colors
    if color_map:
        c_list = [color_map.get(p['family'], 'royalblue') for p in valid_points]
        plt.scatter(xs, ys, c=c_list, alpha=0.9, s=80, edgecolors='k', zorder=10)
    else:
        plt.scatter(xs, ys, c='royalblue', alpha=0.7, s=80, edgecolors='k', zorder=10)
    
    if log_x:
        plt.xscale('log')
        
    if is_date_x:
        import matplotlib.dates as mdates
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.gcf().autofmt_xdate()

    # Annotation with better visibility
    for i, name in enumerate(names):
        # Basic smart offset: checks if point is too close to boundaries
        xytext = (5, 5)
        # Alternate text position to reduce overlap probability
        if i % 2 == 0:
            xytext = (5, -12)
        if i % 3 == 0:
            xytext = (-5, 10)
            
        plt.annotate(name, (xs[i], ys[i]), 
                     xytext=xytext, 
                     textcoords='offset points', 
                     fontsize=9, 
                     alpha=0.9,
                     bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.5),
                     zorder=15)

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True, linestyle='--', alpha=0.5, which='both')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()

def plot_metrics(best_results, output_dir):
    """
    Main function to generate separate plots for all metrics.
    """
    # Extract data points for Full Proving (S+P)
    task_focus = "Full Proving"
    
    data_points = []
    
    for model, tasks in best_results.items():
        if task_focus in tasks:
            t_data = tasks[task_focus]
            # Attach metadata
            meta = get_metadata(model)
            
            # Prepare date object if available
            dt = parse_date(meta['date']) if meta['date'] else None
            
            data_points.append({
                'model': model,
                'pass': t_data.get('pass_rate', 0),
                'em': t_data.get('em_rate', 0),
                'bleu': t_data.get('bleu_score', 0),
                'size': meta['size'],
                'date': dt,
                'family': meta.get('family', 'Unknown')
            })
            
    if not data_points:
        print(f"No data found for task '{task_focus}'. Skipping plots.")
        return

    
    # Global: Determine Standard Family Order and Color Map
    # Order by Max Pass Rate descending
    family_max_pass = {}
    
    unique_families = set()
    for d in data_points:
        fam = d.get('family', 'Unknown')
        unique_families.add(fam)
        if fam not in family_max_pass:
            family_max_pass[fam] = 0
        if d['pass'] > family_max_pass[fam]:
            family_max_pass[fam] = d['pass']
            
    # Sort families: Other/Unknown last, then by pass rate desc
    def family_sort_key(fam):
        is_other = (fam == 'Other' or fam == 'Unknown')
        return (is_other, -family_max_pass.get(fam, 0))
        
    sorted_families = sorted(list(unique_families), key=family_sort_key)
    
    # Assign consistent colors
    # Use a fixed palette
    PALETTE = ['royalblue', 'darkorange', 'forestgreen', 'firebrick', 'mediumpurple', 'sienna', 'hotpink', 'gray', 'teal', 'navy', 'olive']
    color_map = {fam: PALETTE[i % len(PALETTE)] for i, fam in enumerate(sorted_families)}
    
    print(f"Family Order: {sorted_families}")

    # 1. Correlation Plots (Metirc vs Pass)
    # BLEU vs Pass
    plot_scatter_generic(
        data_points,
        lambda d: d['bleu'],
        lambda d: d['pass'],
        os.path.join(output_dir, 'correlation_bleu_pass.png'),
        'BLEU Score vs Pass Rate',
        'BLEU Score',
        'Pass@1 (%)',
        color_map=color_map 
    )
    
    # EM vs Pass
    plot_scatter_generic(
        data_points,
        lambda d: d['em'],
        lambda d: d['pass'],
        os.path.join(output_dir, 'correlation_em_pass.png'),
        'Exact Match (EM) vs Pass Rate',
        'Exact Match (%)',
        'Pass@1 (%)',
        color_map=color_map
    )

    # 2. Scaling Law Plots (Size vs Metric)
    metrics = [
        ('pass', 'Pass@1 (%)'),
        ('bleu', 'BLEU Score'),
        ('em', 'Exact Match (%)')
    ]
    
    for key, label in metrics:
        plot_scatter_generic(
            data_points,
            lambda d: d['size'],
            lambda d: d[key],
            os.path.join(output_dir, f'scaling_{key}.png'),
            f'Model Size vs {label}',
            'Model Parameters (Billions) - Log Scale',
            label,
            log_x=True,
            color_map=color_map
        )

    # 3. Timeline Plots (Date vs Metric)
    for key, label in metrics:
        plot_scatter_generic(
            data_points,
            lambda d: d['date'],
            lambda d: d[key],
            os.path.join(output_dir, f'timeline_{key}.png'),
            f'Release Date vs {label}',
            'Release Date',
            label,
            is_date_x=True,
            color_map=color_map
        )
    
    # 4. Family Comparison (Grouped Bar Charts per Metric)
    # Pass Rate
    plot_grouped_bar_for_metric(
        data_points, 
        'pass', 
        'Pass@1 (%)', 
        os.path.join(output_dir, 'bar_grouped_pass.png'),
        sorted_families=sorted_families,
        color_map=color_map
    )
    # BLEU
    plot_grouped_bar_for_metric(
        data_points, 
        'bleu', 
        'BLEU Score', 
        os.path.join(output_dir, 'bar_grouped_bleu.png'),
        sorted_families=sorted_families,
        color_map=color_map
    )
    # EM
    plot_grouped_bar_for_metric(
        data_points, 
        'em', 
        'Exact Match (%)', 
        os.path.join(output_dir, 'bar_grouped_em.png'),
        sorted_families=sorted_families,
        color_map=color_map
    )
    
    print(f"Generated metric plots in {output_dir}")

def plot_grouped_bar_for_metric(data_points, metric_key, metric_label, output_path, sorted_families, color_map):
    """
    Bar chart showing metric for *each model*, grouped by family.
    Uses consistent sorted_families order and color_map.
    """
    # Group by family
    family_groups = {}
    for d in data_points:
        fam = d.get('family', 'Unknown')
        if fam not in family_groups:
            family_groups[fam] = []
        family_groups[fam].append(d)
        
    if not family_groups:
        return
    
    # Prepare plotting data
    family_labels = [] # For legend
    
    x_pos = 0
    x_ticks = []
    x_tick_labels = []
    
    plt.figure(figsize=(14, 8))
    
    # Iterate using the GLOBAL valid sorted families
    for fam in sorted_families:
        if fam not in family_groups:
            continue
            
        # Sort models within family: Smallest/Oldest -> Largest/Newest
        # Primary sort: Size (asc), Secondary sort: Date (asc)
        def sort_key_models(m):
            # Handle None values
            s = m.get('size') if m.get('size') is not None else -1
            dt = m.get('date') if m.get('date') is not None else datetime.datetime.min
            return (s, dt)
            
        models = sorted(family_groups[fam], key=sort_key_models)
        
        fam_color = color_map.get(fam, 'gray')
        
        for m in models:
            plt.bar(x_pos, m[metric_key], color=fam_color, label=fam if fam not in family_labels else "")
            if fam not in family_labels:
                family_labels.append(fam)
                
            x_ticks.append(x_pos)
            x_tick_labels.append(m['model'])
            x_pos += 1
            
        # Add a gap between families
        x_pos += 1
        
    plt.ylabel(metric_label, fontsize=12)
    plt.title(f'Model Performance by Family: {metric_label}', fontsize=14)
    plt.xticks(x_ticks, x_tick_labels, rotation=45, ha='right', fontsize=9)
    plt.grid(True, axis='y', linestyle='--', alpha=0.3)
    
    # Legend
    plt.legend(title="Model Family")
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()

