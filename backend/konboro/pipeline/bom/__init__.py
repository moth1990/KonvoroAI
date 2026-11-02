"""The BOM-only path (01 §5.8): reading a bill of materials into a table, in stage 1.

- `sheets`: an Excel workbook or a CSV file, read in code (01 §4.2: each worksheet is a page).
- `mapping`: which column is the item, the quantity, the panel…: code from the headers first, the model for headers
  code doesn't know, and the user when the mapping is unsure (S14 decisions 1–2).
- `table`: the table as stage 1 stores it (a `bom_table` context artifact), from a sheet or from the model's
  transcription of a picture, and the row rules that turn it into items.
- `terms`: product names as BOMs write them ("מא"ז", "פחת", "מגן מתח יתר") → family (03 §4.6, S14 decision 6).

Stage 4 turns the items into components (`konboro.pipeline.association.bom`, S14 decision 3).
"""
