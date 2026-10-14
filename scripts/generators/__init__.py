from generators.layout_a import render_a
from generators.layout_b import render_b_csv, render_b_xlsx
from generators.layout_c import render_c

RENDERERS = {
    ("A", "pdf"): render_a,
    ("B", "csv"): render_b_csv,
    ("B", "xlsx"): render_b_xlsx,
    ("C", "pdf"): render_c,
}
