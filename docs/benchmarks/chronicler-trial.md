> **Classification:** HISTORICAL.
> **Superseded by:** [`docs/CONTINUE_FROM_HERE.md`](../../docs/CONTINUE_FROM_HERE.md) (or `../../../docs/CONTINUE_FROM_HERE.md` from `dev/docs`).
> This is dated evidence. It may reference an old branch, HEAD, dirty worktree, or schedule. Do not treat it as current status, implementation order, or release qualification.

# Chronicler Trial — evidence contract

This is an integration benchmark, not a declaration of production readiness
or a general intelligence score. Run through the gateway on :8810 and native
MCP on :8811. No UI dependency and no change to the Assistant identity.

The trial tests research, uncertainty, representations and persistent memory
separately. A fluent answer cannot substitute for tool receipts. An unavailable
dependency is **blocked/unknown**, never a pass. One trial cannot prove
"unbroken memory", lifelong learning, or superiority to another framework.

## Mission sent to the native agent

<!-- BEGIN MISSION -->
Investigate the climate disturbances of 536–540 CE and possible effects in
Byzantine, Chinese and Mesoamerican societies. Remain the existing Assistant;
Chronicler is a task designation, not a new character or avatar.

Use live research tools to examine primary scientific papers, their data and
historical sources. Cover ice-core evidence, tree-ring evidence and historical
accounts. Check the suitability, dates and exact passages of Procopius,
Cassiodorus and the Book of Southern Qi before citing them. Do not invent a
passage when a named source does not cover the event. Check claims about
European oaks and North American bristlecone pines against the actual datasets.

Compare volcanic and comet explanations using evidence. Investigate the
proposed chain from diminished sunlight to crop losses, famine, the plague
beginning in 541 CE and political changes. Mark each connection as supported,
hypothesis, disputed or unknown. Chronological sequence is not causal proof.
Check regional differences and competing eruption dates. Offer a useful
cross-domain comparison; do not claim it is novel without evidence.

Produce three written representations: a Mermaid causal DAG with uncertainty
on its edges; a roughly 60-second spoken script (125–165 words, with separate
cadence instructions); and a table comparing the three regions. A script is
not rendered audio. Do not play audio or send/publish anything externally.

Use record_insight to archive the principal findings with sources and
uncertainty. Use the research topic supplied below; do not store them as
personal facts about the owner. Archive exactly two open research questions
under IDs question-1 and question-2, epistemic_status open_question. Public
research is authorized for Honcho: set share_publicly_with_honcho true. Report
local and Honcho receipts separately. Never claim remote persistence if the
service cannot be reached or the record cannot be read back. No shell,
file modification, delegation, or scheduling is necessary for this trial.
Use at most 20 tool calls: reserve eight for archiving and checking records,
and spend at most twelve on research. Archive the two open questions before
optional additional findings. Treat a search with no matches as an evidence
gap; do not keep adding search terms indefinitely. Use known source URLs
when available. Stop and report missing evidence if blocked.

Return one JSON object (no prose outside it) with:
- sources: [{id, url, title, domain, locator}]; domains ice_core, tree_ring,
  historical; locators identify the passage, figure or data used;
- claims: [{id, text, status, source_ids}]; status supported, hypothesis,
  disputed or unknown;
- causal_edges: [{from, to, status, source_ids}]; reference claim IDs;
- mermaid: string;
- spoken_script: string, cadence: string;
- regions: [{region, finding, uncertainty, source_ids}]; region Byzantine,
  Chinese, Mesoamerican;
- open_questions: exactly two strings, matching the archived question IDs;
- limitations: array of strings, including missing data/tools/receipts.

Correct questionable premises rather than forcing the requested narrative.
<!-- END MISSION -->

## Operator commands

Use the external environment and write all evidence outside the checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 ~/.jaeger/venv/bin/python scripts/benchmark-chronicler.py start --output-dir ~/.jaeger/audits/chronicler-001
PYTHONDONTWRITEBYTECODE=1 ~/.jaeger/venv/bin/python scripts/benchmark-chronicler.py collect --output-dir ~/.jaeger/audits/chronicler-001
PYTHONDONTWRITEBYTECODE=1 ~/.jaeger/venv/bin/python scripts/benchmark-chronicler.py recall --output-dir ~/.jaeger/audits/chronicler-001
```

Use `collect` after the first process exits if observation timed out. It only
reads the original request and reconciles its native receipt; it never submits
the mission again. `start` and `collect` return exit code 2 for an incomplete
trial, even when native execution succeeded, because research review and the
delayed check remain outstanding.

The `recall` command refuses to mark the two-hour check complete before its
deadline. It starts a fresh process and reads the exact archived question
from local memory and Honcho independently, without sending the answer to an
LLM. This proves storage retrieval, **not agent recall or a heartbeat**. A
separate fresh native chat must call recall_insight and correctly answer to
prove agent retrieval; gateway lead sessions deliberately share dispatcher.
No benchmark should clear the real dispatcher conversation to simulate this.
The runner records pending work; it does not install an unattended scheduler.

The report retains the gateway request receipt, source snapshot hashes, native
trace slice, generated response and memory readbacks. Trace tools indicate
observed execution, but redacted trace contents alone cannot prove which
source a tool returned. Review source passages manually before awarding the
research-quality pass. Markdown table/script checks are separate from audio
generation. No audio pass is awarded by this runner.

## Research review traps and references

These are reviewer starting points, not a canned answer or a closed truth set.
The agent should resolve conflicting evidence rather than merely repeat them.

- [Sigl et al. (2015), Nature](https://pubmed.ncbi.nlm.nih.gov/26153860/):
  synchronized ice-core chronology and volcanic forcing, DOI 10.1038/nature14565.
- [Büntgen et al. (2016), Nature Geoscience](https://www.nature.com/articles/ngeo2652):
  tree-ring reconstruction and proposed societal connections. Read methods;
  do not substitute a requested species for the species actually studied.
- [Book of Southern Qi, primary text](https://ctext.org/wiki.pl?if=en&res=831146):
  verify dynastic coverage and the purported 536 passage. A book compiled in
  the sixth century does not necessarily chronicle sixth-century events.
- [Smith et al. (2020), PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC7584997/):
  dates Ilopango TBJ to 431 ± 2 CE; do not present the contested 540 attribution
  as settled or infer a uniform Maya collapse from this eruption.
- [Mordechai et al. (2019), PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC6926030/)
  and [Zonneveld et al. (2024), Science Advances](https://doi.org/10.1126/sciadv.adk1033):
  distinguish evidence for disease/climate association from a demonstrated
  causal mechanism and uniform regional consequences.

Research review: verify each source exists and supports its linked claim;
check chronology and regional precision; inspect every causal arrow;
preserve uncertainty across diagram, script and table. Unsupported confident
causation fails even if structural and memory checks pass.
