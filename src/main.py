"""Main CLI Driver for ApplyFlow.

Runs the end-to-end automated job application pipeline:
1. Ingestion & Visual Capture
2. Brutally Honest Match Scoring
3. Accessibility & DOM Form Extraction
4. Multi-Stage Value Resolution & Autofill
5. Pre-Flight Review & Safety Gate
"""

from datetime import datetime
import json
from pathlib import Path
import sys
import time
from typing import Optional
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
import typer

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.browser import (
    create_persistent_context,
    detect_authwall_or_login,
)
from src.config import (
    BROWSER_PROFILE_DIR,
    BROWSER_TIMEOUT_MS,
    HEADLESS,
    SLOW_MO_MS,
    USER_AGENT,
    VIEWPORT,
)
from src.extractor import FormExtractor
from src.filler import FormFiller
from src.scorer import JobScorer
from src.storage import StorageManager, UserProfile


app = typer.Typer(help="ApplyFlow: Local Automated Job Application Assistant")
console = Console(legacy_windows=False)


def display_banner():
    """Renders ApplyFlow CLI header."""
    console.print(
        Panel.fit(
            "[bold cyan]>> APPLYFLOW[/bold cyan] | [bold white]Local Automated Job Application Engine[/bold white]\n"
            "[dim]Privacy-First - Vision & Accessibility Inspection - Brutally Honest Gap Analysis[/dim]",
            border_style="cyan",
        )
    )


