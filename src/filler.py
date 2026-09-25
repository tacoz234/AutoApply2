"""Form Filler & Playwright Execution Layer for ApplyFlow.

Handles field mapping (Direct Profile -> QA Bank -> Interactive Prompt -> Essay Generation),
Playwright UI interactions (typing, dropdown selection, radio/checkbox clicks, resume attachment),
and safety enforcement.
"""

from pathlib import Path
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from playwright.sync_api import Page, Locator
from rich.console import Console
from rich.prompt import Prompt

from src.extractor import ExtractedField
from src.scorer import JobScorer
from src.storage import StorageManager, UserProfile
import sys

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(legacy_windows=False)


class FillSummary:
    def __init__(self):
        self.fields_filled: int = 0
        self.fields_skipped: int = 0
        self.questions_added_to_qa: int = 0
        self.details: List[Dict[str, Any]] = []


class FormFiller:
    """Executes autofill operations on web forms using multi-stage value resolution."""

    def __init__(
        self,
        page: Page,
        storage: StorageManager,
        scorer: JobScorer,
        user_profile: UserProfile,
        job_title: str = "",
        company: str = "",
        job_description: str = "",
        on_field_fill: Optional[Callable[[str, str, str], None]] = None,
        prompt_callback: Optional[Callable[[ExtractedField], str]] = None,
        essay_callback: Optional[Callable[[str, str], Tuple[str, str]]] = None,
    ):
        self.page = page
        self.storage = storage
        self.scorer = scorer
        self.user_profile = user_profile
        self.job_title = job_title
        self.company = company
        self.job_description = job_description
        self.on_field_fill = on_field_fill
        self.prompt_callback = prompt_callback
        self.essay_callback = essay_callback

    def fill_all_fields(self, fields: List[ExtractedField]) -> FillSummary:
        """Iterates over extracted fields and populates them sequentially."""
        summary = FillSummary()

        for field in fields:
            try:
                filled, val = self._process_and_fill_field(field, summary)
                if filled:
                    summary.fields_filled += 1
                    summary.details.append({"field": field.label, "status": "FILLED", "value": val})
                    if self.on_field_fill:
                        self.on_field_fill(field.label, "FILLED", val)
                else:
                    summary.fields_skipped += 1
                    summary.details.append({"field": field.label, "status": "SKIPPED", "value": ""})
                    if self.on_field_fill:
                        self.on_field_fill(field.label, "SKIPPED", "")
            except Exception as e:
                console.print(f"[yellow]Warning filling field '{field.label}': {e}[/yellow]")
                summary.fields_skipped += 1
                summary.details.append({"field": field.label, "status": "ERROR", "value": str(e)})
                if self.on_field_fill:
                    self.on_field_fill(field.label, "ERROR", str(e))

        return summary

    def fill_multi_step_form(self, extractor: Any, max_steps: int = 6) -> FillSummary:
        """Fills form fields across multi-step wizard pages (e.g. LinkedIn Easy Apply)."""
        total_summary = FillSummary()
        seen_field_ids = set()

        for step in range(max_steps):
            fields = extractor.scan_form_fields()
            new_fields = [f for f in fields if f.id not in seen_field_ids]

            if new_fields:
                for f in new_fields:
                    seen_field_ids.add(f.id)
                step_summary = self.fill_all_fields(new_fields)
                total_summary.fields_filled += step_summary.fields_filled
                total_summary.fields_skipped += step_summary.fields_skipped
                total_summary.questions_added_to_qa += step_summary.questions_added_to_qa
                total_summary.details.extend(step_summary.details)

            # Look for Next or Review buttons in multi-step wizard
            next_btn = self.page.locator(
                "button[aria-label*='Continue to next step'], button:has-text('Next'), footer button:has-text('Next'), button[aria-label*='Review your application'], button:has-text('Review')"
            ).first

            # Strict Safety: Never click submit button automatically
            if next_btn.count() > 0 and next_btn.is_visible():
                btn_text = next_btn.inner_text().strip().lower()
                if "submit" in btn_text:
                    break
                try:
                    next_btn.click()
                    self.page.wait_for_load_state("domcontentloaded", timeout=4000)
                    time.sleep(1.2)
                except Exception:
                    break
            else:
                break

        return total_summary

    def _process_and_fill_field(
        self, field: ExtractedField, summary: FillSummary
    ) -> Tuple[bool, str]:
        """Resolves field value through 4-stage pipeline and applies Playwright action."""
        label_lower = field.label.lower()

        # 1. Handle File Upload (Resume / CV)
        if field.field_type == "file" or "resume" in label_lower or "cv" in label_lower:
            resume_path = self.storage.get_resume_path()
            if Path(resume_path).exists():
                loc = self.page.locator(field.selector).first
                if loc.count() > 0:
                    loc.set_input_files(resume_path)
                    console.print(f"  [green][+] Attached resume:[/green] [cyan]{Path(resume_path).name}[/cyan]")
                    return True, Path(resume_path).name
            return False, ""

        # 2. Stage 1: Direct Profile Mapping
        direct_val = self.storage.find_direct_profile_field(field.label)
        if direct_val:
            success = self._apply_input_value(field, direct_val)
            if success:
                console.print(f"  [green][+] Profile Match:[/green] {field.label} -> [cyan]{direct_val}[/cyan]")
                return True, direct_val

        # 3. Stage 2: QA Bank Semantic Match
        qa_val = self.storage.find_in_qa_bank(field.label)
        if qa_val:
            success = self._apply_input_value(field, qa_val)
            if success:
                console.print(f"  [green][+] QA Bank Match:[/green] {field.label} -> [cyan]{qa_val}[/cyan]")
                return True, qa_val

        # 4. Stage 4: Textarea / Open-Ended Essay Questions
        if field.field_type == "textarea" and len(field.label) > 15:
            return self._handle_open_ended_textarea(field)

        # 5. Stage 3: Missing Value - Interactive User Prompt & Auto-Persist
        return self._prompt_and_persist(field, summary)

    def _handle_open_ended_textarea(self, field: ExtractedField) -> Tuple[bool, str]:
        """Synthesizes open-ended essay responses and requests user approval."""
        console.print(f"\n[bold yellow][*] Open-Ended Question Encountered:[/bold yellow]")
        console.print(f"[bold cyan]\"{field.label}\"[/bold cyan]")
        console.print("[dim]Drafting tailored 3-to-4 sentence response using local model...[/dim]")

        draft = self.scorer.generate_essay_answer(
            question=field.label,
            job_title=self.job_title,
            company=self.company,
            job_description=self.job_description,
            user_profile=self.user_profile,
        )

        final_text = ""
        if self.essay_callback:
            choice, custom_text = self.essay_callback(field.label, draft)
            if choice == "accept":
                final_text = draft
            elif choice == "edit":
                final_text = custom_text or draft
            else:
                return False, ""
        else:
            console.print(f"\n[bold green]Drafted Answer:[/bold green]\n{draft}\n")
            choice = Prompt.ask(
                "Action",
                choices=["accept", "edit", "skip"],
                default="accept",
            )
            if choice == "accept":
                final_text = draft
            elif choice == "edit":
                final_text = Prompt.ask("Enter your custom answer", default=draft)
            else:
                console.print("[dim]Skipped open-ended question.[/dim]")
                return False, ""

        success = self._apply_input_value(field, final_text)
        return success, final_text

    def _prompt_and_persist(
        self, field: ExtractedField, summary: FillSummary
    ) -> Tuple[bool, str]:
        """Prompts user for unknown field value and saves it to QA Bank immediately."""
        user_val = ""
        if self.prompt_callback:
            user_val = self.prompt_callback(field)
        else:
            console.print(f"\n[bold blue][?] Question Needed for Form:[/bold blue] [white]\"{field.label}\"[/white]")
            if field.options:
                console.print(f"[dim]Available Options: {field.options}[/dim]")
            user_val = Prompt.ask(f"Enter answer for '{field.label}' (or leave blank to skip)")

        if not user_val or not user_val.strip():
            return False, ""

        # Auto-persist to qa_bank.json immediately with normalized tokens
        self.storage.add_to_qa_bank(
            question=field.label,
            answer=user_val.strip(),
            field_type=field.field_type,
            category="user_interactive",
        )
        summary.questions_added_to_qa += 1
        console.print(f"  [dim]Saved to QA bank for future applications.[/dim]")

        success = self._apply_input_value(field, user_val.strip())
        return success, user_val.strip()

    def _apply_input_value(self, field: ExtractedField, value: str) -> bool:
        """Applies the resolved string value to the DOM element via Playwright."""
        loc = self.page.locator(field.selector).first
        if loc.count() == 0:
            return False

        try:
            # Dropdown Select
            if field.field_type == "select":
                return self._select_option(loc, value, field.options)

            # Combobox / Autocomplete (e.g. LinkedIn custom dropdowns)
            elif field.field_type == "combobox":
                loc.scroll_into_view_if_needed()
                loc.click()
                time.sleep(0.2)
                loc.fill(value)
                time.sleep(0.3)
                self.page.keyboard.press("Enter")
                return True

            # Radio Group
            elif field.field_type == "radio":
                return self._select_radio(field.name, value)

            # Checkbox
            elif field.field_type == "checkbox":
                if value.lower() in ("yes", "true", "1", "agree"):
                    loc.check()
                    return True
                return False

            # Text, Email, Tel, Textarea
            else:
                loc.scroll_into_view_if_needed()
                loc.fill("")
                loc.fill(value)
                return True

        except Exception as e:
            console.print(f"  [red]Failed applying value to {field.label}: {e}[/red]")
            return False

    def _select_option(self, select_loc: Locator, target_val: str, options: List[str]) -> bool:
        """Matches and selects the best matching dropdown option."""
        target_norm = target_val.lower().strip()

        # 1. Exact or partial match in options list
        best_match = None
        for opt in options:
            if opt.lower().strip() == target_norm:
                best_match = opt
                break
            if target_norm in opt.lower() or opt.lower() in target_norm:
                best_match = opt

        if best_match:
            try:
                select_loc.select_option(label=best_match)
                return True
            except Exception:
                try:
                    select_loc.select_option(value=best_match)
                    return True
                except Exception:
                    pass

        # Fallback to direct label selection
        try:
            select_loc.select_option(label=target_val)
            return True
        except Exception:
            return False

    def _select_radio(self, group_name: str, target_val: str) -> bool:
        """Selects the matching radio button within a radio group."""
        target_norm = target_val.lower().strip()
        radios = self.page.locator(f"input[type='radio'][name='{group_name}']")

        for i in range(radios.count()):
            r = radios.nth(i)
            val = (r.get_attribute("value") or "").lower().strip()
            
            # Check value match
            if val == target_norm or target_norm in val:
                r.check()
                return True

            # Check label match
            r_id = r.get_attribute("id")
            if r_id:
                lbl = self.page.locator(f"label[for='{r_id}']").first
                if lbl.count() > 0:
                    lbl_text = lbl.inner_text().lower().strip()
                    if target_norm == lbl_text or target_norm in lbl_text or lbl_text in target_norm:
                        r.check()
                        return True

        # If yes/no and not matched, try clicking first radio if matching yes/no
        if target_norm in ("yes", "true", "1") and radios.count() > 0:
            radios.first.check()
            return True

        return False
