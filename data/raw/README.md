The three-page scan (`sample_pages_004_006.pdf`) and its provenance manifest (`source.json`) live here. The manifest records the SHA-256 hash of the sample, the PDF page range and the printed page numbers; `pipeline.py ocr` checks the hash before it starts.

Run the pipeline on this sample as is. For your own book, `pipeline.py sample` cuts a similar sample and writes a fresh manifest. See the [reuse notes](../../docs/reuse.md) for the terms that apply to the scan.
