#!/usr/bin/env python3
"""
update_roster.py
----------------
Reads student roster from a CSV or Excel file and updates the hardcoded
ROSTER constant in index.html.  Optionally commits and pushes to GitHub.

Accepted formats:
    roster.csv   — recommended (plain text, works best with Git)
    roster.xlsx  — Excel workbook (single sheet)

File format (columns are case-insensitive, extra whitespace ignored):
    Class  |  Roll No  |  Adm No   |  Name               |  Mobile
    6A     |  1        |  001/754  |  SMRUTI BEHERA      |  9937953808
    6A     |  2        |  002/755  |  SUDHANSU PATRO     |  9078924824
    ...

Usage:
    python update_roster.py roster.csv
    python update_roster.py roster.xlsx
    python update_roster.py roster.csv --html path/to/index.html
    python update_roster.py roster.csv --push
    python update_roster.py roster.csv --push --message "Update roster for 2026-27"

Requirements:
    pip install pandas openpyxl
"""

import json
import re
import sys
import argparse
import subprocess
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas not installed.  Run:  pip install pandas openpyxl")
    sys.exit(1)


# Classes the app recognises — any class in the Excel outside this list
# will trigger a warning but will still be written.
KNOWN_CLASSES = ['6A', '6B', '7A', '7B', '8A', '8B',
                 '9A', '9B', '10A', '10B', '11', '12']

# Canonical column names after normalisation
_COL_CLASS  = 'Class'
_COL_ROLL   = 'Roll No'
_COL_ADM    = 'Adm No'
_COL_NAME   = 'Name'
_COL_MOBILE = 'Mobile'

# Maps lowercased/stripped variants → canonical name
_COL_ALIASES = {
    'class':          _COL_CLASS,
    'roll':           _COL_ROLL,
    'roll no':        _COL_ROLL,
    'roll number':    _COL_ROLL,
    'rollno':         _COL_ROLL,
    'adm no':         _COL_ADM,
    'adm. no':        _COL_ADM,
    'admission no':   _COL_ADM,
    'admission number': _COL_ADM,
    'admno':          _COL_ADM,
    'name':           _COL_NAME,
    'student name':   _COL_NAME,
    'mobile':         _COL_MOBILE,
    'mobile no':      _COL_MOBILE,
    'phone':          _COL_MOBILE,
    'contact':        _COL_MOBILE,
}


def _normalise_columns(df: "pd.DataFrame") -> "pd.DataFrame":
    renamed = {}
    for col in df.columns:
        canonical = _COL_ALIASES.get(col.strip().lower())
        if canonical:
            renamed[col] = canonical
    return df.rename(columns=renamed)


def read_roster(file_path: str) -> dict:
    """Parse a CSV or Excel file and return a ROSTER dict keyed by class."""
    ext = Path(file_path).suffix.lower()
    try:
        if ext == '.csv':
            df = pd.read_csv(file_path, dtype=str)
        elif ext in ('.xlsx', '.xls'):
            df = pd.read_excel(file_path, dtype=str)
        else:
            print(f"ERROR: Unsupported file type '{ext}'. Use .csv or .xlsx")
            sys.exit(1)
    except FileNotFoundError:
        print(f"ERROR: File not found — {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR reading file: {e}")
        sys.exit(1)

    df = _normalise_columns(df)

    required = [_COL_CLASS, _COL_ROLL, _COL_ADM, _COL_NAME, _COL_MOBILE]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"ERROR: Missing column(s): {missing}")
        print(f"       Columns found in Excel: {list(df.columns)}")
        print("       Expected: Class | Roll No | Adm No | Name | Mobile")
        sys.exit(1)

    # Start with empty lists for all known classes so none disappear
    roster: dict = {cls: [] for cls in KNOWN_CLASSES}

    skipped = 0
    for idx, row in df.iterrows():
        cls    = str(row[_COL_CLASS]).strip()
        name   = str(row[_COL_NAME]).strip().upper()
        adm    = str(row[_COL_ADM]).strip()
        mobile = str(row[_COL_MOBILE]).strip()
        roll_raw = str(row[_COL_ROLL]).strip()

        # Skip blank / header-repeat rows
        if not cls or cls.lower() in ('nan', 'class'):
            skipped += 1
            continue
        if not name or name.lower() == 'nan':
            skipped += 1
            continue

        # Warn about unknown classes but still include them
        if cls not in KNOWN_CLASSES:
            print(f"  WARNING: Unknown class '{cls}' (row {idx + 2}) — included anyway")

        # Parse roll number — keep as int when possible
        try:
            roll = int(float(roll_raw))
        except (ValueError, TypeError):
            roll = roll_raw

        if cls not in roster:
            roster[cls] = []

        roster[cls].append({
            'roll':   roll,
            'admNo':  adm,
            'name':   name,
            'mobile': mobile,
        })

    # Sort each class by roll number
    for cls in roster:
        roster[cls].sort(key=lambda s: (int(s['roll']) if isinstance(s['roll'], int) else 9999))

    if skipped:
        print(f"  (Skipped {skipped} blank/invalid row(s))")

    return roster


