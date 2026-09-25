# ApplyFlow ⚡

> **Local, Privacy-First Automated Job Application Engine**  
> Powered by Playwright, Ollama (`llama3.2-vision`), and Accessibility Tree screen inspection.

ApplyFlow eliminates repetitive job application workflows without sacrificing safety or resume quality. It inspects job postings and application forms via **visual screenshots and accessibility tree screen reading**, runs a **brutally honest gap analysis** to assess candidate fit, autofills fields using a **4-stage learning pipeline**, drafts tailored short essays for open-ended questions, and **guarantees a safety halt** before the final submit button.

---

## Key Features

1. **Vision & Screen Reading (Zero HTML Scrape Fragility)**:
   - Captures high-res viewport and full-page screenshots for local multimodal models (`llama3.2-vision`).
   - Uses Playwright's **Accessibility Tree** (`page.accessibility.snapshot()`) to extract semantic form roles (`textbox`, `combobox`, `radio`, `checkbox`, `file`) without getting tripped up by obfuscated class names or dynamic SPA frameworks.

2. **The Brutally Honest Match Scorer**:
   - Evaluates hard constraints (YOE, required stack, degree, clearance, visa sponsorship).
   - Generates an unvarnished **Estimated Callback Chance (0–100%)**, 2–3 blunt rejection risk points, and candidate strengths.
   - Prompts you before touching a single field: *Do you want to proceed with application autofill based on this score? [y/n]*.

3. **4-Stage Value Resolution & Self-Expanding Knowledge Bank**:
   - **Stage 1 (Direct Profile)**: Canonical resume fields (`name`, `email`, `phone`, `links`, `location`).
   - **Stage 2 (QA Bank Match)**: Semantic and token similarity lookup in `data/qa_bank.json`.
   - **Stage 3 (Interactive Learning)**: Pauses execution if a field is unknown, prompts you in the CLI, and **auto-persists** your answer so it is never asked again.
   - **Stage 4 (AI Essay Synthesis)**: For open-ended questions (*"Why this company?"*), drafts a punchy 3–4 sentence answer using your profile and the job description, presenting `[Accept / Edit / Skip]`.

4. **File Upload Handling**:
   - Automatically detects resume file inputs and attaches your configured PDF (`data/user_profile.json`).

5. **Pre-Flight Review & Safety Gate**:
   - Leaves the visible browser window open on your screen.
   - Displays a clean pre-flight summary table.
   - **Strict Guarantee**: NEVER clicks the final submit button automatically without your explicit confirmation (`[y/N]`).
   - Logs every application run, match score, critique, and post-fill screenshot to `data/applications.sqlite`.

---

## File Structure

```
AutoApply2/
├── data/
│   ├── user_profile.json       # Canonical candidate resume & preferences
│   ├── qa_bank.json            # Persistent self-expanding Q&A bank
│   ├── applications.sqlite     # SQLite log of runs and critiques
│   ├── sample_resume.pdf       # Default PDF for file upload
│   └── screenshots/            # Ingestion & post-fill visual captures
├── src/
│   ├── config.py               # Path constants, Ollama models, browser settings
│   ├── storage.py              # Profile, QA store, and SQLite handlers
│   ├── scorer.py               # Cynical recruiter gap analysis & essay synthesis
│   ├── extractor.py            # Screen reading, screenshots, and form element mapper
│   ├── filler.py               # Playwright autofill execution & interactive prompt
│   └── main.py                 # Interactive Typer/Rich CLI driver
├── tests/
│   ├── mock_ats_server.py      # Local ATS server simulating Greenhouse/Lever/Ashby
│   ├── test_storage.py         # Unit tests for storage & pattern matching
│   └── test_scorer.py          # Unit tests for gap scoring & JSON schema
├── requirements.txt
└── README.md
```

---

## Quickstart Guide

### 1. Requirements & Dependencies
Ensure Python 3.10+ is installed:
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Local Models (Ollama)
ApplyFlow integrates with your local Ollama instance (`http://localhost:11434`):
```bash
ollama serve
# Recommended models:
ollama pull llama3.2-vision:latest
```
*(If a specific model is not pulled, ApplyFlow automatically falls back to your available local models or intelligent heuristics).*

---

## Launching the GUI Dashboard (Recommended)

