# Validation of the three-page demonstration

OCR, segmentation and the entry inventory were checked on 21 September 2026; the model run saved in `examples/` is from 22 September 2026. This is a functional demonstration on three pages, not an accuracy estimate for a whole book. A later section records how the parser was revised and checked against three complete books.

## Environment and input

- Windows, Python 3.12.12, in a newly created virtual environment.
- PyMuPDF 1.26.7, OCRmyPDF 16.12.0, OpenAI Python SDK 2.9.0.
- Tesseract 5.5.0.20241111 with `eng`, `fra` and `osd`; Ghostscript 10.06.0.
- Exact installed Python packages are recorded in `requirements-lock.txt`.
- The source is the original scan, PDF viewer pages 4–6 / printed pages 19–21. Earlier research OCR and AI outputs were not used to generate this run.

The native Windows virtual-environment workflow was tested. The Conda recipe and the macOS/Linux command adaptations are provided as alternatives and were not independently tested.

## OCR and segmentation

OCR corrected the first page's 180-degree rotation and produced nonempty text layers on all three pages. The source sample is about 11 MB; the searchable PDF is about 3.6 MB with PDF optimization disabled. The OCR step reported 2,560, 3,147 and 3,110 extracted text characters on the three pages.

Visual inspection identified **21 biography starts**: six on PDF page 4, eight on page 5 and seven on page 6. The extracted entries match that inventory and order. [reference_entries.json](reference_entries.json) records the manually checked headings and page spans; it is an inventory of entry boundaries, not a hand-transcribed dataset.

Cases explicitly checked:

| Case | Result |
| --- | --- |
| Upside-down first page | Corrected by OCR orientation detection. |
| Text near the column divider | Assigned by line centre, so right-column lines do not enter the left-column biography. |
| Detached `Fa-` fragment in the first biography | Grouped with fragments on the same baseline before reading left to right, preserving both `Deir Mowas` and `Faculté`. |
| ABAZA, AZIZ | Includes the continuation at the top of the right column on the same page. |
| ABAZA, OSMAN | One record spanning original PDF pages 4–5. |
| ABDEL HAK, ABDEL HAMID | One record spanning original PDF pages 5–6. |
| Uppercase wrapped names | NAZMY, AHMED MAHMOUD and KAMAL-EL-DiN MAHMOUD remain within their entries. |
| Club initials following `Clubs :` | Kept with the biography instead of creating a person named `HSE, SPC.` |
| Two entries headed ABDEL FATTAH HASSAN | Kept separate; the scan contains two distinct entries, one for a lawyer and one for a military/diplomatic biography. |
| ABDEL WAHAB TALAAT | Final record is explicitly marked `source_incomplete`; it continues onto original PDF page 7, which is not included. |

## Structured extraction

The example run was produced on 22 September 2026 with `gpt-5-mini` at `high` reasoning effort; the API returned `gpt-5-mini-2025-08-07`. Requests use the prompt and strict schema in `biography_schema.py`. The prompt includes a worked example based on the first biography, so that entry is not an independent evaluation case.

Each successful response is saved independently. Export requires a response for every input ID and validates its schema; a source/settings fingerprint prevents reuse after changing an input or request configuration, and HTTP errors and incomplete responses are reported explicitly. An earlier run on 21 September, made with a prompt that differed only in its opening phrase, had exposed a reading-order bug and a token-budget issue: one request consumed its 16,000-token cap entirely in reasoning and returned no JSON. The example run uses the corrected extraction and a 50,000-token cap, sends up to three requests concurrently, and retries transient errors up to three times.

The run completed all **21 requests** with **0 missing or failed results** in 14 minutes, producing **21 JSON records and 21 CSV rows** (207 CSV columns). Saved responses used 78,203 input tokens (57,856 cached) and 224,771 output tokens, of which 209,344 were reasoning tokens; see [examples/usage.json](../examples/usage.json). These counts exclude the earlier run and are not a billing statement. Counts and review flags are in [examples/validation.json](../examples/validation.json).

Five records require review, four because the model flagged them and one because of the sample boundary. Every evidence quote passed the exact-substring check:

| Entry | Why it is flagged |
| --- | --- |
| 009 — ABBOUDA, MOUSTAFA | The model reports OCR garbling: `Fgyntian`, `edue,`, `CATRO`. |
| 010 — ABDEL AHAD, ARMAND SELIM | The model reports an inconsistent OCR year range, `1989-41`, and broken words such as `Chief Accoun-. tant`. The scan reads `1939-41`. |
| 013 — ABDEL FATTAH HASSAN, military/diplomatic entry | The model reports OCR artifacts such as `Acadé- : mie Milit.` and `Arteur de`. |
| 014 — ABDEL HAK, ABDEL HAMID | The model reports OCR artifacts such as `Garden-€ity` and `C.Y¥.C`. |
| 021 — ABDEL WAHAB TALAAT | The sample ends before this biography is complete. |

In the earlier run the model had replaced closing guillemets with straight quotation marks in two quotes for entry 015, which the validator caught as inexact evidence; the current run quotes them exactly. Which entries the model flags varies between runs, while the OCR noise it cites is present in every one of these entries, so `needs_review = false` means the model did not object, not that the record is clean.

The outputs preserve these results and flags for inspection; they are not presented as a fully corrected dataset. Manual spot checks found the birth dates or years for entries 001, 002, 008, 015 and 021 consistent with the scans, and the first record gives `Deir Mowas, Mallawi` as its birthplace.

## Repeat-run check