def update_index_html(html_path: str, roster: dict) -> None:
    """Replace the const ROSTER = {...}; block in index.html."""
    path = Path(html_path)
    if not path.exists():
        print(f"ERROR: {html_path} not found.")
        sys.exit(1)

    content = path.read_text(encoding='utf-8')

    # Match const ROSTER = { ... }; — the value spans multiple lines
    pattern = r'(const ROSTER\s*=\s*)(\{[\s\S]*?\});'
    roster_json = json.dumps(roster, ensure_ascii=False, separators=(',', ':'))
    replacement = r'\g<1>' + roster_json + ';'

    new_content, count = re.subn(pattern, replacement, content)
    if count == 0:
        print("ERROR: Could not find 'const ROSTER = {...};' in the HTML file.")
        print("       Make sure the file contains exactly that pattern.")
        sys.exit(1)

    path.write_text(new_content, encoding='utf-8')


def git_commit_push(html_path: str, message: str) -> None:
    """Stage index.html, commit, and push."""
    try:
        subprocess.run(['git', 'add', html_path], check=True)
        result = subprocess.run(
            ['git', 'diff', '--cached', '--quiet'],
            capture_output=True
        )
        if result.returncode == 0:
            print("No changes to commit — roster in index.html is already up to date.")
            return
        subprocess.run(['git', 'commit', '-m', message], check=True)
        subprocess.run(['git', 'push'], check=True)
        print("Committed and pushed to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}")
        sys.exit(1)


def print_summary(roster: dict) -> None:
    total = sum(len(v) for v in roster.values())
    print(f"\n{'Class':<8} {'Students':>8}")
    print("-" * 18)
    for cls in KNOWN_CLASSES:
        count = len(roster.get(cls, []))
        flag = ""
        if count == 0:
            flag = "  (empty)"
        print(f"  {cls:<6} {count:>6}{flag}")
    print("-" * 18)
    print(f"  {'TOTAL':<6} {total:>6}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Update student roster in index.html from an Excel file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'excel',
        help='Path to the roster file (.csv recommended, or .xlsx)',
    )
    parser.add_argument(
        '--html',
        default='index.html',
        help='Path to index.html (default: index.html in current directory)',
    )
    parser.add_argument(
        '--push',
        action='store_true',
        help='Commit and push to GitHub after updating index.html',
    )
    parser.add_argument(
        '--message',
        default='Update student roster from Excel',
        help='Git commit message (used with --push)',
    )
    args = parser.parse_args()

    print(f"Reading roster from: {args.excel}")
    roster = read_roster(args.excel)
    print_summary(roster)

    print(f"Updating: {args.html}")
    update_index_html(args.html, roster)
    print("index.html updated successfully.")

    if args.push:
        print("\nPushing to GitHub...")
        git_commit_push(args.html, args.message)
    else:
        print("Done.  Run with --push to also commit and push to GitHub.")


if __name__ == '__main__':
    main()
