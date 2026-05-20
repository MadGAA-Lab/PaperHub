"""Run once to (re)generate sample.pdf. Output is git-committed."""
from pathlib import Path

import pymupdf

OUT = Path(__file__).parent / "sample.pdf"


def main() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "A Tiny Test Paper", fontsize=18)
    page.insert_text((72, 140), "Abstract", fontsize=14)
    page.insert_text(
        (72, 170),
        "This PDF is a tiny example for the PaperHub ingestion pipeline tests.",
        fontsize=11,
    )
    page.insert_text((72, 220), "Introduction", fontsize=14)
    page.insert_text(
        (72, 250),
        "Mixture-of-Experts (MoE) routing activates only a subset of experts.",
        fontsize=11,
    )
    doc.save(OUT)
    doc.close()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
