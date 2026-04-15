import pdfplumber
import re

pdf_path = 'data_pipeline/xbrl/temp/reliance_latest.pdf'

print("=" * 60)
print("DIAGNOSTIC 1 - Scan ALL 27 pages with lines strategy")
print("=" * 60)
with pdfplumber.open(pdf_path) as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        if tables:
            print(f"Page {i+1}: {len(tables)} tables found")
            for j, t in enumerate(tables):
                print(f"  Table {j+1}: {len(t)} rows")
                print(f"  First row: {t[0]}")
                print(f"  Second row: {t[1] if len(t)>1 else 'N/A'}")

print("\n" + "=" * 60)
print("DIAGNOSTIC 2 - Retry with text strategy on ALL pages")
print("=" * 60)
with pdfplumber.open(pdf_path) as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables({
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_tolerance": 3,
        })
        if tables:
            print(f"Page {i+1}: {len(tables)} tables found")
            for j, t in enumerate(tables):
                print(f"  Table {j+1}: {len(t)} rows x "
                      f"{len(t[0]) if t else 0} cols")
                for row in t[:3]:
                    print(f"    {row}")

print("\n" + "=" * 60)
print("DIAGNOSTIC 3 - Check text layer on pages 1-10")
print("=" * 60)
keywords = [
    'revenue', 'profit', 'income', 'tax',
    'operations', 'depreciation', 'eps'
]
with pdfplumber.open(pdf_path) as pdf:
    for i, page in enumerate(pdf.pages[:10]):
        text = page.extract_text() or ''
        text_lower = text.lower()
        found = [k for k in keywords if k in text_lower]
        has_numbers = bool(re.search(r'\d{3,}', text))
        print(f"Page {i+1}: {len(text)} chars | "
              f"keywords={found} | numbers={has_numbers}")
        if found and has_numbers:
            print(f"  SAMPLE TEXT (first 500 chars):")
            print(f"  {text[:500]}")
            print()

print("\n" + "=" * 60)
print("DIAGNOSTIC 4 - Find income statement page")
print("=" * 60)
with pdfplumber.open(pdf_path) as pdf:
    for i, page in enumerate(pdf.pages):
        text = (page.extract_text() or '').lower()
        if ('revenue from operations' in text or
            'profit after tax' in text or
            'profit before tax' in text):
            print(f"Page {i+1} has income statement!")
            print(f"Full text of page {i+1} (first 2000 chars):")
            print(page.extract_text()[:2000])
            print()

            for strategy in [
                {'vertical_strategy': 'lines',
                 'horizontal_strategy': 'lines'},
                {'vertical_strategy': 'text',
                 'horizontal_strategy': 'text',
                 'snap_tolerance': 3},
                {'vertical_strategy': 'lines_strict',
                 'horizontal_strategy': 'lines_strict'},
                {'vertical_strategy': 'explicit',
                 'horizontal_strategy': 'text',
                 'snap_tolerance': 3},
            ]:
                try:
                    tables = page.extract_tables(strategy)
                    if tables:
                        print(f"  Strategy {strategy} -> "
                              f"{len(tables)} tables!")
                        print(f"  First table first 5 rows:")
                        for row in tables[0][:5]:
                            print(f"    {row}")
                    else:
                        print(f"  Strategy {strategy} -> 0 tables")
                except Exception as e:
                    print(f"  Strategy {strategy} -> ERROR: {e}")
            print("-" * 40)
