# Agentic RFP Evaluation and Supplier Ranking

Procurement dashboard for fictional supplier proposals. A model reads one proposal at a time and returns criterion scores, evidence, and a justification. Python calculates the weighted score, peer benchmarks, the Peer Performance Index (PPI), and the final rank. Results are stored in SQLite and shown in Streamlit.

The same validated scorecards always produce the same scores and order. The model does not calculate weights, benchmarks, gaps, PPI, tie-breaks, or rank.

## Features

- Five seeded criteria. Active criteria can be turned on or off, and their weights and maximum scores can be edited. Active weights must total exactly 100 before a run.
- Multiple PDF uploads, with a supplier name, submission date, and historical experience rating from 1 to 5 for each file.
- Text extraction, one model call per supplier, and JSON validation before scoring.
- Leaderboard, criterion scorecards, tie-break explanation, warnings, and a JSON download.
- Failed suppliers are saved and shown separately. They do not receive an ordinary score or a rank.
- Previous runs can be reopened from the database.

## Architecture and data flow

```text
Streamlit
  -> load or edit criteria in SQLite
  -> user uploads PDFs and metadata, then clicks Evaluate suppliers
  -> orchestrator
       1. validate names, dates, and experience ratings
       2. load active criteria and require weights of 100
       3. create one RFP_RUN_ID
       4. extract text from each PDF
       5. ask the model for JSON for that supplier only
       6. validate and normalize the JSON
       7. score, benchmark, and rank the successful suppliers
       8. save the run and every supplier in one transaction
  -> leaderboard, scorecards, and JSON download
```

| Piece | Responsibility |
| --- | --- |
| `app.py` | Screens, uploads, progress, and download. No scoring math. |
| `orchestrator.py` | Calls the steps in order and records failures. |
| `pdf_extract.py` | Reads text with pypdf. |
| `llm_client.py` | Builds the prompt and calls OpenAI chat completions. The key is read at call time. |
| `validation.py` | Checks the JSON, fills a missing criterion with score 0 and an explicit warning, and clips finite out-of-range scores. |
| `scoring.py` | Absolute score, benchmark, gap, relative percentage, and PPI. Leaves rank empty. |
| `ranking.py` | Sorts, then assigns ranks 1, 2, 3, and so on. |
| `db.py` | Schema, seed, criteria edits, and run persistence. |

Proposal text is wrapped as untrusted data. Instructions inside a PDF are not followed as system instructions.

## Project folder structure

```text
app.py                     Streamlit entry point
requirements.txt           Runtime and test dependencies
runtime.txt                Python version pin for Streamlit Community Cloud
pytest.ini
.env.example               Empty key template
.gitignore
README.md
.streamlit/config.toml     Local theme
src/rfp_eval/              Application package
tests/                     Offline pytest suite
sample_proposals/          Four fictional PDFs
sample_output/             Synthetic JSON export
scripts/                   Database seed, PDF regeneration, sample export
data/                      Local SQLite file, created on first run and not committed
```

## Local setup

These commands were used on Python 3.9.6. The code also targets the Python 3.11 pin in `runtime.txt`. That Cloud pin has not been executed in this workspace.

