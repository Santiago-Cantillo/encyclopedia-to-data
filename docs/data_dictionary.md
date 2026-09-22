# Data dictionary

`entries.json` and `entries.csv` contain the extracted source text. `biographies.json` adds a nested `data` object containing the model's structured extraction and a `validation` object containing checks performed by code. `biographies.csv` flattens these objects into one row per entry.

## Source fields

| Field | Meaning |
| --- | --- |
| `id` | Source ID plus the entry's order within the sample; stable for unchanged extraction output. It is not a universal person identifier. |
| `source_id` | Identifier from the source manifest. |
| `pdf_page_start`, `pdf_page_end` | Inclusive page range in the original PDF viewer, numbered from 1. |
| `printed_page_start`, `printed_page_end` | Corresponding page numbers printed in the book. |
| `source_incomplete` | Whether this entry is known to be cut off by the sample boundary. In this sample, only the final record is marked. |
| `header` | Heuristically separated heading text. It can contain titles or some body text and is not a cleaned personal name. |
| `body` | Remaining biography text after OCR and whitespace/hyphen cleanup. |
| `model` | Model identifier returned by the API, including a dated version when supplied. |
| `reasoning` | Requested reasoning effort, or `none` for a model without reasoning. |
| `max_output_tokens` | Request cap, including reasoning tokens; actual usage is reported separately. |

The raw PDF preserves the scans. The searchable PDF preserves the page images with an OCR text layer. `lines.txt` records the cleaned reading order. The request combines the heading and body, so text that falls on the wrong side of that heuristic split is still available to the model.

## Structured fields under `data`

| Field | Content |
| --- | --- |
| `last_name`, `first_name`, `middle_name` | Name components, or `null` if uncertain. These components require human review for unfamiliar naming conventions. |
| `birthdate`, `deathdate` | `YYYY-MM-DD`, `YYYY-MM`, `YYYY`, original text when parsing is impossible, or `null`. The schema checks string/null type, not calendar validity. |
| `birthplace`, `deathplace` | Locations explicitly present in the input, or `null`. |
| `education` | Degree, institution, field of study, year, evidence, confidence. |
| `jobs` | English role description, organization, start/end years, evidence, confidence. |
| `family` | Relation and name, evidence, confidence. |
| `writings` | Publication title or description, evidence, confidence. |
| `awards` | Honor or award label, evidence, confidence. |
| `political_activities` | Political role/activity label, evidence, confidence. |
| `addresses` | Historical address, evidence, confidence. |
| `phones` | Historical telephone number as text, evidence, confidence. |
| `clubs` | Club name or abbreviation, evidence, confidence. |
| `founder_of` | Organization explicitly founded by the person, evidence, confidence. |
| `notes` | Other relevant information, evidence, confidence. |
| `quality` | Model-reported review flags and explanation. |

The complete machine-readable schema is `RESPONSE_FORMAT` in [biography_schema.py](../scripts/biography_schema.py). It is adapted from the research notebook, including its limitations. For example, jobs require string values for role and organization, while some education fields can be null. Future schema changes should address ambiguous names and missing organizations explicitly.

Arrays are empty when no supported items are extracted. Scalar missing values use JSON `null`. Each array item has `confidence` equal to `high`, `medium`, or `low`; these labels are not calibrated probabilities.

## Evidence and review flags

Each array item includes an `evidence` quote. The prompt asks for a contiguous quote from the exact text sent to the API, normally no more than 20 words and at most 25. The code checks presence in that input and the 25-word maximum. It does not verify that the quote supports every part of the extracted item. Scalar name, date, and place fields do not have evidence in the inherited schema.

- `data.quality.needs_review`: the model requests review.
- `data.quality.needs_review_reason`: the model's explanation.
- `data.quality.multiple_people_detected`: the model believes an input contains multiple people.
- `validation.evidence_issues`: exact-quote or quote-length checks that failed.
- `validation.needs_review`: true when the source is incomplete, either model flag is true, or any evidence check fails.

`validation.needs_review = false` does not mean a human verified the record. Manual observations are recorded separately in the validation notes.

## CSV conventions

Nested names are joined with underscores. Repeated items use one-based positions:

```text
data_first_name
data_education_1_degree
data_education_1_evidence
data_education_2_degree
data_jobs_1_role_en
data_quality_needs_review
validation_needs_review
```

All populated array item fields are retained, including evidence. The widest record determines the available columns; missing cells are blank. Empty arrays generate no item columns. JSON is the canonical output when the distinction between `null`, empty arrays, and absent CSV cells matters.

CSV files use UTF-8 with a byte-order mark for convenient opening in Excel. Spreadsheet software may still reinterpret dates, years, or phone numbers; import those columns as text when their exact representation matters.

## Run files

`ocr_run.json` records source/output hashes, OCR languages, text counts, and core package versions. `lines.txt` is the cleaned OCR text in reading order. `skipped.json` lists entries set aside by the parser as non-persons, such as country profiles; they are never sent to the model. `responses/` holds private per-entry API results and input/settings fingerprints for resumption. `failures.json` lists entries not successfully exported. `usage.json` sums token usage for saved successful responses. `validation.json` summarizes structural and evidence checks. None of these checks establishes whole-book accuracy.
