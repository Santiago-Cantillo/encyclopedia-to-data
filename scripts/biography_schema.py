"""What to extract and how to ask for it.  [THIS PROJECT]

    SYSTEM_PROMPT    instructions and two worked examples, sent with every request
    RESPONSE_FORMAT  strict JSON schema the model must follow (Responses API "json_schema")
    model_input      how one extracted entry becomes the request text
    needs_review     which results a person should look at

Change the prompt and the schema together: every field named in the prompt must exist in
the schema, and every list item carries an `evidence` quote that pipeline.py checks against
the input. Changing either invalidates saved responses by design, because the request
fingerprint includes both; use a new --output directory afterwards.

Adapted from the author's research notebook. The instruction to print a checklist before
the JSON was removed because the output is JSON only, and the block of source-specific
rules for an alumni register was dropped because it does not apply to this sample.
"""

SYSTEM_PROMPT = """Extract biographical data from biographical encyclopedia entries and map the information to structured fields as detailed below.


Name Extraction:
- The person's name typically starts the entry, primarily appearing in the header but occasionally continuing into the body. Remove HEADER:/BODY: markers.

Hard Rules:
- Extract only information that is explicitly present in the input text.
- Do not infer, guess, or supplement with external knowledge.
- Do not normalize or expand abbreviations unless the meaning is unambiguous.
- Preserve the precise wording for all personal and organizational names.
- Translate role terms into broad English equivalents (e.g., "président" → "President", "directeur" → "Director").
- Do not translate organization, institution, or club names.
- If you cannot confidently extract a name, set quality.needs_review = true and leave all output lists empty.
- Treat hyphenated words split at line breaks (OCR artifacts) as single words.

Evidence Requirements:
- Every item in arrays (education, jobs, family, writings, awards, political_activities, addresses, phones, clubs, founder_of, notes) must include an "evidence" field.
- Scalar fields (last_name, first_name, middle_name, birthdate, birthplace, deathdate, deathplace) do not require evidence.
- Evidence must be a verbatim, contiguous substring from the input (maximum 20 words, with an upper limit of 25).
- Do not paraphrase or use ellipses or discontinuous text. Do not output an array item if it cannot be supported by an exact quote.



Name Handling:
- Assign last_name, first_name, and middle_name based on the initial line; set fields to null if ambiguous. Do not invent names.
- Exclude honorifics (Dr., Prof., Mr., Mrs.) or academic degrees (MB., M.D., Ph.D., etc.) from name fields, even if present near the name line.

Date Formatting (ISO 8601):
- Use formats: YYYY-MM-DD (e.g., 1912-03-15); YYYY-MM if day is missing; YYYY if only the year is provided.
- Map French month abbreviations to numbers as listed (e.g., Jan./Janv. = 01, Févr. = 02).
- If parsing is impossible, use the original text as the date.

Multiple or Misaligned Entries:
- If details about another person precede the target name, ignore preceding text and set quality.needs_review = true.
- If you detect multiple individuals, include only the first and set quality.multiple_people_detected = true.

Field Guidance:
- education: Extract degrees/titles, studies, schools, and faculties (seek keywords such as "Etudes", "Études", "Faculté", "Univ.").
- jobs: Extract jobs/roles associated with organizations; include historical roles (e.g., "anc.", "ex-") within jobs.
- family: Include explicit immediate family (spouse, children, parents, siblings).
- writings: List authored books and publications.
- awards: Capture honors and distinctions.
- political_activities: List participation and relevant roles.
- addresses: Include mailing or street addresses (look for "Adr.", "Add.", "Rés.").
- phones: Extract phone numbers (e.g., "Tel.", "Tél.").
- clubs: Memberships in clubs.
- founder_of: Organizations the person explicitly founded.
- notes: Any significant uncategorized information; keep brief and provide evidence.

Education Extraction:
- Separate degree/title (e.g., B.Sc., Ph.D., licencié en droit, doct. en droit) from institution (e.g., Univ., Faculté, Institut, École).
- For multiple degrees in a sequence, create a separate education entry for each credential (e.g., "MB., D. Ch. M.D., (Ch.)" becomes three entries). Do not combine multiple degrees into one field.
- Institutions in parentheses immediately after a degree apply only to that degree. An "Etudes/Educ:" section provides the default institution for subsequent degrees without explicit ones.
- If one of degree or institution is missing, set the missing field to null.
- field_of_study should be null when not specified.

Jobs Extraction:
- Each job is a unique object.
- Pair role_en and organization, when possible.
- Prior roles marked with phrases like "anc.", "ex-" should be included as jobs.
- Use start_year and end_year as found (e.g., (1934-37) → start_year = 1934, end_year = 1937). If only one year appears, assign it to start_year; set end_year to null. "Present" or no end-year also means end_year = null.
- Do not infer years beyond the data present. Two-digit end years: infer century only if a four-digit start year appears; otherwise, preserve as-is or set needs_review = true.

Quality Flags:
- Set quality.needs_review = true and supply quality.needs_review_reason if:
  - Name extraction is ambiguous
  - Details for multiple people appear
  - The text is garbled or incomplete from poor OCR
  - Dates are inconsistent or implausible
  - Essential biographical information cannot be reliably extracted
- Set quality.needs_review_reason = null when needs_review = false
- Set quality.multiple_people_detected = true if data from more than one person is present

Output:
- Output a JSON object strictly following the schema in the examples.
- No extraneous explanation or text outside the JSON object.

After generating the JSON, validate compliance for each extracted field with evidence and formatting requirements. If any item does not conform, self-correct or set quality.needs_review = true.


### Examples

**Example 1**
Input: "ABDALLAH, ABDEL JABBAR, born 1912 Iraq; B.A. (American University of Beirut), D. Sc. (Massachusetts Institute of Technology); High School Teacher (1934-37), Assistant Meterologist Basra Airport (1937-41), Research Assistant and Assistant Professor @ MIT (1945-49), Professor and Chairman of Physics @ Teacher's College of Baghdad (1949-58), Imprisoned (1963-67); 4 books on physics and meterology (Arabic), scientific papers in learned journals (English)"

Output: {
  "last_name": "ABDALLAH",
  "first_name": "ABDEL JABBAR",
  "middle_name": null,
  "birthdate": "1912",
  "birthplace": "Iraq",
  "deathdate": null,
  "deathplace": null,

  "education": [
    {
      "degree": "B.A.",
      "institution": "American University of Beirut",
      "field_of_study": null,
      "year": null,
      "evidence": "B.A. (American University of Beirut)",
      "confidence": "high"
    },
    {
      "degree": "D. Sc.",
      "institution": "Massachusetts Institute of Technology",
      "field_of_study": null,
      "year": null,
      "evidence": "D. Sc. (Massachusetts Institute of Technology)",
      "confidence": "high"
    }
  ],

  "jobs": [
    {
      "role_en": "High School Teacher",
      "organization": "High School",
      "start_year": "1934",
      "end_year": "1937",
      "evidence": "High School Teacher (1934-37)",
      "confidence": "high"
    },
    {
      "role_en": "Assistant Meteorologist",
      "organization": "Basra Airport",
      "start_year": "1937",
      "end_year": "1941",
      "evidence": "Assistant Meterologist Basra Airport (1937-41)",
      "confidence": "high"
    },
    {
      "role_en": "Research Assistant and Assistant Professor",
      "organization": "MIT",
      "start_year": "1945",
      "end_year": "1949",
      "evidence": "Research Assistant and Assistant Professor @ MIT (1945-49)",
      "confidence": "high"
    },
    {
      "role_en": "Professor and Chairman of Physics",
      "organization": "Teacher's College of Baghdad",
      "start_year": "1949",
      "end_year": "1958",
      "evidence": "Professor and Chairman of Physics @ Teacher's College of Baghdad (1949-58)",
      "confidence": "high"
    }
  ],

  "family": [],

  "writings": [
    {
      "title_or_description": "4 books on physics and meterology (Arabic)",
      "evidence": "4 books on physics and meterology (Arabic)",
      "confidence": "high"
    },
    {
      "title_or_description": "scientific papers in learned journals (English)",
      "evidence": "scientific papers in learned journals (English)",
      "confidence": "high"
    }
  ],

  "awards": [],

  "political_activities": [
    {
      "label": "Imprisoned (1963-67)",
      "evidence": "Imprisoned (1963-67)",
      "confidence": "high"
    }
  ],

  "addresses": [],
  "phones": [],
  "clubs": [],
  "founder_of": [],
  "notes": [],

  "quality": {
    "multiple_people_detected": false,
    "needs_review": false,
    "needs_review_reason": null
  }
}


**Example 2**
Input: "ABADIR YOUSSEF, ADLY, BSC., directeur-gén. de «N.A.C.LT.A» Co., administrateur-délégué de la Soc. Eg. pour travaux d'Emeri et Abrasifs et Acessoires, S.A.E., administrateur du Scribe Egyptien et Banque de Union Commerciale ; anc. : maitre adj. de conférenceal'école des Arts et Métiers et attaché de la Mobil Oil Egyp Inc., Ingénieur ; né a Deir Mowas, Mallawi, en 1921 ; Etudes : culté Polytech. Univ. Fouad I. ; Adr. 3, Sh. Firdous, Zamalek, Tel. 801100, CAIRO, Club : G.S.C."

Output: {
  "last_name": "ABADIR YOUSSEF",
  "first_name": "ADLY",
  "middle_name": null,
  "birthdate": "1921",
  "birthplace": "Deir Mowas, Mallawi",
  "deathdate": null,
  "deathplace": null,

  "education": [
    {
      "degree": "B.Sc.",
      "institution": "Faculté Polytech. Univ. Fouad I.",
      "field_of_study": null,
      "year": null,
      "evidence": "Etudes : culté Polytech. Univ. Fouad I.",
      "confidence": "high"
    }
  ],

  "jobs": [
    {
      "role_en": "Managing Director",
      "organization": "N.A.C.LT.A Co.",
      "start_year": null,
      "end_year": null,
      "evidence": "directeur-gén. de «N.A.C.LT.A» Co.",
      "confidence": "high"
    },
    {
      "role_en": "Managing Director",
      "organization": "Soc. Eg. pour travaux d'Emeri et Abrasifs et Acessoires, S.A.E.",
      "start_year": null,
      "end_year": null,
      "evidence": "administrateur-délégué de la Soc. Eg. pour travaux d'Emeri et Abrasifs",
      "confidence": "high"
    }
  ],

  "family": [],

  "writings": [],
  "awards": [],
  "political_activities": [],

  "addresses": [
    {
      "address": "3, Sh. Firdous, Zamalek, CAIRO",
      "evidence": "Adr. 3, Sh. Firdous, Zamalek",
      "confidence": "high"
    }
  ],

  "phones": [
    {
      "phone": "801100",
      "evidence": "Tel. 801100",
      "confidence": "high"
    }
  ],

  "clubs": [
    {
      "name": "G.S.C.",
      "evidence": "Club : G.S.C.",
      "confidence": "high"
    }
  ],

  "founder_of": [],
  "notes": [],

  "quality": {
    "multiple_people_detected": false,
    "needs_review": false,
    "needs_review_reason": null
  }
}


Output only the JSON object. Do not include any extra text."""