For the earlier run, the complete `run` command was executed in a new output directory, starting again from the raw scanned PDF, with the completed response files supplied as a cache and no usable API key. OCR and extraction reran; all 21 input/settings fingerprints matched, so **0 API requests were needed**, and export and validation produced the same 21 records and review flags. This checked the full command and resumability without purchasing the same responses again. Fresh model calls are not byte-for-byte identical: the 22 September run flags a different set of entries, as described above.

## Parser revisions after the first run

The parser was then run, offline, over three complete OCR'd books: the same book in full (226 pages), a later edition with English entries and full-surname running heads (426 pages), and an alumni register with a different heading style (151 pages). Its output was compared with the research parser that produced the author's earlier datasets. That comparison exposed rules that had been tuned to the three-page sample:

| Rule as first written | Failure elsewhere in the same book | Revision |
| --- | --- | --- |
| Two short uppercase tokens after a `Club:` line are club initials | Swallowed `AMER, Mouchir (Field Marshal)`, a four-letter surname, into the previous biography | Two tokens count as initials only when the line has no lowercase letters; three or more tokens as before |
| Hyphenated line ends join with any following letter | A stray hyphen at the end of an entry glued the next heading onto it | No join when the next line is a heading and the previous one is not |
| Wrapped headings merge only when the first line has at most two lowercase letters after deleting `Dr.` | `Sheikh`, `Lewa (General)`, `Comte`, `Prof.` blocked the merge, leaving name-only records | Title words and parenthesised words are ignored; a heading-only record is merged into the next entry (`MERGE_HEADING_ONLY_ENTRIES`) |
| Running heads are bare one-to-three letter lines in the margins | `© ABD` leaked into a biography on sample page 6; page numbers at the top of a page were kept | Punctuation is stripped before matching, and both margins are checked for both patterns |
| Any line starting with capitals and containing a comma is a heading | Degree lines such as `M.B., Ch.B.,` and `MD, 00;` became people, sometimes with an empty heading | Abbreviation-only heads are rejected; the heading may not be empty |
| A spaced-out word is re-joined anywhere in a line | `avocat a la cour` became `avocatala cour` and `George I de` became `GeorgeIde` | Only whole runs of single letters are re-joined |

Country profiles inserted between biographies are now written to `skipped.json` instead of being sent to the model.

Results of the final rules, compared with the earlier research parser on the same OCR'd PDFs:

| Book | Pages | Records, revised | Records, earlier parser | Empty-body records, revised / earlier | Margin fragments left in text, revised / earlier |
| --- | --- | --- | --- | --- | --- |
| Sample book, first 20 pages | 20 | 118 | 122 | 0 / 1 | 2 / 15 |
| Sample book, complete | 226 | 1,648 | 1,671 | 0 / 1 | 13 / 227 |
| Later edition | 426 | 2,449 | 2,456 | 0 / 1 | 154 / 208 |
| Alumni register | 151 | 1,720 | 1,719 | 0 / 1 | 15 / 104 |

Most of the records that disappeared were fragments (`: MA.`, `XANDRIE`, `EL, Director,`) or headings that had been split from their person. Known remaining losses: a name preceded by OCR letter-noise such as `tf ANTONY SAKKAL` or `» e JUMA, SAAD` is not recognised as a heading and is merged into the previous entry; in the later edition, whose running heads are full surnames, the running heads still enter the text. Both are settings in `book_settings.py` rather than code changes.

On the three-page sample the revised parser reproduces the 21 entries of the inventory exactly, except that entry 017 no longer contains the running-head fragment `© ABD`. With the fragment present, the earlier model run had built a spurious third job, `Minchaet` at `ABD Abdel Nabi, AGA (Eg.)`. The example run lists landowner and lawyer only, as the scan does, although it still attaches the locality `Minchaet Abdel Nabi, AGA (Eg.)` to the lawyer job as its organization: an example of a correct quote with a doubtful interpretation.

## Known quality limitations

The first API smoke test returned the birth year `1921`, matching the scan, but its birthplace was `Deir MoFawas, Mallawi`. Inspection traced this to reading order: OCR emitted `Fa-` from `Faculté` as a detached fragment slightly above the rest of its line, and sorting by exact vertical coordinate joined it into `Deir Mo-was`. Grouping fragments on the same baseline fixed the source text, and that first record was regenerated for the final example. The model's review flag was false for the faulty input, which is why source checking matters even for schema-valid responses.

OCR also affects accents, punctuation, club initials and names such as `CAIRO` read as `CATRO`. The heuristic `header`/`body` division can include some profession text in the header. Both parts are sent to the model, but the header should not be treated as a normalized name.

Automated evidence checks verify exact substring matches against the text sent to the API. They do not verify the scanned image, the model's interpretation of a quote, or unsupported scalar values. Model confidence labels and `needs_review = false` are not human approval. No field-level precision/recall or whole-book accuracy is claimed.

## Offline regression checks

The suite in `scripts/test_pipeline.py` covers:

- Column assignment, margin furniture, wrapped headings with title words, and stray hyphens, on synthetic one-page PDFs.
- Page continuation, club initials, a short surname after a club line, heading-only entries, degree lines, and country profiles, on synthetic line lists.
- Agreement with the manually inspected 21-entry inventory (skipped when the scan is absent).
- Strict schema validation, exact evidence matching, and preservation of repeated fields in the wide CSV.
- Reusing completed requests without loading a key or calling the API; rejecting stale cached inputs, missing or failed results, incomplete responses that still parse, and inconsistent review flags; omitting the reasoning parameter for models without it.

Run it from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p "test_*.py" -v
```

All **20 offline checks pass**. `pip check` reported no broken requirements.
