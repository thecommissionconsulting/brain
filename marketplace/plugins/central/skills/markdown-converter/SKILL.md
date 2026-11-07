---
name: markdown-converter
description: Convert documents and files to Markdown using markitdown. Use when converting PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx, .xls), HTML, CSV, JSON, XML, images (with EXIF/OCR), audio (with transcription), ZIP archives, YouTube URLs, or EPubs to Markdown format for LLM processing or text analysis.
---

# Markdown Converter

Convert files to Markdown using `uvx markitdown==0.1.7` — no installation required.

## Basic Usage

```bash
# Convert to stdout
uvx markitdown==0.1.7 input.pdf

# Save to file
uvx markitdown==0.1.7 input.pdf -o output.md
uvx markitdown==0.1.7 input.docx > output.md

# From stdin
cat input.pdf | uvx markitdown==0.1.7
```

## Supported Formats

- **Documents**: PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx, .xls)
- **Web/Data**: HTML, CSV, JSON, XML
- **Media**: Images (EXIF + OCR), Audio (EXIF + transcription)
- **Other**: ZIP (iterates contents), YouTube URLs, EPub

## Options

```bash
-o OUTPUT      # Output file
-x EXTENSION   # Hint file extension (for stdin)
-m MIME_TYPE   # Hint MIME type
-c CHARSET     # Hint charset (e.g., UTF-8)
-d             # Use Azure Document Intelligence
-e ENDPOINT    # Document Intelligence endpoint
--use-plugins  # Enable 3rd-party plugins
--list-plugins # Show installed plugins
```

## Examples

```bash
# Convert Word document
uvx markitdown==0.1.7 report.docx -o report.md

# Convert Excel spreadsheet
uvx markitdown==0.1.7 data.xlsx > data.md

# Convert PowerPoint presentation
uvx markitdown==0.1.7 slides.pptx -o slides.md

# Convert with file type hint (for stdin)
cat document | uvx markitdown==0.1.7 -x .pdf > output.md

# Use Azure Document Intelligence for better PDF extraction
uvx markitdown==0.1.7 scan.pdf -d -e "https://your-resource.cognitiveservices.azure.com/"
```

## Notes

- Output preserves document structure: headings, tables, lists, links
- First run caches dependencies; subsequent runs are faster
- For complex PDFs with poor extraction, use `-d` with Azure Document Intelligence
