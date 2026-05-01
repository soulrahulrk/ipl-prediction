import docx
import re
import os
import zipfile
from xml.etree import ElementTree

def get_page_count(docx_path):
    try:
        with zipfile.ZipFile(docx_path) as z:
            app_xml = z.read("docProps/app.xml")
            root = ElementTree.fromstring(app_xml)
            # Standard namespace for docProps/app.xml
            ns = {"ns": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"}
            pages = root.find("ns:Pages", ns)
            if pages is not None:
                return int(pages.text)
    except:
        pass
    return 1

def analyze_doc(docx_path, output_path):
    doc = docx.Document(docx_path)
    all_paras = doc.paragraphs
    total_paras = len(all_paras)
    
    # Identify non-empty paragraphs for chunking
    non_empty_indices = [i for i, p in enumerate(all_paras) if p.text.strip()]
    num_non_empty = len(non_empty_indices)
    page_count = get_page_count(docx_path)
    
    # Heading-like: Bold or Heading style
    headings = []
    for i, p in enumerate(all_paras):
        is_heading = p.style.name.startswith("Heading")
        is_bold = any(run.bold for run in p.runs) if p.runs else False
        if (is_heading or is_bold) and p.text.strip():
            headings.append(f"Line {i}: {p.text.strip()[:100]}")

    # Metrics regex
    metrics_re = re.compile(r"accuracy|mae|rmse|log loss|brier|precision|recall|f1|error|%", re.I)
    metrics_lines = []
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"FILE: {docx_path}\n")
        f.write(f"Total Paragraphs: {total_paras}\n")
        f.write(f"Page Count (from app.xml): {page_count}\n\n")
        
        f.write("--- HEADING-LIKE LINES ---\n")
        for h in headings:
            f.write(h + "\n")
        f.write("\n")
        
        f.write("--- PARAGRAPH DUMP ---\n")
        chunk_size = max(1, num_non_empty // page_count)
        current_page = 1
        non_empty_seen = 0
        
        for i, p in enumerate(all_paras):
            text = p.text.strip()
            # Label Page
            if text:
                if non_empty_seen % chunk_size == 0 and current_page <= page_count:
                    f.write(f"\n[PAGE {current_page}]\n")
                    current_page += 1
                non_empty_seen += 1
            
            f.write(f"[{i}] [{p.style.name}] {p.text}\n")
            
            # Check for metrics
            if metrics_re.search(p.text):
                metrics_lines.append(f"Line {i}: {p.text.strip()}")
        
        f.write("\n--- METRICS-LIKE LINES ---\n")
        for m in metrics_lines:
            f.write(m + "\n")

# Run analysis
analyze_doc("docs/Final Project sample (1).docx", "docs/reports/_ai_report_analysis.txt")
analyze_doc("docs/IPL_Prediction_Project_Report_Refined.docx", "docs/reports/_ipl_70plus_analysis.txt")

# Create style mapping notes manually based on prompt requirements
with open("docs/reports/_style_mapping_notes.txt", "w", encoding="utf-8") as f:
    f.write("SUMMARY OF AI REPORT STYLE MAPPING\n")
    f.write("Front-matter order: Title Page, Abstract/Summary, TOC, List of Figures/Tables.\n")
    f.write("Chapter order: Introduction, Literature Review, Methodology, Results/Evaluation, Conclusion.\n")
    f.write("Numbering conventions: Decimal numbering for sections (e.g., 1.1, 1.2).\n")
    f.write("Table/figure list pattern: 'Table X: ...' or 'Figure X: ...' usually in bold or specific styles.\n")
    f.write("Evaluation-writing pattern: Quantitative metrics followed by qualitative discussion and performance graphs.\n")

print("Created: docs/reports/_ai_report_analysis.txt")
print("Lines: " + str(sum(1 for _ in open("docs/reports/_ai_report_analysis.txt", encoding="utf-8"))))
print("Created: docs/reports/_ipl_70plus_analysis.txt")
print("Lines: " + str(sum(1 for _ in open("docs/reports/_ipl_70plus_analysis.txt", encoding="utf-8"))))
print("Created: docs/reports/_style_mapping_notes.txt")
print("Lines: " + str(sum(1 for _ in open("docs/reports/_style_mapping_notes.txt", encoding="utf-8"))))
