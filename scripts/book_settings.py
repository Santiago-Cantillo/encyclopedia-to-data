"""Everything that is specific to THIS PROJECT's source book.  [THIS PROJECT]

The code in this repository is organised in three tiers, tagged in comments:

  [GENERIC]       Any scanned document -> OCR -> one API request per item -> tables.
                  pipeline.py. Nothing there knows what a biography is.
  [ENCYCLOPEDIA]  A printed reference work: text set in columns, a running head and
                  page number on every page, one heading per entry, entries that
                  continue in the next column or on the next page.
                  extract_biographies.py. It reads all book-specific rules from here.
  [THIS PROJECT]  This book's page geometry, heading style, labels, OCR languages and
                  model defaults (this file), plus the fields to extract and the
                  prompt (biography_schema.py).

To adapt the pipeline to another book, work through this file from top to bottom,
then adjust biography_schema.py. Delete or comment out rules that do not apply.
`pipeline.py extract` runs offline in seconds, so iterate on a 20-page sample and
read outputs/entries.csv and outputs/lines.txt after every change.
"""
import re

# --- Source description, written into the manifest by `pipeline.py sample` -----------
SOURCE_ID = "encyclopedia_sample"      # prefix of every record id
SOURCE_TITLE = "Biographical encyclopedia, mid-twentieth century (title withheld)"
SOURCE_NOTE = ("Two-column pages with entries in French or English. "
               "The publisher reserved all rights; three sample pages are included for demonstration.")
OCR_LANGUAGES = "eng+fra"              # Tesseract language packs joined with '+'

# --- Model defaults for `pipeline.py structure` -------------------------------------
MODEL = "gpt-5-mini"
REASONING = "high"                     # minimal | low | medium | high, or "none" for models without reasoning
MAX_OUTPUT_TOKENS = 50000              # includes reasoning tokens; a low cap can leave no room for the JSON

# --- Page geometry, in PDF points (72 per inch) -------------------------------------
# OCRmyPDF wrote A4 pages for this scan (595 x 842). Check `page.rect` for another book.
COLUMNS = 2                            # 1 for a single-column book
TOP_BAND = 90                          # running heads and page numbers sit above this y ...
BOTTOM_BAND = 65                       # ... or below page height minus this
SAME_LINE_TOLERANCE = 5                # fragments whose vertical centres differ by less form one line
WRAPPED_HEADING_GAP = 10               # the second line of a wrapped heading starts within this gap

# --- Page furniture: recognised only inside the top and bottom bands ------------------
# Punctuation is stripped before matching, because OCR adds noise such as "(c) ABD" or "AMI ."
PAGE_NUMBER = re.compile(r"\d{1,4}")
RUNNING_HEAD = re.compile(r"[A-Z]{1,3}")   # this book prints "ABD"; use r"[A-Z]{2,}" for full surnames

# --- Headings: how an entry starts in this book ---------------------------------------
# Entries begin with an UPPERCASE surname, a comma, then given names:
#   "ABAZA, AZIZ, C.B.E. president et ..."      "ABBASSY, Dr. AHMED SHAFIK, M.B. ..."
HEADING_START = re.compile(r"^[A-Z]{2,}")      # after any leading punctuation ("| ABDEL HAK, ...")
HEADING_MIN_LETTERS = 3                        # letters before the first comma; rejects "MD, 00;" degree lines
HEADING_MAX_LOWERCASE = 3                      # lowercase letters allowed before the first comma ("Dr")
# A degree line such as "M.B., Ch.B., Prof. of Surgery" also starts with capitals and a comma.
# It is rejected because every word before the comma is an abbreviation (a period inside the
# word, or at most two letters); "TAWFIK F. SHAHLAWI" and "HAMAD. (Khider)" keep a full word.
SECTION_LABEL = re.compile(r"\b(?:Addr|Adr|Add|Educ|Dipl|Publ|Awards?|Son of|Married|Clubs?)\s*:", re.I)
# Words that may sit inside an uppercase heading without ending it. Used to recognise a
# heading that wrapped onto a second line: "EL-BAKOURI, Sheikh AHMED" / "HASSAN, Ex-Minister".
TITLE_WORDS = re.compile(r"\b(?:Dr|Prof|Sir|Sheikh|Cheikh|Comte|Mme|Mrs|Mr|Lewa|Mouchir|Miralai|Bey|Pasha|"
                         r"Hadj|Emir|VEmir|l'Emir)\b\.?", re.I)