To run ApplyFlow in the modern web GUI:
```bash
python run_gui.py
```
*(or `python -m src.main gui`)*

This starts the local dashboard at `http://127.0.0.1:5000/` and opens your default browser automatically.

### What the GUI Provides:
* **🚀 Apply Tab**: Enter any job posting URL or click **"Use Mock ATS"** for instant 1-click testing. Shows the live screenshot, the **Brutally Honest Scorecard** (0–100% chance gauge, brutal reality bullets, dealbreaker flags), and a **"Proceed with Autofill ⚡"** button.
* **❓ Interactive Modals**: If an unknown field is encountered, a popup asks you for the answer and auto-persists it to `qa_bank.json`. If an open-ended essay question is found, the local model drafts an answer and presents `[Accept / Edit / Skip]`.
* **🛡️ Pre-Flight Review**: Shows filled fields summary, post-fill screenshot, and pauses safely before final submission.
* **👤 Master Profile Tab**: View and edit your personal details, contact info, skills, links, work authorization, and target resume PDF.
* **💡 QA Bank Tab**: Search, view, add, or delete learned question patterns and answers.
* **📊 Application History Tab**: Audit log of previous runs, match scores, and status.
* **🔐 Browser Sessions & LinkedIn Login**: Log into LinkedIn, Indeed, or custom job boards once. All session cookies and 2FA tokens persist in `data/browser_profile/`, allowing ApplyFlow to bypass authwalls and automate LinkedIn Easy Apply flows.
* **🧪 1-Click Mock ATS Controller**: Start or stop the local test server with a single click.

---

## LinkedIn & External Portal Authentication

Many job boards (especially **LinkedIn**) require authentication before revealing full job descriptions or allowing Easy Apply submissions. ApplyFlow uses anti-detection persistent browser contexts:

### 1. In the Web Dashboard:
- Click **"🔐 Browser Sessions"** in the sidebar (or the **"🔐 Login"** button beside the URL input).
- Click **"🚀 Open LinkedIn Login"**. A visible browser window will open on your screen.
- Log in, complete any 2FA/SMS verification, and make sure your feed loads.
- Click **"✅ Done / Save Session"**.
- Your login state is saved permanently in `data/browser_profile/`. From then on, any LinkedIn job link you paste will load in your authenticated session!
- If you scan a link that requires login before you've authenticated, ApplyFlow automatically detects the authwall and displays a sign-in prompt with 1-click retry.

### 2. In the CLI:
To sign into your accounts from the terminal:
```bash
python -m src.main login linkedin
# Or for Indeed:
python -m src.main login indeed
```
Log into your account in the browser that opens, press Enter in the terminal, and your session will be remembered across all applications!

---

## CLI Usage (Alternative)

If you prefer using the terminal instead:
```bash
python -m src.main login linkedin     # Save persistent login session
python -m src.main apply <URL>        # Run screen ingestion & autofill
python -m src.main profile            # View canonical candidate profile
python -m src.main qa                 # View and search QA Knowledge Bank
python -m src.main history            # View audit log of application runs
python -m src.main test-server        # Start local mock ATS test server
```

---

## Local Testing with the Built-in Mock ATS Server

To safely test the entire visual autofill flow on your screen without applying to real companies:

1. **Terminal 1 — Launch the Local Mock ATS Server:**
   ```bash
   python -m src.main test-server
   ```
   *This starts a realistic Greenhouse/Lever-style application form on `http://127.0.0.1:8088/`.*

2. **Terminal 2 — Run ApplyFlow Against the Mock Server:**
   ```bash
   python -m src.main apply http://127.0.0.1:8088/
   ```

3. **What You Will See:**
   * A Chromium window will open on your screen.
   * ApplyFlow reads the screen, saves an initial screenshot, and calculates the Brutally Honest Match Scorecard.
   * You confirm `[y/n]` to proceed with autofill.
   * Fields are typed, radio buttons selected, dropdowns picked, and your resume PDF attached.
   * For the open-ended question (*"Why do you want to join our engineering team?"*), the local model drafts an answer and prompts you to Accept / Edit / Skip.
   * ApplyFlow halts before the submit button, prints a Pre-Flight Summary Table, and asks:
     `Review completed form on screen. Submit? [y/N]`
