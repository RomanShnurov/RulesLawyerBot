"""
Analyze PDF files in rules_pdfs/ directory.

This script helps you understand what PDFs you have before renaming.
It extracts metadata and creates a CSV for manual mapping.

Usage:
    uv run python scripts/analyze_pdfs.py
"""
import csv
from pathlib import Path

from pypdf import PdfReader


def extract_pdf_info(pdf_path: Path) -> dict:
    """Extract basic info from PDF file.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dictionary with PDF metadata
    """
    try:
        reader = PdfReader(pdf_path)
        metadata = reader.metadata or {}

        # Try to extract game name from first page
        first_page_text = ""
        if len(reader.pages) > 0:
            first_page_text = reader.pages[0].extract_text()[:500]  # First 500 chars

        return {
            "filename": pdf_path.name,
            "title": metadata.get("/Title", ""),
            "pages": len(reader.pages),
            "first_page_preview": first_page_text.replace("\n", " ")[:100]
        }
    except Exception as e:
        return {
            "filename": pdf_path.name,
            "title": "",
            "pages": 0,
            "first_page_preview": f"Error: {str(e)}"
        }


def analyze_pdfs():
    """Analyze all PDFs and create inventory CSV."""
    pdf_dir = Path("rules_pdfs")

    if not pdf_dir.exists():
        print(f"❌ Directory {pdf_dir} not found")
        return

    pdf_files = list(pdf_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"⚠️  No PDF files found in {pdf_dir}")
        return

    print(f"📚 Found {len(pdf_files)} PDF files\n")
    print("Analyzing PDFs...\n")

    # Analyze each PDF
    pdf_data = []
    for i, pdf_file in enumerate(sorted(pdf_files), 1):
        print(f"  [{i}/{len(pdf_files)}] {pdf_file.name}")
        info = extract_pdf_info(pdf_file)
        pdf_data.append(info)

    # Create CSV for manual mapping
    output_csv = Path("rules_pdfs_inventory.csv")

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "current_filename",
            "english_name",  # To be filled manually
            "russian_names",  # To be filled manually
            "is_expansion",  # yes/no
            "parent_game",  # if expansion
            "pages",
            "pdf_title",
            "preview",
            "notes"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for info in pdf_data:
            writer.writerow({
                "current_filename": info["filename"],
                "english_name": "",  # Manual fill
                "russian_names": "",  # Manual fill
                "is_expansion": "",
                "parent_game": "",
                "pages": info["pages"],
                "pdf_title": info["title"],
                "preview": info["first_page_preview"],
                "notes": ""
            })

    print(f"\n✅ Analysis complete!")
    print(f"📊 Created inventory: {output_csv}")
    print(f"\nNext steps:")
    print(f"1. Open {output_csv} in Excel/Google Sheets")
    print(f"2. Fill in 'english_name' column (use BGG English names)")
    print(f"3. Fill in 'russian_names' column (comma-separated)")
    print(f"4. Mark expansions in 'is_expansion' column (yes/no)")
    print(f"5. Run scripts/rename_pdfs.py to rename files")


if __name__ == "__main__":
    analyze_pdfs()
