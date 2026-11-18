"""
Generates high-quality, professional PDF reports from Markdown research documents
using Chrome headless and clean styling.
Outputs PDFs with date-time stamps to the dedicated research_reports_pdf directory.
"""

import os
import sys
import subprocess
from datetime import datetime
import markdown_it

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUTPUT_DIR = os.path.abspath("research_reports_pdf")
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M")

REPORTS_TO_BUILD = [
    {
        "source": "research/price_action/PRICE_ACTION_BEHAVIOUR_REPORT.md",
        "title": "HERMES Deep NIFTY Price-Action Behaviour Research",
        "pdf_name": f"HERMES_DEEP_PRICE_ACTION_BEHAVIOUR_REPORT_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/INTRADAY_BEHAVIOUR_REPORT.md",
        "title": "HERMES NIFTY Intraday Behaviour Research",
        "pdf_name": f"HERMES_INTRADAY_BEHAVIOUR_REPORT_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/SWING_BEHAVIOUR_REPORT.md",
        "title": "HERMES NIFTY Swing Behaviour Research",
        "pdf_name": f"HERMES_SWING_BEHAVIOUR_REPORT_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/GAP_BEHAVIOUR_RESEARCH.md",
        "title": "HERMES NIFTY Opening Gap Behaviour Research",
        "pdf_name": f"HERMES_GAP_BEHAVIOUR_RESEARCH_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/OPENING_RANGE_BEHAVIOUR.md",
        "title": "HERMES NIFTY Opening Range & First-Hour Behaviour Research",
        "pdf_name": f"HERMES_OPENING_RANGE_BEHAVIOUR_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/PDH_PDL_SWEEP_RESEARCH.md",
        "title": "HERMES NIFTY PDH / PDL Sweep & Rejection Behaviour Research",
        "pdf_name": f"HERMES_PDH_PDL_SWEEP_RESEARCH_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/CANDLE_GEOMETRY_RESEARCH.md",
        "title": "HERMES NIFTY Candle Geometry, Body, Wick & Close Location Research",
        "pdf_name": f"HERMES_CANDLE_GEOMETRY_RESEARCH_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/VOLATILITY_BEHAVIOUR_RESEARCH.md",
        "title": "HERMES NIFTY Volatility Compression -> Expansion Research",
        "pdf_name": f"HERMES_VOLATILITY_BEHAVIOUR_RESEARCH_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/TREND_MOMENTUM_REVERSION.md",
        "title": "HERMES NIFTY Trend vs Momentum vs Mean Reversion Research",
        "pdf_name": f"HERMES_TREND_MOMENTUM_REVERSION_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/MARKET_STRUCTURE_RESEARCH.md",
        "title": "HERMES NIFTY Swing Structure, Higher Highs, Lower Lows & Reversals Research",
        "pdf_name": f"HERMES_MARKET_STRUCTURE_RESEARCH_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/TIME_OF_DAY_BEHAVIOUR.md",
        "title": "HERMES NIFTY Time-of-Day Price Behaviour Research",
        "pdf_name": f"HERMES_TIME_OF_DAY_BEHAVIOUR_{TIMESTAMP}.pdf"
    },
    {
        "source": "research/price_action/MULTI_TIMEFRAME_SWING_RESEARCH.md",
        "title": "HERMES NIFTY Multi-Timeframe Price Behaviour & Swing Persistence Research",
        "pdf_name": f"HERMES_MULTI_TIMEFRAME_SWING_RESEARCH_{TIMESTAMP}.pdf"
    }
]

CSS_STYLES = """
@page {
    size: A4;
    margin: 20mm 15mm 20mm 15mm;
    @bottom-right {
        content: counter(page);
    }
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.55;
    color: #1a1a1a;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
}
h1 {
    font-size: 20pt;
    color: #0d233a;
    border-bottom: 2px solid #2b5c8f;
    padding-bottom: 6px;
    margin-top: 0;
    margin-bottom: 12px;
}
h2 {
    font-size: 14pt;
    color: #1b3d64;
    border-bottom: 1px solid #dcdcdc;
    padding-bottom: 4px;
    margin-top: 22px;
    margin-bottom: 10px;
    page-break-after: avoid;
}
h3 {
    font-size: 12pt;
    color: #2b5c8f;
    margin-top: 16px;
    margin-bottom: 6px;
    page-break-after: avoid;
}
p, ul, ol {
    margin-top: 0;
    margin-bottom: 10px;
}
li {
    margin-bottom: 4px;
}
blockquote {
    border-left: 4px solid #d9534f;
    background-color: #fdf7f7;
    margin: 12px 0;
    padding: 10px 14px;
    color: #333333;
    font-size: 10.5pt;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}
th, td {
    border: 1px solid #c8d1dc;
    padding: 6px 8px;
    text-align: left;
}
th {
    background-color: #eef3f8;
    color: #0d233a;
    font-weight: 600;
}
tr:nth-child(even) {
    background-color: #f8fafc;
}
code {
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9.5pt;
    background-color: #f0f3f6;
    padding: 2px 4px;
    border-radius: 3px;
    color: #a01c1c;
}
pre {
    background-color: #f4f6f8;
    border: 1px solid #d0d7de;
    border-radius: 4px;
    padding: 10px;
    overflow-x: auto;
    font-size: 9pt;
    page-break-inside: avoid;
}
.header-box {
    background-color: #f0f4f8;
    border: 1px solid #c2d4e5;
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 18px;
}
hr {
    border: 0;
    height: 1px;
    background-color: #dcdcdc;
    margin: 18px 0;
}
"""

def convert_md_to_html(md_path: str, title: str) -> str:
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    md = markdown_it.MarkdownIt('gfm-like', {'linkify': False})
    html_content = md.render(md_text)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        {CSS_STYLES}
    </style>
</head>
<body>
    {html_content}
</body>
</html>"""
    return full_html


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Output Directory for Research PDFs: {OUTPUT_DIR}")

    if not os.path.exists(CHROME_PATH):
        print(f"ERROR: Chrome binary not found at {CHROME_PATH}")
        sys.exit(1)

    generated_pdfs = []
    temp_html_files = []

    for item in REPORTS_TO_BUILD:
        src = os.path.abspath(item["source"])
        if not os.path.exists(src):
            print(f"ERROR: Source file {src} not found!")
            continue

        pdf_path = os.path.join(OUTPUT_DIR, item["pdf_name"])
        temp_html = os.path.join(OUTPUT_DIR, f"temp_{os.path.basename(src)}.html")
        temp_html_files.append(temp_html)

        print(f"\nProcessing {src} -> {pdf_path}...")
        html_doc = convert_md_to_html(src, item["title"])
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html_doc)

        cmd = [
            CHROME_PATH,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            temp_html
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(pdf_path):
            file_size_kb = os.path.getsize(pdf_path) / 1024
            print(f"SUCCESS: Generated {item['pdf_name']} ({file_size_kb:.1f} KB)")
            generated_pdfs.append(pdf_path)
        else:
            print(f"FAILED to generate {pdf_path}: {res.stderr}")

    # Clean up temporary HTML files
    for tmp in temp_html_files:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

    print("\nSummary of Generated Research PDFs:")
    for p in generated_pdfs:
        print(f" - {p}")


if __name__ == "__main__":
    main()