# A heading hiding after a sentence break inside one OCR line: "... CAIRO. ABAZA, OSMAN, ..."
EMBEDDED_HEADING = re.compile(r"\.\s+([A-Z][A-Z\-]+,(?:\s+(?:Dr\.|Sir|Prof\.))?\s+[A-Z][A-Za-z\.\-]+,)")
# A heading with nothing after it is almost always a heading that wrapped: attach it to the
# next entry. Set to False for a source where name-only entries are genuine.
MERGE_HEADING_ONLY_ENTRIES = True


def looks_like_heading(line):
    """Does this line start a new entry? Adjust the constants above before changing the logic."""
    line = re.sub(r"^[^A-Za-z]+", "", line.lstrip())        # OCR noise before the name; "tf ANTONY" still fails
    if not line or not HEADING_START.match(line) or SECTION_LABEL.search(line) or "," not in line:
        return False
    head = re.split(r"\(", line, maxsplit=1)[0].split(",", 1)[0]   # before the first "(" and the first ","
    letters = re.findall(r"[A-Za-z]", head)
    abbreviations_only = all(re.search(r"\.[^.]*[A-Za-z]", word) or len(re.findall(r"[A-Za-z]", word)) <= 2
                             for word in head.split())
    return (len(letters) >= HEADING_MIN_LETTERS and not abbreviations_only
            and sum(c.islower() for c in letters) <= HEADING_MAX_LOWERCASE)


CLUB_LABEL = re.compile(r"\bClubs?\b\s*:", re.I)
CLUB_TOKEN_MAX_LETTERS = 4             # club initials are short: "G.S.C.", "CECP", "HSE"


def continues_previous_entry(previous_line, line):
    """A line that looks like a heading but belongs to the entry above it.

    In this book that is the club list: "CAIRO. Clubs :" is followed by "HSE, SPC." on its
    own line, which starts with capitals and contains a comma like a surname does. Club
    initials are short uppercase tokens; a real heading such as "AMER, Mouchir (Field
    Marshal)" carries lowercase given names after only two tokens.
    Return False for a book without this quirk, or write your own rule.
    """
    if re.search(r"\bClubs?\b", line, re.I):
        return True
    if not CLUB_LABEL.search(previous_line):
        return False
    uppercase_part = re.split(r"[a-z]", line, maxsplit=1)[0]  # up to the first lowercase letter
    tokens = re.findall(r"[A-Z]+", uppercase_part)
    has_lowercase = uppercase_part != line
    return (len(tokens) >= 2 and all(len(t) <= CLUB_TOKEN_MAX_LETTERS for t in tokens)
            and (len(tokens) >= 3 or not has_lowercase))


def heading_end(text):
    """Index where the heading stops and the body starts, or None if the heading continues.

    The heading ends at the second comma, or before the word holding the second period,
    whichever comes first:  "ABAZA, AZIZ, C.B.E. president" -> "ABAZA, AZIZ,"
                            "ABDEL AZIZ MOHAMED, A.M.I. Mench." -> "ABDEL AZIZ MOHAMED,"
    """
    end = None
    commas = [m.start() for m in re.finditer(",", text)]
    if len(commas) >= 2:
        end = commas[1] + 1
    periods = [m.start() for m in re.finditer(r"\.", text)]
    if len(periods) >= 2:
        word_start = text.rfind(" ", 0, periods[1]) + 1
        if word_start == 0:              # the first word holds both periods ("M.B., Ch.B."): do not empty the heading
            word_start = None if end is not None else periods[1] + 1
        if word_start is not None and (end is None or word_start < end):
            end = word_start
    return end


# --- Entries that are not people ------------------------------------------------------
# This book inserts a country profile before each country's biographies. Long entries that
# use most of these words are written to skipped.json instead of being sent to the model.
# A person whose entry absorbed a following country profile is set aside too; fix those by
# hand or choose sample pages that avoid them.
NON_PERSON_MIN_CHARS = 2500
NON_PERSON_WORDS = ("AREA", "POPULATION", "CAPITAL", "CURRENCY", "HEAD OF STATE",
                    "GEOGRAPHY", "HISTORY", "RELIGION", "LANGUAGE", "EDUCATION", "COMMUNICATIONS")
NON_PERSON_MIN_WORDS = 4


def is_non_person(header, body):
    """True for a long entry that reads like a country profile rather than a biography."""
    text = f"{header} {body}".upper()
    return len(body) > NON_PERSON_MIN_CHARS and sum(w in text for w in NON_PERSON_WORDS) >= NON_PERSON_MIN_WORDS