def run_apply_pipeline(url: str):
    """Executes the full end-to-end application flow for a target job URL."""
    display_banner()
    storage = StorageManager()
    profile = storage.load_profile()
    scorer = JobScorer()

    console.print(f"\n[bold blue]>> Target URL:[/bold blue] [underline]{url}[/underline]")
    console.print("[dim]Launching browser and capturing page screen...[/dim]")

    with sync_playwright() as p:
        context = create_persistent_context(
            p,
            headless=HEADLESS,
            slow_mo=SLOW_MO_MS,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(BROWSER_TIMEOUT_MS)

        try:
            # Step 1: Ingestion & Screen Reading
            console.print("[cyan]>> Navigating to job posting...[/cyan]")
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(2.5)

            # Check if redirected to login / authwall (e.g. LinkedIn)
            auth_check = detect_authwall_or_login(page)
            if auth_check["auth_required"]:
                console.print(f"\n[bold yellow]🔐 Authentication Required ({auth_check['platform']}):[/bold yellow]")
                console.print(f"[cyan]Please complete login in the open browser window to view this job posting.[/cyan]")
                Prompt.ask("Press Enter once you have finished logging in")
                page.goto(url, wait_until="domcontentloaded")
                time.sleep(2)

            extractor = FormExtractor(page)
            job_info = extractor.extract_job_info()

            console.print(f"[bold green][+] Ingested Posting:[/bold green] [bold white]{job_info.title}[/bold white] at [bold cyan]{job_info.company}[/bold cyan]")
            if job_info.screenshot_path:
                console.print(f"[dim]  Initial screen snapshot saved: {job_info.screenshot_path}[/dim]")

            # Step 2: The Brutally Honest Match Scorer
            console.print("\n[bold yellow][*] Running Brutal Candidate Gap Analysis...[/bold yellow]")
            score_result = scorer.score_match(
                job_title=job_info.title,
                company=job_info.company,
                job_description=job_info.description,
                user_profile=profile,
                screenshot_path=job_info.screenshot_path,
            )

            # Display scorecard
            chance = score_result.estimated_callback_chance
            chance_color = "red" if chance < 35 else ("yellow" if chance < 65 else "green")

            score_table = Table(title="Brutally Honest Match Scorecard", border_style="yellow")
            score_table.add_column("Metric", style="bold")
            score_table.add_column("Assessment", style="white")

            score_table.add_row(
                "Estimated Callback Chance",
                f"[{chance_color}]{chance}%[/{chance_color}] ({score_result.recommendation})",
            )
            
            critique_bullets = "\n".join([f"- {b}" for b in score_result.brutal_reality])
            score_table.add_row("The Brutal Reality", f"[red]{critique_bullets}[/red]")

            strengths_bullets = "\n".join([f"- {s}" for s in score_result.strengths])
            score_table.add_row("Key Strengths", f"[green]{strengths_bullets}[/green]")

            if score_result.dealbreakers:
                db_bullets = "\n".join([f"- {d}" for d in score_result.dealbreakers])
                score_table.add_row("Flagged Dealbreakers", f"[bold red]{db_bullets}[/bold red]")

            console.print(score_table)

            # User confirmation gate
            proceed = Confirm.ask(
                "\nDo you want to proceed with application autofill based on this score?",
                default=chance >= 40,
            )

            app_id = f"app_{int(time.time())}"
            if not proceed:
                console.print("[yellow]Application aborted by user. Logging decision...[/yellow]")
                storage.log_application(
                    app_id=app_id,
                    job_title=job_info.title,
                    company=job_info.company,
                    url=url,
                    match_score=chance,
                    brutal_critique="\n".join(score_result.brutal_reality),
                    status="ABORTED_BY_USER",
                    screenshot_path=job_info.screenshot_path,
                )
                context.close()
                return

            # Step 3: Ensure Application Form is Open & Scan Fields
            console.print("\n[bold blue]>> Opening & Inspecting Application Form...[/bold blue]")
            form_ready = extractor.ensure_application_form_open()
            if not form_ready:
                console.print("[yellow]Note: No distinct application form detected. Inspecting current page inputs...[/yellow]")

            # Step 4: Populate Fields Sequentially (Supports Multi-Step Forms & Easy Apply)
            console.print("\n[bold blue]>> Executing Autofill Pipeline...[/bold blue]")
            filler = FormFiller(
                page=page,
                storage=storage,
                scorer=scorer,
                user_profile=profile,
                job_title=job_info.title,
                company=job_info.company,
                job_description=job_info.description,
            )

            fill_summary = filler.fill_multi_step_form(extractor)

            # Step 5: Pre-Flight Review & Visual Capture
            post_screenshot = extractor.capture_screenshot("post_fill")

            summary_table = Table(title="Pre-Flight Autofill Summary", border_style="cyan")
            summary_table.add_column("Field", style="bold")
            summary_table.add_column("Status", style="cyan")
            summary_table.add_column("Value / Source", style="white")

            for item in fill_summary.details:
                st = item["status"]
                st_color = "green" if st == "FILLED" else ("yellow" if st == "SKIPPED" else "red")
                val_disp = item["value"][:45] + ("..." if len(item["value"]) > 45 else "")
                summary_table.add_row(item["field"], f"[{st_color}]{st}[/{st_color}]", val_disp)

            console.print("\n")
            console.print(summary_table)

            console.print(
                Panel.fit(
                    f"[bold green]Autofill Complete:[/bold green] "
                    f"[white]{fill_summary.fields_filled}[/white] filled, "
                    f"[white]{fill_summary.fields_skipped}[/white] skipped, "
                    f"[white]{fill_summary.questions_added_to_qa}[/white] new question(s) saved to QA bank.\n"
                    f"[dim]Post-fill verification screenshot: {post_screenshot}[/dim]",
                    border_style="green",
                )
            )

            # Final Safety Confirmation Gate
            console.print(
                Panel(
                    "[bold yellow][!] SAFETY GATE: Final Submission Confirmation[/bold yellow]\n\n"
                    "ApplyFlow will [bold red]NEVER[/bold red] automatically click final submit.\n"
                    "The browser window is open in front of you.\n"
                    "1. Review all pre-filled fields on screen.\n"
                    "2. Adjust any values directly in the browser if needed.",
                    border_style="yellow",
                )
            )

            submit_choice = Prompt.ask(
                "Review completed form on screen. Submit? [y/N]",
                choices=["y", "n", "Y", "N"],
                default="N",
            )

            final_status = "READY_FOR_SUBMIT"
            if submit_choice.lower() == "y":
                # Find submit button and submit
                submit_btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Submit Application')").first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    console.print("[bold green]Application submitted successfully![/bold green]")
                    final_status = "SUBMITTED"
                    time.sleep(3)
                else:
                    console.print("[yellow]Submit button not automatically found. Please click Submit in the browser window.[/yellow]")
                    Prompt.ask("Press Enter after you submit in the browser window")
                    final_status = "SUBMITTED_MANUALLY"
            else:
                console.print("[dim]Form left unsubmitted as requested.[/dim]")
                final_status = "REVIEWED_NOT_SUBMITTED"

            # Log to SQLite
            storage.log_application(
                app_id=app_id,
                job_title=job_info.title,
                company=job_info.company,
                url=url,
                match_score=chance,
                brutal_critique="\n".join(score_result.brutal_reality),
                status=final_status,
                screenshot_path=post_screenshot,
            )
            console.print(f"[dim]Run logged to database: {storage.db_path}[/dim]")

        except Exception as e:
            console.print(f"\n[bold red]Pipeline Error:[/bold red] {e}")
            raise e
        finally:
            context.close()


@app.command()
def login(
    platform: str = typer.Argument("linkedin", help="Platform to log into (e.g. linkedin, indeed, custom)"),
    url: Optional[str] = typer.Option(None, help="Custom login URL"),
):
    """Opens a persistent browser session so you can log into LinkedIn, Indeed, etc."""
    target_url = url
    if not target_url:
        p_lower = platform.lower()
        if "link" in p_lower:
            target_url = "https://www.linkedin.com/login"
        elif "indeed" in p_lower:
            target_url = "https://secure.indeed.com/account/login"
        else:
            target_url = "https://www.linkedin.com/login"

    console.print(f"\n[bold cyan]>> Launching persistent browser for {platform}...[/bold cyan]")
    console.print(f"[dim]URL: {target_url}[/dim]")
    console.print(f"[dim]Session profile saved to: {BROWSER_PROFILE_DIR}[/dim]\n")

    with sync_playwright() as p:
        context = create_persistent_context(p, headless=False, slow_mo=0)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target_url)

        console.print("[bold green][+] Browser window is open on your screen.[/bold green]")
        console.print("[yellow]Please sign into your account, complete 2FA if prompted, and verify you are on your feed/dashboard.[/yellow]")
        Prompt.ask("\nPress [bold white]Enter[/bold white] here once you are logged in to save your session")
        context.close()
        console.print("[bold green][✓] Session saved! Your credentials and cookies are now remembered for all applications.[/bold green]\n")


