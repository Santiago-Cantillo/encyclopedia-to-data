# Source and code reuse

The demonstration uses three pages of a mid-twentieth-century biographical encyclopedia with entries in French and English. The publisher reserved all rights, and the title is withheld. The three scanned pages are included in `data/raw/` as the smallest sample that lets every stage of the pipeline run and lets its output be checked against the source; no further pages are distributed. `data/raw/source.json` records the SHA-256 hash of the sample and its page mapping.

The repository also includes derived text: the OCR reading order (`examples/lines.txt`), the segmented entries (`examples/entries.json`, `examples/entries.csv`), the structured records returned by the model (`examples/biographies.json`, `examples/biographies.csv`) and the run reports. These files exist to show what each stage produces. They are not a dataset for reuse, and the addresses and telephone numbers in them describe the period of publication.

If you hold rights to the source and object to this use, open an issue in the repository and the pages will be removed.

The code is released under the MIT license in `LICENSE`. That license covers the software only, not the scanned pages or the derived example text.
