# Local Data Setup

This repository is intentionally code-only. Official rulebooks, card data,
FAQ, errata, ban lists, scraped pages, and datasets derived from them are not
included in Git.

## Local-only directories

The following paths are ignored by `.gitignore` and must remain local:

```text
规则书/
raw/
rules/
data/
.scrape/
.extracted/
```

## Expected local layout

Create the local files required by the ingestion scripts, for example:

```text
rules/en/core_rules.raw.txt
rules/en/tournament_rules.raw.txt
raw/cards/page_*.json
raw/cards_zh/p*.json
raw/banlist/*.html
raw/errata/*.html
raw/faq/*.html
raw/patches/*.html
```

The source PDFs and API/HTML responses must be obtained from official
channels. Follow the source provider's terms; do not commit downloaded files
or extracted copies.

## Rebuilding local datasets

After preparing the local inputs, run the relevant scripts from the repository
root. For example:

```powershell
$env:PYTHONPATH = "src"
python scripts/ingest_cards.py
python scripts/ingest_cards_zh.py
python scripts/ingest_rules.py
python scripts/ingest_banlist.py
python scripts/ingest_errata.py
python scripts/ingest_faq.py
python scripts/ingest_patch_notes.py
```

The scripts write their outputs under `data/`, which is also local-only. A
fresh clone does not include these files, so data-dependent commands will not
run until the local inputs and datasets have been prepared.

## Security

Never commit API keys. The default LLM configuration lookup uses
`config/llm.json`, which is ignored. Prefer environment variables:

```powershell
$env:RIFTBENCH_LLM_API_KEY = "..."
$env:RIFTBENCH_LLM_BASE_URL = "https://api.deepseek.com/v1"
$env:RIFTBENCH_LLM_MODEL = "deepseek-chat"
```