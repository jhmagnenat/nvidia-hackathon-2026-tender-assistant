# Sample tenders

`../sample_tenders.json` is the local search-fallback index (used when SIMAP/Tavily
are unavailable — see `src/adapters/tender_search.py`). Each entry's `id` maps to a
subfolder here containing that tender's documents:

```
data/sample_tenders/
  <tender-id>/
    notice.txt
    cahier_des_charges.txt
```

These `.txt` fixtures are **synthetic, hackathon-demo data** — clearly not real
simap.ch tenders — written in a section-header format
(`TITRE:`, `EXIGENCES OBLIGATOIRES:`, `CERTIFICATIONS REQUISES:`, ...) that
`src/agents/ingestion.py`'s deterministic parser reads. They are committed to git
(unlike real tender PDFs, which are not freely redistributable and are excluded via
`.gitignore`).

To point the pipeline at real tenders instead: drop real PDFs/text files into a new
subfolder here and add a matching entry to `../sample_tenders.json`, or wire up the
SIMAP/Tavily adapters once those services are reachable from this environment.