@app.command()
def apply(url: str = typer.Argument(..., help="Job posting URL to apply to")):
    """Run the complete ApplyFlow pipeline for a job posting URL."""
    run_apply_pipeline(url)


@app.command()
def profile():
    """Display the candidate's canonical profile."""
    display_banner()
    storage = StorageManager()
    p = storage.load_profile()

    t = Table(title="Master Candidate Profile", border_style="cyan")
    t.add_column("Category", style="bold cyan")
    t.add_column("Details", style="white")

    t.add_row(
        "Personal",
        f"Name: {p.personal.full_name}\nEmail: {p.personal.email}\nPhone: {p.personal.phone}\nLocation: {p.personal.city}, {p.personal.state}",
    )
    links_str = "\n".join([f"{k}: {v}" for k, v in p.links.items() if v])
    t.add_row("Links", links_str or "None")

    skills_str = ", ".join(p.skills)
    t.add_row("Skills", skills_str)

    auth_str = f"US Auth: {p.authorization.get('us_work_authorized', 'N/A')}\nSponsorship: {p.authorization.get('requires_sponsorship', 'N/A')}\nClearance: {p.authorization.get('security_clearance', 'N/A')}"
    t.add_row("Work Auth", auth_str)

    exp_str = "\n".join([f"• {exp.get('title')} @ {exp.get('company')}" for exp in p.work_experience])
    t.add_row("Work History", exp_str)

    console.print(t)
    console.print(f"[dim]Profile file path: {storage.profile_path}[/dim]")


@app.command()
def qa():
    """List all saved Q&A patterns in the persistent knowledge bank."""
    display_banner()
    storage = StorageManager()
    qa_list = storage.load_qa_bank()

    t = Table(title=f"QA Knowledge Bank ({len(qa_list)} entries)", border_style="magenta")
    t.add_column("ID", style="bold")
    t.add_column("Category", style="cyan")
    t.add_column("Recognized Patterns", style="dim")
    t.add_column("Saved Answer", style="bold green")

    for entry in qa_list:
        pats = "\n".join([f"• {p}" for p in entry.question_patterns[:2]])
        t.add_row(entry.id, entry.category, pats, entry.answer)

    console.print(t)
    console.print(f"[dim]QA Bank file path: {storage.qa_path}[/dim]")


@app.command()
def history(limit: int = typer.Option(10, help="Number of records to show")):
    """View application history logged in SQLite."""
    display_banner()
    storage = StorageManager()
    logs = storage.get_history(limit=limit)

    if not logs:
        console.print("[dim]No applications logged yet.[/dim]")
        return

    t = Table(title=f"Application Run History (Last {len(logs)})", border_style="blue")
    t.add_column("Date", style="dim")
    t.add_column("Company", style="bold")
    t.add_column("Title", style="white")
    t.add_column("Score", style="yellow")
    t.add_column("Status", style="green")

    for log in logs:
        dt = log.applied_at[:19].replace("T", " ")
        t.add_row(dt, log.company, log.job_title, f"{int(log.match_score)}%", log.status)

    console.print(t)
    console.print(f"[dim]SQLite DB path: {storage.db_path}[/dim]")


@app.command(name="test-server")
def start_mock_server(port: int = typer.Option(8088, help="Port to run mock ATS server on")):
    """Start local mock ATS server to safely test ApplyFlow in browser."""
    display_banner()
    from tests.mock_ats_server import run_mock_server
    console.print(f"[bold green][+] Starting Mock ATS server at http://127.0.0.1:{port}/[/bold green]")
    console.print(f"[cyan]To test autofill, run in another terminal:[/cyan] [bold white]python -m src.main apply http://127.0.0.1:{port}/[/bold white]")
    run_mock_server(port=port)


@app.command(name="gui")
def start_gui(port: int = typer.Option(5000, help="Port for the dashboard web server")):
    """Launch the ApplyFlow modern web GUI dashboard."""
    display_banner()
    from run_gui import launch
    launch(port=port)


if __name__ == "__main__":
    app()


