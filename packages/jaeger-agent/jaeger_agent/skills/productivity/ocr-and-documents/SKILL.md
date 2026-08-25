---
name: ocr-and-documents
description: "Extract text from PDFs and scanned documents with PyMuPDF or marker-pdf. Use when the user needs OCR, document text extraction, or a machine-readable version of a scan."
license: MIT
metadata:
  jros:
    version: 3.0.0
    lifecycle: core
    skill-class: first-class
    platforms: [linux, macos, windows]
    requires-tools: [terminal, read_file]
    tags: [ocr, pdf, documents, extraction]
    category: productivity
---

# OCR AND DOCUMENT EXTRACTION

## SOP

1. Inspect file type, page count, whether text is embedded, and desired output.
2. Use PyMuPDF for text-native PDFs; use OCR/marker only for scanned or complex
   pages. Do not OCR every document by default.
3. Process a small page sample first and inspect reading order, tables, headers,
   and character quality.
4. Read `references/legacy-guide.md` only for advanced marker/OCR setup and flags.
5. Run the bounded extraction, write the requested text/Markdown output, and
   compare representative pages against the source.

## ERROR HATCH

Encrypted/corrupt PDF, missing OCR dependency, or unusable reading order: report
the exact blocker and preserve partial output separately rather than overwriting.

## DONE WHEN

The output exists, representative pages were checked, and limitations such as
tables, handwriting, or low-confidence OCR are disclosed.
