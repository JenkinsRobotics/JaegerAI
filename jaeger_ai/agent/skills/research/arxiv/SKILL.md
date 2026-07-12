---
name: arxiv
description: "Search and fetch academic papers from arXiv (free REST API) plus citation/related-work data from Semantic Scholar. Load this for finding papers by keyword/author/category/ID, reading abstracts or full PDFs, generating BibTeX, or tracing citations."
version: 1.1.0
platforms: [macos, linux, windows]
requires_tools: [terminal, web_extract]
metadata:
  jros:
    tags: [arxiv, papers, research, citations, semantic-scholar, bibtex]
    category: research
    related_skills: [ocr-and-documents, research-paper-writing]
---

# ARXIV RESEARCH

Search + retrieve academic papers. arXiv API = discovery (Atom XML, no key).
Semantic Scholar = citations/related work/authors (JSON, no key, 1 req/sec).
All calls run through the `terminal` tool (curl/python). No pip installs needed.

## TOOLS

- `terminal(command="curl -s '<url>'")` — hit the arXiv or Semantic Scholar API.
- `terminal(command="python scripts/search_arxiv.py '<query>'")` — clean search (stdlib only).
- `web_extract(url="https://arxiv.org/abs/<id>")` — read a paper's abstract page.
- `web_extract(url="https://arxiv.org/pdf/<id>")` — read the full paper as text.
- `read_file("scripts/search_arxiv.py")` — inspect the helper if a flag is unclear.

## HELPER SCRIPT (preferred for search)

`scripts/search_arxiv.py` parses the Atom XML into readable output. No dependencies.

```bash
python scripts/search_arxiv.py "GRPO reinforcement learning"
python scripts/search_arxiv.py "transformer attention" --max 10 --sort date
python scripts/search_arxiv.py --author "Yann LeCun" --max 5
python scripts/search_arxiv.py --category cs.AI --sort date
python scripts/search_arxiv.py --id 2402.03300           # single or comma-separated
```

## RAW ARXIV API (when the helper is not enough)

Endpoint: `https://export.arxiv.org/api/query`. Returns Atom XML.

```bash
# Keyword search, newest first
curl -s "https://export.arxiv.org/api/query?search_query=all:GRPO&sortBy=submittedDate&sortOrder=descending&max_results=5"
# Fetch specific papers by ID
curl -s "https://export.arxiv.org/api/query?id_list=2402.03300,2401.12345"
```

Query prefixes: `all:` `ti:` (title) `au:` (author) `abs:` `cat:` (category) `co:` (comment).
Operators: `+`=AND, `+OR+`, `+ANDNOT+`, `ti:"exact+phrase"`. Encode spaces as `+`.
Sort: `sortBy=relevance|submittedDate|lastUpdatedDate`, `sortOrder=ascending|descending`.
Common categories: `cs.AI cs.CL cs.CV cs.LG cs.CR stat.ML math.OC`. Full taxonomy: https://arxiv.org/category_taxonomy

## READING A PAPER

```
web_extract(url="https://arxiv.org/abs/2402.03300")   # fast: metadata + abstract
web_extract(url="https://arxiv.org/pdf/2402.03300")   # full text
```
For local PDF files (no URL), hand off to the `ocr-and-documents` skill.

## SEMANTIC SCHOLAR (citations, related work, authors)

arXiv has no citation data. Use Semantic Scholar for that. Pipe through `python3 -m json.tool`.

```bash
# Paper impact by arXiv ID
curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300?fields=title,citationCount,influentialCitationCount,year"
# Who cited it / what it cites
curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300/citations?fields=title,year&limit=10"
curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300/references?fields=title,year&limit=10"
# Author profile
curl -s "https://api.semanticscholar.org/graph/v1/author/search?query=Yann+LeCun&fields=name,hIndex,citationCount"
```
Useful fields: `title authors year abstract citationCount influentialCitationCount isOpenAccess openAccessPdf fieldsOfStudy externalIds`.

## BIBTEX

To emit a BibTeX entry, fetch the paper by ID and format the Atom fields (title, authors,
year, primary category, eprint id). Preserve the version suffix (e.g. `1706.03762v7`) you
actually read — a later version can change content and cause citation drift.

## RESEARCH WORKFLOW

1. Discover: `python scripts/search_arxiv.py "<topic>" --sort date --max 10`
2. Assess impact: Semantic Scholar `citationCount` / `influentialCitationCount`.
3. Read: `web_extract(url="…/abs/<id>")`, then `…/pdf/<id>` if you need the full text.
4. Expand: Semantic Scholar `references` + `citations` to find related work.
5. If the run spans many papers, log finds to a file (`append_file`) so nothing is lost.

## ERROR HATCH

- API returns empty/garbled XML or times out twice → simplify the query (drop operators,
  use `all:`) or fall back to `web_search` for the topic, then `web_extract` the result.
- Semantic Scholar 429 (rate limit) → wait, it allows only 1 req/sec; space calls out.
- Result looks withdrawn (summary says "withdrawn"/"retracted") → do not treat as valid.

## DONE WHEN

The user has the paper IDs/links, abstracts or full text they asked for — plus citation
counts or a BibTeX entry if requested.
