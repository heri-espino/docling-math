"""Native desktop GUI for docling-math. No browser or terminal is required."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .corpus_upgrade import default_obsidian_vault
from .desktop import (
    WorkerStep,
    hidden_process_kwargs,
    plan_extract,
    plan_rename,
    plan_upgrade,
    resolve_or_create_library,
    worker_command,
)


class DesktopWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Docling Math")
        self.root.geometry("1000x720")
        self.root.minsize(820, 610)
        self.root.configure(bg="#f5f6f8")

        self.corpus: Path | None = None
        self.rename_values: dict[str, str] = {}
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.cancel_requested = threading.Event()
        self.process: subprocess.Popen | None = None
        self.rename_temp_files: list[Path] = []

        self.corpus_var = tk.StringVar(value="No library selected")
        self.status_var = tk.StringVar(value="Ready")
        self.summary_var = tk.StringVar(value="Select an existing library or create a new one.")
        self.strategy_var = tk.StringVar(value="compare")
        self.device_var = tk.StringVar(value="auto")
        self.rename_auto_var = tk.BooleanVar(value=False)
        self.write_pdf_metadata_var = tk.BooleanVar(value=False)
        self.assets_var = tk.BooleanVar(value=False)
        self.obsidian_var = tk.BooleanVar(value=True)
        self.vault_var = tk.BooleanVar(value=True)
        self.allow_cpu_var = tk.BooleanVar(value=False)
        self.custom_vault_var = tk.StringVar(value="")
        self.rename_edit_var = tk.StringVar(value="")

        self._setup_theme()
        self._layout()
        self.root.after(120, self._drain_messages)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_theme(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background="#f5f6f8")
        style.configure("TLabel", background="#f5f6f8", foreground="#293241")
        style.configure("Heading.TLabel", font=("Segoe UI Semibold", 20), background="#f5f6f8")
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 12), background="#f5f6f8")
        style.configure("Hint.TLabel", foreground="#617084", background="#f5f6f8")
        style.configure("TButton", padding=(12, 8))
        style.configure("Primary.TButton", padding=(16, 10))
        style.configure("TNotebook", background="#f5f6f8")
        style.configure("TNotebook.Tab", padding=(16, 10))
        style.configure("Treeview", rowheight=29)

    def _layout(self) -> None:
        wrapper = ttk.Frame(self.root, padding=22)
        wrapper.pack(fill="both", expand=True)

        header = ttk.Frame(wrapper)
        header.pack(fill="x")
        ttk.Label(header, text="Docling Math", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, text="Local academic document extraction", style="Hint.TLabel").pack(
            side="left", padx=16, pady=(9, 0)
        )

        project_bar = ttk.Frame(wrapper)
        project_bar.pack(fill="x", pady=(20, 12))
        ttk.Label(project_bar, textvariable=self.corpus_var, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(project_bar, text="Open library", command=self._open_library).pack(side="right", padx=(8, 0))
        ttk.Button(project_bar, text="New library", command=self._new_library).pack(side="right", padx=(8, 0))

        ttk.Label(wrapper, textvariable=self.summary_var, style="Hint.TLabel").pack(anchor="w", pady=(0, 12))

        self.tabs = ttk.Notebook(wrapper)
        self.tabs.pack(fill="both", expand=True)
        self.extract_tab = ttk.Frame(self.tabs, padding=16)
        self.upgrade_tab = ttk.Frame(self.tabs, padding=16)
        self.rename_tab = ttk.Frame(self.tabs, padding=16)
        self.log_tab = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(self.extract_tab, text="Extract PDFs")
        self.tabs.add(self.upgrade_tab, text="Upgrade library")
        self.tabs.add(self.rename_tab, text="Rename papers")
        self.tabs.add(self.log_tab, text="Activity")

        self._extract_layout()
        self._upgrade_layout()
        self._rename_layout()
        self._log_layout()

        footer = ttk.Frame(wrapper)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=160)
        self.progress.pack(side="right", padx=(10, 0))
        self.cancel_button = ttk.Button(footer, text="Cancel job", command=self._cancel_job, state="disabled")
        self.cancel_button.pack(side="right", padx=10)

    def _extract_layout(self) -> None:
        frame = self.extract_tab
        ttk.Label(frame, text="Extract academic PDFs", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Choose a library, add PDF files, and run the extraction with your local CPU/GPU.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        ttk.Button(controls, text="Add PDF files…", command=self._add_pdfs).pack(side="left")
        ttk.Button(controls, text="Open PDF folder", command=self._open_pdf_folder).pack(side="left", padx=8)
        self.pdf_list = tk.Listbox(
            frame,
            height=8,
            relief="solid",
            bd=1,
            selectmode="extended",
            font=("Segoe UI", 10),
            bg="white",
            fg="#293241",
            highlightthickness=0,
        )
        self.pdf_list.pack(fill="both", expand=True, pady=(12, 12))

        settings = ttk.Frame(frame)
        settings.pack(fill="x")
        ttk.Label(settings, text="Strategy").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Combobox(
            settings, textvariable=self.strategy_var,
            values=("compare", "smart", "hybrid", "ocr"), width=13, state="readonly"
        ).grid(row=0, column=1, sticky="w", padx=(8, 25))
        ttk.Label(settings, text="Device").grid(row=0, column=2, sticky="w", pady=5)
        ttk.Combobox(
            settings, textvariable=self.device_var,
            values=("auto", "cuda", "mps", "cpu"), width=11, state="readonly"
        ).grid(row=0, column=3, sticky="w", padx=8)

        ttk.Checkbutton(settings, text="Auto-rename PDFs", variable=self.rename_auto_var).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Checkbutton(settings, text="Write metadata inside PDFs", variable=self.write_pdf_metadata_var).grid(
            row=1, column=2, columnspan=2, sticky="w", pady=4
        )
        ttk.Checkbutton(settings, text="Save figure/table assets", variable=self.assets_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Checkbutton(settings, text="Allow slower CPU fallback", variable=self.allow_cpu_var).grid(
            row=2, column=2, columnspan=2, sticky="w", pady=4
        )
        ttk.Label(
            frame,
            text="After extraction, a default Obsidian vault is created and references are synchronized.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(12, 7))
        self.extract_button = ttk.Button(
            frame, text="Extract PDFs", style="Primary.TButton", command=self._extract
        )
        self.extract_button.pack(anchor="e")

    def _upgrade_layout(self) -> None:
        frame = self.upgrade_tab
        ttk.Label(frame, text="Upgrade an existing library", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Rebuild metadata, tags, reference notes, INDEX and bundle without running OCR.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(4, 20))
        ttk.Checkbutton(frame, text="Obsidian properties and related papers", variable=self.obsidian_var).pack(
            anchor="w", pady=6
        )
        ttk.Checkbutton(frame, text="Create/update local Obsidian vault", variable=self.vault_var).pack(
            anchor="w", pady=6
        )
        ttk.Label(frame, text="Custom vault path (optional)", style="Section.TLabel").pack(
            anchor="w", pady=(18, 5)
        )
        vault_row = ttk.Frame(frame)
        vault_row.pack(fill="x")
        ttk.Entry(vault_row, textvariable=self.custom_vault_var).pack(side="left", fill="x", expand=True)
        ttk.Button(vault_row, text="Browse…", command=self._pick_vault).pack(side="left", padx=(8, 0))
        ttk.Label(
            frame,
            text="Default: a separate obsidian-vault folder beside bib/. Source PDFs stay untouched.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(10, 0))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=24)
        self.upgrade_button = ttk.Button(
            actions, text="Upgrade library", style="Primary.TButton", command=self._upgrade
        )
        self.upgrade_button.pack(side="right")
        ttk.Button(actions, text="Open vault", command=self._open_vault_folder).pack(side="right", padx=10)

    def _rename_layout(self) -> None:
        frame = self.rename_tab
        ttk.Label(frame, text="Rename literature", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Select a PDF, enter a new filename, preview changes, then apply.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        table_box = ttk.Frame(frame)
        table_box.pack(fill="both", expand=True)
        self.rename_tree = ttk.Treeview(
            table_box, columns=("current", "new"), show="headings", selectmode="browse"
        )
        self.rename_tree.heading("current", text="Current PDF filename")
        self.rename_tree.heading("new", text="New PDF filename")
        self.rename_tree.column("current", width=350)
        self.rename_tree.column("new", width=350)
        scrollbar = ttk.Scrollbar(table_box, orient="vertical", command=self.rename_tree.yview)
        self.rename_tree.configure(yscrollcommand=scrollbar.set)
        self.rename_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.rename_tree.bind("<<TreeviewSelect>>", self._on_rename_selected)

        edit = ttk.Frame(frame)
        edit.pack(fill="x", pady=(12, 5))
        ttk.Entry(edit, textvariable=self.rename_edit_var).pack(side="left", fill="x", expand=True)
        ttk.Button(edit, text="Set new name", command=self._set_rename).pack(side="left", padx=(8, 0))
        ttk.Button(edit, text="Load JSON…", command=self._load_rename_json).pack(side="left", padx=(8, 0))

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(12, 0))
        self.preview_button = ttk.Button(actions, text="Preview changes", command=self._preview_rename)
        self.preview_button.pack(side="right", padx=(8, 0))
        self.rename_button = ttk.Button(
            actions, text="Apply renames", style="Primary.TButton", command=self._apply_rename
        )
        self.rename_button.pack(side="right")

    def _log_layout(self) -> None:
        self.log_text = tk.Text(
            self.log_tab, wrap="word", bg="#121923", fg="#e2e8f0",
            insertbackground="#e2e8f0", font=("Consolas", 10),
            relief="flat", padx=14, pady=14, state="disabled"
        )
        scrollbar = ttk.Scrollbar(self.log_tab, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _set_corpus(self, bib: Path) -> None:
        self.corpus = bib
        self.corpus_var.set(str(bib))
        self._refresh_library()

    def _refresh_library(self) -> None:
        if self.corpus is None:
            return
        pdfs = sorted((self.corpus / "pdf").glob("*.pdf"), key=lambda p: p.name.casefold())
        md_count = len(list((self.corpus / "extracted").glob("*.md")))
        refs_count = len(list((self.corpus / "references").glob("*.references.md")))
        self.summary_var.set(
            f"{len(pdfs)} PDFs  ·  {md_count} Markdown  ·  {refs_count} reference notes"
        )
        self.pdf_list.delete(0, tk.END)
        self.rename_tree.delete(*self.rename_tree.get_children())
        old = dict(self.rename_values)
        self.rename_values = {}
        for pdf in pdfs:
            self.pdf_list.insert(tk.END, pdf.name)
            new = old.get(pdf.name, pdf.name)
            self.rename_values[pdf.name] = new
            self.rename_tree.insert("", "end", iid=pdf.name, values=(pdf.name, new))

    def _open_library(self) -> None:
        folder = filedialog.askdirectory(title="Choose existing docling-math library")
        if not folder:
            return
        try:
            self._set_corpus(resolve_or_create_library(folder))
        except Exception as exc:
            messagebox.showerror("Invalid library", str(exc), parent=self.root)

    def _new_library(self) -> None:
        folder = filedialog.askdirectory(title="Choose the new library's parent folder")
        if not folder:
            return
        try:
            self._set_corpus(resolve_or_create_library(folder, create=True))
        except Exception as exc:
            messagebox.showerror("Could not create library", str(exc), parent=self.root)

    def _require_corpus(self) -> Path | None:
        if self.corpus is None:
            messagebox.showinfo("Select a library", "Open or create a library first.", parent=self.root)
        return self.corpus

    def _open_folder(self, folder: Path) -> None:
        if not folder.is_dir():
            messagebox.showinfo("Folder not found", str(folder), parent=self.root)
            return
        try:
            import sys
            if sys.platform == "win32":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror("Could not open folder", str(exc), parent=self.root)

    def _open_pdf_folder(self) -> None:
        if (bib := self._require_corpus()) is not None:
            self._open_folder(bib / "pdf")

    def _open_vault_folder(self) -> None:
        if (bib := self._require_corpus()) is not None:
            custom = self.custom_vault_var.get().strip()
            self._open_folder(Path(custom) if custom else default_obsidian_vault(bib))

    def _add_pdfs(self) -> None:
        if self.busy:
            return
        bib = self._require_corpus()
        if bib is None:
            return
        chosen = filedialog.askopenfilenames(
            title="Choose PDF papers", filetypes=[("PDF documents", "*.pdf")]
        )
        if not chosen:
            return

        added = 0
        skipped = 0
        for filename in chosen:
            source = Path(filename)
            destination = bib / "pdf" / source.name
            try:
                if source.resolve() == destination.resolve():
                    skipped += 1
                    continue
                if destination.exists():
                    index = 2
                    while destination.exists():
                        destination = bib / "pdf" / f"{source.stem}_{index}.pdf"
                        index += 1
                shutil.copy2(source, destination)
                added += 1
            except Exception as exc:
                messagebox.showerror("Could not add PDF", f"{source.name}: {exc}", parent=self.root)
        self._refresh_library()
        self.status_var.set(f"Added {added} PDF(s), skipped {skipped}")

    def _pick_vault(self) -> None:
        path = filedialog.askdirectory(title="Choose Obsidian vault folder")
        if path:
            self.custom_vault_var.set(path)
            self.vault_var.set(True)

    def _extract(self) -> None:
        bib = self._require_corpus()
        if bib is None or self.busy:
            return
        if not list((bib / "pdf").glob("*.pdf")):
            messagebox.showwarning("No PDFs", "Add PDF files before extracting.", parent=self.root)
            return
        if self.device_var.get() == "cpu" and not self.allow_cpu_var.get():
            messagebox.showwarning(
                "CPU confirmation", "Check 'Allow slower CPU fallback' to use CPU.",
                parent=self.root
            )
            return
        try:
            steps = plan_extract(
                bib,
                strategy=self.strategy_var.get(),
                device=self.device_var.get(),
                rename_pdfs=self.rename_auto_var.get(),
                write_pdf_metadata=self.write_pdf_metadata_var.get(),
                assets=self.assets_var.get(),
                create_vault=True,
                obsidian=True,
            )
        except Exception as exc:
            messagebox.showerror("Invalid extraction settings", str(exc), parent=self.root)
            return
        self._start_job(steps)

    def _upgrade(self) -> None:
        bib = self._require_corpus()
        if bib is None or self.busy:
            return
        custom = self.custom_vault_var.get().strip() or None
        create_vault = self.vault_var.get() or custom is not None
        try:
            step = plan_upgrade(
                bib, create_vault=create_vault, obsidian=self.obsidian_var.get(),
                vault_path=custom
            )
        except Exception as exc:
            messagebox.showerror("Upgrade settings", str(exc), parent=self.root)
            return
        self._start_job((step,))

    def _on_rename_selected(self, _event=None) -> None:
        selected = self.rename_tree.selection()
        if selected:
            self.rename_edit_var.set(self.rename_values.get(selected[0], selected[0]))

    def _set_rename(self) -> None:
        selected = self.rename_tree.selection()
        if not selected:
            messagebox.showinfo("Select a paper", "Select a row first.", parent=self.root)
            return
        current = selected[0]
        new = self.rename_edit_var.get().strip()
        if not new:
            return
        if not new.casefold().endswith(".pdf"):
            new += ".pdf"
        self.rename_values[current] = new
        self.rename_tree.item(current, values=(current, new))

    def _load_rename_json(self) -> None:
        if self._require_corpus() is None:
            return
        filename = filedialog.askopenfilename(
            title="Select rename dictionary", filetypes=[("JSON files", "*.json")]
        )
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in data.items()
            ):
                raise ValueError("Expected a JSON dictionary of filename strings.")
            for current, new in data.items():
                if current not in self.rename_values:
                    raise ValueError(f"PDF not found in selected library: {current}")
                self.rename_values[current] = new
                self.rename_tree.item(current, values=(current, new))
        except Exception as exc:
            messagebox.showerror("Invalid rename mapping", str(exc), parent=self.root)

    def _planned_mapping(self) -> dict[str, str]:
        return {
            old: new
            for old, new in self.rename_values.items()
            if old != new
        }

    def _rename_job(self, *, dry_run: bool) -> None:
        bib = self._require_corpus()
        if bib is None or self.busy:
            return
        mapping = self._planned_mapping()
        if not mapping:
            messagebox.showinfo("No changes", "Enter at least one new filename.", parent=self.root)
            return
        if not dry_run:
            if not messagebox.askyesno(
                "Confirm renames",
                f"Apply {len(mapping)} filename changes and update the Markdown references?",
                parent=self.root,
            ):
                return
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", prefix="docling-rename-",
                delete=False
            ) as handle:
                json.dump(mapping, handle, ensure_ascii=False, indent=2)
                mapping_file = Path(handle.name)
            self.rename_temp_files.append(mapping_file)
            step = plan_rename(bib, mapping_file, dry_run=dry_run)
        except Exception as exc:
            messagebox.showerror("Rename error", str(exc), parent=self.root)
            return
        self._start_job((step,))

    def _preview_rename(self) -> None:
        self._rename_job(dry_run=True)

    def _apply_rename(self) -> None:
        self._rename_job(dry_run=False)

    def _write_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _start_job(self, steps: tuple[WorkerStep, ...]) -> None:
        if self.busy:
            return
        self.busy = True
        self.cancel_requested.clear()
        self.status_var.set("Running: " + steps[0].label)
        self.progress.start(12)
        self.cancel_button.configure(state="normal")
        for button in (
            self.extract_button, self.upgrade_button, self.rename_button, self.preview_button
        ):
            button.configure(state="disabled")
        self.tabs.select(self.log_tab)
        self._write_log(f"\n=== {steps[0].label} ===\n")

        worker = threading.Thread(
            target=self._run_steps,
            args=(steps, self.allow_cpu_var.get()),
            daemon=True,
        )
        worker.start()

    def _run_steps(self, steps: tuple[WorkerStep, ...], allow_cpu: bool) -> None:
        success = True
        try:
            for step in steps:
                if self.cancel_requested.is_set():
                    success = False
                    break
                self.messages.put(("label", step.label))
                command = worker_command(step)
                kwargs = hidden_process_kwargs(allow_cpu=allow_cpu and step.kind == "extract")
                self.process = subprocess.Popen(command, **kwargs)

                # User explicitly enabled CPU fallback in the GUI. Feed one confirmation
                # only to extraction worker; never silently opt in otherwise.
                if allow_cpu and step.kind == "extract" and self.process.stdin:
                    self.process.stdin.write("y\n")
                    self.process.stdin.flush()

                if self.process.stdout is not None:
                    for line in self.process.stdout:
                        self.messages.put(("log", line))

                code = self.process.wait()
                self.process = None
                if code != 0:
                    self.messages.put(("log", f"\n[FAILED] {step.label}: exit code {code}\n"))
                    success = False
                    break
                self.messages.put(("log", f"\n[OK] {step.label}\n"))
        except Exception as exc:
            success = False
            self.messages.put(("log", f"\n[ERROR] {type(exc).__name__}: {exc}\n"))
        finally:
            self.process = None
            self.messages.put(("done", success and not self.cancel_requested.is_set()))

    def _cancel_job(self) -> None:
        if not self.busy:
            return
        self.cancel_requested.set()
        self.status_var.set("Cancelling job…")
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _drain_messages(self) -> None:
        try:
            while True:
                action, value = self.messages.get_nowait()
                if action == "log":
                    self._write_log(str(value))
                elif action == "label":
                    self.status_var.set(str(value))
                elif action == "done":
                    self._finish_job(bool(value))
        except queue.Empty:
            pass
        self.root.after(120, self._drain_messages)

    def _finish_job(self, success: bool) -> None:
        self.busy = False
        self.progress.stop()
        self.cancel_button.configure(state="disabled")
        for button in (
            self.extract_button, self.upgrade_button, self.rename_button, self.preview_button
        ):
            button.configure(state="normal")
        self.status_var.set("Completed" if success else "Cancelled or failed — see Activity")
        for path in self.rename_temp_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self.rename_temp_files.clear()
        self._refresh_library()
        if success:
            messagebox.showinfo("Docling Math", "Operation completed. See Activity for details.", parent=self.root)

    def _on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno(
                "Job running", "Cancel the active job and close?", parent=self.root
            ):
                return
            self._cancel_job()
        self.root.destroy()


def launch() -> int:
    root = tk.Tk()
    DesktopWindow(root)
    root.mainloop()
    return 0
