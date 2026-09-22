"""Searchable PDF -> biography entries.  [ENCYCLOPEDIA]

Assumes a printed reference work: text set in columns, a running head and a page
number on every page, one heading per entry, and entries that continue in the next
column or on the next page. Everything that describes how THIS book looks comes from
book_settings.py; this module should not need changes for a similar book.

    get_lines                   page -> lines in reading order, column by column
    split_entries               lines -> entries, one per heading
    merge_heading_only_entries  reattach headings that wrapped onto a second line
    parse_entry                 entry -> heading + body
    build_records               everything above -> records for the pipeline
"""
import re

import book_settings as book  # [THIS PROJECT] every rule that depends on the book lives there


# ----------------------------------------------------------------------------- lines
def get_lines(pdf_path, metadata):
    """Read each page column by column, top to bottom; keep the PDF page number with every line."""
    import pymupdf
    lines = []
    with pymupdf.open(pdf_path) as document:
        if len(document) != len(metadata["pdf_viewer_pages"]):
            raise ValueError("OCR PDF page count does not match the source manifest.")
        for index, page in enumerate(document):
            page_number = metadata["pdf_viewer_pages"][index]
            fragments = []
            text_dict = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
            for block in text_dict.get("blocks", []):
                for line in block.get("lines", []):
                    text = clean("".join(span["text"] for span in line["spans"]))
                    x0, y0, x1, y1 = line["bbox"]
                    if text and not is_page_furniture(text, y0, y1, page.rect.height):
                        column = min(int((x0 + x1) / 2 // (page.rect.width / book.COLUMNS)), book.COLUMNS - 1)
                        fragments.append((column, y0, x0, y1, text))
            previous_position = None
            for column, y0, x0, y1, text in join_fragments(fragments):
                # Lines on the previous page are left alone: a continuation may start on the next page.
                previous = lines[-1][0] if lines and lines[-1][1] == page_number else ""
                if previous.endswith("-") and text[:1].isalpha() and not (
                        book.looks_like_heading(text) and not book.looks_like_heading(previous)):
                    # A word split at the line end: "Univer-" / "sity", or "NAZ-" / "MY, B.C. (Hons)".
                    # A stray hyphen before a new heading must not glue two people together.
                    lines[-1] = (previous[:-1] + text, page_number)
                elif (previous_position and previous_position[0] == column
                      and y0 - previous_position[1] < book.WRAPPED_HEADING_GAP
                      and is_wrapped_heading(previous, text)):
                    lines[-1] = (previous + " " + text, page_number)
                else:
                    lines.append((text, page_number))
                previous_position = (column, y1)
    return lines


def clean(text):
    """Normalise one OCR line: plain spaces and hyphens, and re-join spaced-out words ("E d u c." -> "Educ.")."""
    if not text:
        return ""
    text = text.replace(" ", " ").replace("–", "-").replace("—", "-")
    text = re.sub(r"-\s*\n\s*", "", text)
    # Only whole runs of single letters: "avocat a la cour" and "George I de" must stay as they are.
    text = re.sub(r"(?<![A-Za-z])((?:[A-Za-z]\s){2,}[A-Za-z]\.?)(?![A-Za-z])",
                  lambda m: m.group(0).replace(" ", ""), text)
    return re.sub(r"\s+", " ", text).strip()


def is_page_furniture(text, y0, y1, page_height):
    """Page numbers and running heads, recognised only inside the top and bottom bands."""
    if not (y0 < book.TOP_BAND or y1 > page_height - book.BOTTOM_BAND):
        return False
    core = re.sub(r"[^A-Za-z0-9]", "", text)
    return bool(book.PAGE_NUMBER.fullmatch(core) or book.RUNNING_HEAD.fullmatch(core))


def join_fragments(fragments):
    """Sort by column and position; glue fragments that share a baseline before reading left to right.

    OCR can emit a short word fragment as its own line with a slightly different top
    coordinate; sorted by exact coordinate, "Fa-" could precede the line that ends with it.
    """
    groups = []
    for item in sorted(fragments):
        column, y0, x0, y1, text = item
        first = groups[-1][0] if groups else None
        if first and first[0] == column and abs((y0 + y1) / 2 - (first[1] + first[3]) / 2) < book.SAME_LINE_TOLERANCE:
            groups[-1].append(item)
        else:
            groups.append([item])
    for group in groups:
        group.sort(key=lambda item: item[2])
        yield (group[0][0], min(i[1] for i in group), min(i[2] for i in group), max(i[3] for i in group),
               " ".join(i[4] for i in group))


def is_wrapped_heading(previous, text):
    """An uppercase heading that ran onto a second line: "EL-BAKOURI, Sheikh AHMED" / "HASSAN, Ex-Minister"."""
    previous = re.sub(r"[^A-Za-z0-9,.;:)]+$", "", previous)     # ignore trailing OCR noise such as " |"
    if not (book.looks_like_heading(previous) and book.looks_like_heading(text)) or previous.endswith((",", ".", ";")):
        return False
    name_part = book.TITLE_WORDS.sub("", re.sub(r"\([^)]*\)", "", previous))
    return sum(c.islower() for c in name_part) <= 2


# --------------------------------------------------------------------------- entries
def split_entries(lines):
    """Group lines into entries: a heading starts a new entry unless the book says it continues the previous one."""
    entries, current, previous_text = [], [], ""
    for text, page in lines:
        if book.looks_like_heading(text):
            if current and book.continues_previous_entry(previous_text, text):
                current.append((text, page))
            else:
                if current:
                    entries.append(current)
                current = [(text, page)]
        else:
            start = find_embedded_heading(text)
            if start is not None and current:
                before, after = text[:start].strip(), text[start:].strip()
                if before:
                    current.append((before, page))
                entries.append(current)
                current = [(after, page)]
            elif current:  # text before the first heading belongs to an entry outside the sample and is dropped
                current.append((text, page))
        previous_text = text
    if current:
        entries.append(current)
    return [entry for entry in entries if is_substantial(entry)]


def find_embedded_heading(text):
    """Position of a heading that OCR merged into the end of the previous entry's last line, or None."""
    for match in book.EMBEDDED_HEADING.finditer(text):
        if book.looks_like_heading(text[match.start(1):]):
            return match.start(1)
    return None


def is_substantial(entry):
    """Drop fragments: an entry needs more than one word, or more than twelve characters."""
    text = " ".join(t for t, _ in entry)
    return len(text.split()) > 1 or len(re.sub(r"\s+", "", text)) > 12


def merge_heading_only_entries(entries):
    """An entry with a heading and no body is a heading that wrapped: attach it to the entry that follows."""
    merged, pending = [], []
    for entry in entries:
        entry = pending + entry
        pending = []
        if not parse_entry(entry)["body"]:
            pending = entry
        else:
            merged.append(entry)
    if pending:
        merged.append(pending)
    return merged


def parse_entry(entry_lines):
    """Split an entry into heading and body; the heading may run over several lines."""
    texts = [text for text, _ in entry_lines]
    current, consumed = texts[0], 1
    while True:
        if current.endswith("-") and consumed < len(texts):
            current = current[:-1] + texts[consumed]
            consumed += 1
            continue
        end = book.heading_end(current)
        if end is not None and end < len(current):
            body = (current[end:].strip() + " " + " ".join(texts[consumed:])).strip()
            return {"header": current[:end].strip(), "body": body}
        if consumed < len(texts):
            current = current + " " + texts[consumed]
            consumed += 1
        else:
            return {"header": current, "body": ""}


# --------------------------------------------------------------------------- records
def build_records(lines, metadata):
    """Records for the pipeline, plus the entries set aside because they are not people."""
    entries = split_entries(lines)
    if book.MERGE_HEADING_ONLY_ENTRIES:
        entries = merge_heading_only_entries(entries)
    page_map = dict(zip(metadata["pdf_viewer_pages"], metadata["printed_pages"]))
    records, skipped = [], []
    for entry in entries:
        fields = parse_entry(entry)
        first, last = min(p for _, p in entry), max(p for _, p in entry)
        record = {"id": None, "source_id": metadata["source_id"],
                  "pdf_page_start": first, "pdf_page_end": last,
                  "printed_page_start": page_map[first], "printed_page_end": page_map[last],
                  "source_incomplete": False, "header": fields["header"], "body": fields["body"]}
        if book.is_non_person(fields["header"], fields["body"]):
            record["reason"] = "looks like a country profile or other non-person section"
            skipped.append(record)
        else:
            records.append(record)
    for index, record in enumerate(records, 1):
        record["id"] = f"{metadata['source_id']}_{index:03d}"
    if records and entries and records[-1]["header"] == parse_entry(entries[-1])["header"]:
        records[-1]["source_incomplete"] = bool(metadata["last_entry_incomplete"])
    for record in skipped:
        record["id"] = f"{metadata['source_id']}_skipped_p{record['pdf_page_start']}"
    return records, skipped


def extract_records(pdf_path, metadata):
    """Searchable PDF -> (records, reading-order lines, skipped entries)."""
    lines = get_lines(pdf_path, metadata)
    records, skipped = build_records(lines, metadata)
    return records, lines, skipped