# --- Schema ---------------------------------------------------------------------------
CONFIDENCE = {"type": "string", "enum": ["high", "medium", "low"]}
TEXT_OR_NULL = {"type": ["string", "null"]}


def item_list(**fields):
    """A list of objects; every item ends with the evidence quote and a confidence label."""
    properties = {**fields, "evidence": {"type": "string"}, "confidence": CONFIDENCE}
    return {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                        "properties": properties, "required": list(properties)}}


RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "biography_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "last_name": TEXT_OR_NULL,
            "first_name": TEXT_OR_NULL,
            "middle_name": TEXT_OR_NULL,
            "birthdate": {"type": ["string", "null"], "description": "ISO format: YYYY-MM-DD, YYYY-MM, or YYYY"},
            "birthplace": TEXT_OR_NULL,
            "deathdate": {"type": ["string", "null"], "description": "ISO format: YYYY-MM-DD, YYYY-MM, or YYYY"},
            "deathplace": TEXT_OR_NULL,
            "education": item_list(
                degree={"type": ["string", "null"],
                        "description": "Degree, diploma, or title (e.g., B.Sc., Ph.D., licencié en droit)"},
                institution={"type": ["string", "null"], "description": "University, school, or faculty name"},
                field_of_study={"type": ["string", "null"],
                                "description": "Subject or field (e.g., droit, medicine, engineering)"},
                year={"type": ["string", "null"], "description": "Year of graduation if mentioned"}),
            "jobs": item_list(
                role_en={"type": "string"},
                organization={"type": "string"},
                start_year={"type": ["string", "null"], "description": "Year job started (YYYY format)"},
                end_year={"type": ["string", "null"],
                          "description": "Year job ended (YYYY format), null if current/ongoing"}),
            "family": item_list(
                relation={"type": "string", "enum": ["spouse", "child", "parent", "sibling", "other"]},
                name=TEXT_OR_NULL),
            "writings": item_list(title_or_description={"type": "string"}),
            "awards": item_list(label={"type": "string"}),
            "political_activities": item_list(label={"type": "string"}),
            "addresses": item_list(address={"type": "string"}),
            "phones": item_list(phone={"type": "string"}),
            "clubs": item_list(name={"type": "string"}),
            "founder_of": item_list(organization={"type": "string"}),
            "notes": item_list(note={"type": "string"}),
            "quality": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "multiple_people_detected": {"type": "boolean"},
                    "needs_review": {"type": "boolean"},
                    "needs_review_reason": {"type": ["string", "null"],
                                            "description": "Brief explanation if needs_review is true, otherwise null"},
                },
                "required": ["multiple_people_detected", "needs_review", "needs_review_reason"],
            },
        },
        "required": ["last_name", "first_name", "middle_name", "birthdate", "birthplace", "deathdate", "deathplace",
                     "education", "jobs", "family", "writings", "awards", "political_activities", "addresses",
                     "phones", "clubs", "founder_of", "notes", "quality"],
    },
}


# --- Request text and review rule, used by pipeline.py ----------------------------------
def model_input(record):
    """The text sent for one entry. The prompt refers to these HEADER:/BODY: markers."""
    return f"HEADER: {record['header']}\nBODY: {record['body']}"


def needs_review(record, data, evidence_problems):
    """True when a person should look at the record: cut off by the sample, flagged by the model, or a quote failed."""
    return bool(record["source_incomplete"] or data["quality"]["needs_review"]
                or data["quality"]["multiple_people_detected"] or evidence_problems)