```bash
cd "/Users/sangelo/Downloads/Cursor data/agentic-rfp-evaluation"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create the database and seed the five criteria. The Streamlit app does this on startup as well.

```bash
python scripts/initialize_database.py
```

Regenerate the fictional PDFs if you want to rebuild them:

```bash
python scripts/generate_proposals.py
```

## API key configuration

Copy the template and put your own key in `.env`. Leave this file uncommitted.

```bash
cp .env.example .env
```

```text
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-4o-mini
```

The app loads `.env` when it starts. A variable that is already set in the environment wins over `.env`. Streamlit secrets are used when both the environment and `.env` are blank. The key is not written into source, the database, or the sample export.

You can set the same values in `.streamlit/secrets.toml` instead of `.env`:

```toml
OPENAI_API_KEY = "your-key-here"
OPENAI_MODEL = "gpt-4o-mini"
```

That file is gitignored.

## Run the app and the tests

```bash
streamlit run app.py
```

Open the local URL Streamlit prints. Use **Criteria**, **Evaluate**, and **Results**.

Nothing is sent to the model until you click **Evaluate suppliers**. A completed batch cannot be submitted again until the supplier names, dates, experience ratings, or file names change.

```bash
pytest
```

From the project directory with the virtual environment active, that is the full offline suite. It does not need an API key and does not call the network.

Rebuild the synthetic export, which also uses the fake model:

```bash
python scripts/export_synthetic_run.py
```

## Scoring and PPI

Seeded criteria, all active, each with a maximum score of 10:

| Criterion | Weight |
| --- | --- |
| Technical Capability | 30 |
| Implementation Plan | 20 |
| Commercial Value | 20 |
| Security & Compliance | 20 |
| Support & Experience | 10 |

Absolute weighted score:

```text
sum of (criterion score / maximum score) x criterion weight
```

A perfect score on every seeded criterion is 100.

For one run, using only suppliers that scored successfully:

- Benchmark is the highest raw score for that criterion.
- Gap is the supplier score minus the benchmark. The leader's gap is 0.
- Relative performance is `(score / benchmark) x 100`.
- If the benchmark is 0, the relative performance is 0 and the run stores a warning. There is no division by zero.

PPI is the weighted average of those relative percentages:

```text
sum of (relative performance x criterion weight) / 100
```

PPI is on a 0 to 100 scale when the active weights total 100.

Historical experience is the integer the user enters, from 1 to 5. The model does not score it.

## Ranking and tie-breaks

Ranks are assigned only after this sort:

1. Higher PPI
2. Earlier submission date
3. Higher experience rating
4. Supplier name from A to Z

`score_suppliers` leaves `final_rank` empty. `rank_suppliers` sorts first and then writes 1, 2, 3, and so on. The Results screen explains each adjacent pair from the stored values.

## Database schema

`evaluation_criteria`

- `criterion_id`, `name`, `description`, `weight`, `max_score`, `is_active`
- Weight must be from 1 to 100. Maximum score must be positive.
- Rows are seeded only when the table is empty.

`rfp_runs`

- `rfp_run_id`, `created_at`, `status`
- Status is `completed`, `completed_with_failures`, or `failed`.

`supplier_results`

- `rfp_run_id`, `supplier_name`, `submission_date`, `experience_rating`
- `absolute_score`, `ppi`, `final_rank`, `result_json`
- Score, PPI, and rank are null for a supplier that failed extraction, the model call, or JSON validation.
- `result_json` must be valid JSON and holds the scorecard or the failure record.
- A run and its supplier rows are written in one transaction.

The app database path is `data/rfp_eval.db`.

## Error handling

- Missing or blank supplier names, invalid dates, duplicate names, and experience ratings outside 1 to 5 stop the batch before any model call.
- Active weights that are not exactly 100 block evaluation. The edited criteria are still saved.
- An empty, unreadable, encrypted, or image-only PDF is an extraction failure for that supplier.
- A missing API key, model error, malformed JSON, wrong supplier name, or non-finite score is recorded for that supplier. Other suppliers in the batch continue.
- A missing criterion becomes score 0 with the text "No model result was returned for this criterion." and "No evidence was provided." A finite score outside 0 to the configured maximum is clipped. The configured maximum score wins over the number returned by the model.
- The screen shows a success message only when the status is `completed`.

## Sample JSON

`sample_output/synthetic_rfp_run.json` is a completed four-supplier run. The `notice` field states that it is synthetic test data from the offline fake model. The model responses are fixed numbers, not live citations from the PDFs. Python still extracted the PDFs, scored them, ranked them, saved the run, and reloaded it.

In that file the order is NexaWorks, Apex Systems, BrightPath Tech, then Orbit Digital. Absolute scores are 81, 76, 62, and 56. The download button in the app returns the same run fields without the extra `notice` key.

## Fictional proposals

Each file in `sample_proposals/` is 3 pages and includes the six required sections: executive summary, solution and implementation, timeline and team, price table, security and compliance, and support and references.

| File | Profile |
| --- | --- |
| `apex_systems.pdf` | Strong technical design and security, higher price, 16-week schedule |
| `brightpath_tech.pdf` | Lowest price, 8-week schedule, limited compliance and experience |
| `nexaworks.pdf` | Balanced proposal, strongest implementation plan and support model |
| `orbit_digital.pdf` | Stronger experience and three fictional references, vague integration plan, medium price |

Prices, organizations, and references are invented. Each proposal says it is a fictional classroom proposal and that no real certification is claimed.

## Error demonstration without a second code path

Use one valid sample PDF and one PDF that contains no text, such as an empty or scanned file. Give both a name, a date, and an experience rating, then click **Evaluate suppliers**. The valid supplier is ranked. The unreadable file is listed under suppliers that were not ranked, with an extraction error. The run status is `completed_with_failures`, and the page does not show a success message.

A missing API key fails before scoring and leaves the previous database unchanged.

## GitHub and Streamlit Community Cloud

This phase did not create a remote, push code, or deploy the app. Do those steps only after you approve them.

The repository root must be this project directory, so `app.py` stays at the root. Do not push the parent `Cursor data` folder.

1. Create a GitHub repository.
2. Confirm `.env`, `.streamlit/secrets.toml`, and `data/*.db` are not staged. `.gitignore` excludes them.
3. Push the project. Do not put a key in the commit, the README, or the secrets example.
4. In [Streamlit Community Cloud](https://share.streamlit.io/), choose **Create app**.
5. Select the repository and branch. Set **Main file path** to `app.py`.
6. Open **Advanced settings** before the first deploy. `runtime.txt` asks Cloud for Python 3.11.
7. Under **Secrets**, paste:

```toml
OPENAI_API_KEY = "your-key-here"
OPENAI_MODEL = "gpt-4o-mini"
```

8. Deploy, then run one successful batch and one extraction-failure batch in the hosted app.

Cloud installs from `requirements.txt`. The app finds the package through the `src` path inserted by `app.py`.

## Known limitations

- Tests and the sample export were run locally on Python 3.9.6. The Cloud Python 3.11 pin has not been deployed or tested here.
- Streamlit Community Cloud storage is ephemeral. `data/rfp_eval.db` can disappear on reboot, redeploy, or a moved container. Hosted criteria edits and run history are not durable, and this project has not verified otherwise.
- The hosted app is one shared SQLite file. It is not a multi-user system of record, and concurrent writes can fail.
- Model output can change between model versions even with temperature 0. Formulas and ordering are stable only after a scorecard has been validated.
- Experience rating is typed by the user. It is not inferred from the PDF.
- Image-only and encrypted PDFs cannot be scored.
- The README does not include screenshots. Capture them from a local or hosted run before submission. This phase did not open a live model session for that purpose.
- `fpdf2` is required to regenerate the sample PDFs. `pytest` is included so one install supports both the app and the suite. Neither is used on the evaluation request path.
