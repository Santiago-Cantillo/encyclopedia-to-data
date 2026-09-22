# Source and code reuse

The demonstration uses three pages of a mid-twentieth-century biographical encyclopedia with entries in French and English. The publisher reserved all rights, so the scanned pages are not distributed with this repository and the title is withheld. `data/raw/source.json` records SHA-256 hashes of the original file and of the three-page sample, plus the page mapping, so provenance can be verified locally by the author.

What the repository does include is derived text: the OCR reading order (`examples/lines.txt`), the segmented entries (`examples/entries.json`, `examples/entries.csv`), the structured records returned by the model (`examples/biographies.json`, `examples/biographies.csv`) and the run reports. These files exist to show what each stage produces. They are not a dataset for reuse, and the addresses and telephone numbers in them describe the period of publication.

The code is released under the MIT license in `LICENSE`. That license covers the software only, not the encyclopedia pages or the derived example text.
