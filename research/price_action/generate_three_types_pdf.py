"""
Generates publication-quality PDF report for Topic 13 - 3 Swing Trading Archetypes:
LONG, SHORT & REVERSAL with EMA 200 Distance Factor.
"""

import os
import sys
import subprocess
from datetime import datetime
import markdown_it

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUTPUT_DIR = os.path.abspath("research_reports_pdf")
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M")
MD_SOURCE = os.path.abspath("research/price_action/THREE_SWING_TYPES_RESEARCH.md")
PDF_NAME = f"HERMES_THREE_SWING_TYPES_RESEARCH_{TIMESTAMP}.pdf"
PDF_PATH = os.path.join(OUTPUT_DIR, PDF_NAME)
TEMP_HTML = os.path.join(OUTPUT_DIR, f"temp_three_types_{TIMESTAMP}.html")

CSS_STYLES = """
@page {
    size: A4;
    margin: 18mm 14mm 18mm 14mm;
    @bottom-right {
        content: counter(page);
    }
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.5;
    color: #1a1a1a;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
}
h1 {
    font-size: 17pt;
    color: #0d233a;
    border-bottom: 2px solid #2b5c8f;
    padding-bottom: 5px;
    margin-top: 0;
    margin-bottom: 10px;
}
h2 {
    font-size: 13pt;
    color: #1b3d64;
    border-bottom: 1px solid #dcdcdc;
    padding-bottom: 4px;
    margin-top: 18px;
    margin-bottom: 8px;
    page-break-after: avoid;
}
h3 {
    font-size: 11pt;
    color: #2b5c8f;
    margin-top: 14px;
    margin-bottom: 5px;
    page-break-after: avoid;
}
p, ul, ol {
    margin-top: 0;
    margin-bottom: 8px;
}
li {
    margin-bottom: 3px;
}
blockquote {
    border-left: 4px solid #d9534f;
    background-color: #fdf7f7;
    margin: 10px 0;
    padding: 8px 12px;
    color: #333333;
    font-size: 9.5pt;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 8.5pt;
    page-break-inside: avoid;
}
th, td {
    border: 1px solid #c8d1dc;
    padding: 5px 6px;
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
    font-size: 9pt;
    background-color: #f0f3f6;
    padding: 1px 3px;
    border-radius: 3px;
    color: #a01c1c;
}
pre {
    background-color: #f4f6f8;
    border: 1px solid #d0d7de;
    border-radius: 4px;
    padding: 8px 10px;
    overflow-x: auto;
    font-size: 8.5pt;
    page-break-inside: avoid;
    line-height: 1.35;
}
hr {
    border: 0;
    height: 1px;
    background-color: #dcdcdc;
    margin: 14px 0;
}
"""

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(CHROME_PATH):
        print(f"ERROR: Chrome not found at {CHROME_PATH}")
        sys.exit(1)

    print(f"Reading markdown: {MD_SOURCE}")
    with open(MD_SOURCE, "r", encoding="utf-8") as f:
        md_text = f.read()

    md = markdown_it.MarkdownIt('gfm-like', {'linkify': False})
    html_body = md.render(md_text)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>HERMES 3 Swing Trading Archetypes: LONG, SHORT & REVERSAL</title>
    <style>
        {CSS_STYLES}
    </style>
</head>
<body>
    {html_body}
</body>
</html>"""

    with open(TEMP_HTML, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"Generating PDF via Headless Chrome: {PDF_PATH}")
    cmd = [
        CHROME_PATH,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={PDF_PATH}",
        TEMP_HTML
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode == 0 and os.path.exists(PDF_PATH):
        size_kb = os.path.getsize(PDF_PATH) / 1024
        print(f"SUCCESS: Generated PDF at {PDF_PATH} ({size_kb:.1f} KB)")
        try:
            os.remove(TEMP_HTML)
        except Exception:
            pass
    else:
        print(f"ERROR generating PDF: {res.stderr}")
        sys.exit(1)

if __name__ == '__main__':
    main()
