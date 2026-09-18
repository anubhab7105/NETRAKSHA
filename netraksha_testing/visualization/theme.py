"""Visualization theme and common charting utilities."""

from __future__ import annotations

import platform
from pathlib import Path

try:
    import matplotlib.pyplot as plt
    import matplotlib as mpl
    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False


# Professional HSL-derived color palette
COLORS = {
    "primary": "#3B82F6",     # Blue
    "secondary": "#8B5CF6",   # Purple
    "success": "#10B981",     # Green
    "warning": "#F59E0B",     # Amber
    "danger": "#EF4444",      # Red
    "info": "#06B6D4",        # Cyan
    "bg_dark": "#1E293B",     # Slate 800
    "bg_light": "#F8FAFC",    # Slate 50
    "text_dark": "#0F172A",   # Slate 900
    "text_light": "#F1F5F9",  # Slate 100
    "grid": "#E2E8F0",        # Slate 200
    "grid_dark": "#334155",   # Slate 700
}


def setup_theme(dark_mode: bool = False) -> None:
    """Apply professional matplotlib theme."""
    if not _HAS_MATPLOTLIB:
        return
        
    bg = COLORS["bg_dark"] if dark_mode else COLORS["bg_light"]
    fg = COLORS["text_light"] if dark_mode else COLORS["text_dark"]
    grid = COLORS["grid_dark"] if dark_mode else COLORS["grid"]
    
    # Try to use a nice modern font if available
    fonts = ['Inter', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif']
    if platform.system() == "Windows":
         fonts = ['Segoe UI', 'Arial', 'sans-serif']
         
    plt.style.use('default')
    
    mpl.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': fonts,
        'figure.facecolor': bg,
        'axes.facecolor': bg,
        'axes.edgecolor': grid,
        'axes.labelcolor': fg,
        'axes.titleweight': 'bold',
        'axes.titlecolor': fg,
        'xtick.color': fg,
        'ytick.color': fg,
        'grid.color': grid,
        'grid.alpha': 0.7,
        'text.color': fg,
        'axes.spines.top': False,
        'axes.spines.right': False,
        'legend.frameon': False,
        'figure.autolayout': True,
        'lines.linewidth': 2.0,
    })


def save_chart(fig: plt.Figure, name: str, output_dir: Path, dpi: int = 150) -> Path:
    """Save a matplotlib figure to the configured output directory."""
    out_path = output_dir / "charts" / f"{name}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path), dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    return out_path
