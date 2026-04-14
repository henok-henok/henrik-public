"""E-ARK SIP Creator — Desktop GUI application.

customtkinter interface for creating E-ARK SIP packages.
Entry point for both development and PyInstaller builds.
"""

import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from eark_core import collect_files
from mets_builder import (
    Agent,
    AltRecordID,
    MetsHeader,
    build_mets,
)
from package_assembler import create_package

def _exe_dir() -> Path:
    """Return the directory containing the running .exe, or the script dir."""
    import sys
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

LOG_FILE = _exe_dir() / "eark_sip_creator.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _setup_file_logging() -> None:
    """Add file handler to root logger. Truncates on each run."""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.FileHandler) and h.name == "eark_file":
            return
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.name = "eark_file"
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(fh)
    root.setLevel(logging.DEBUG)
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.FileHandler
        ):
            h.setLevel(logging.INFO)


# ── Reusable file selector widget ──


class FileSelectorGroup(ctk.CTkFrame):
    """A file/folder selector group with add/remove buttons and a list."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        label: str,
        show_subdirectory_checkbox: bool = False,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self.paths: list[Path] = []
        self.subdirectories = ctk.BooleanVar(value=False)

        # Header row
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=5, pady=(5, 2))

        ctk.CTkLabel(header, text=label, font=("", 13, "bold")).pack(
            side="left"
        )

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")

        ctk.CTkButton(
            btn_frame,
            text="Add File",
            width=80,
            command=self._add_file,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            btn_frame,
            text="Add Folder",
            width=80,
            command=self._add_folder,
        ).pack(side="left", padx=2)

        if show_subdirectory_checkbox:
            ctk.CTkCheckBox(
                header,
                text="Include subdirectories",
                variable=self.subdirectories,
            ).pack(side="right", padx=(0, 10))

        # List display
        self.listbox = tk.Listbox(self, height=4, selectmode=tk.EXTENDED)
        self.listbox.pack(fill="x", padx=5, pady=2)

        ctk.CTkButton(
            self,
            text="Remove Selected",
            width=120,
            fg_color="#c0392b",
            hover_color="#e74c3c",
            command=self._remove_selected,
        ).pack(padx=5, pady=(2, 5))

    def _add_file(self) -> None:
        files = filedialog.askopenfilenames(title="Select files")
        for f in files:
            p = Path(f)
            if p not in self.paths:
                self.paths.append(p)
                self.listbox.insert(tk.END, str(p))

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder")
        if folder:
            p = Path(folder)
            if p not in self.paths:
                self.paths.append(p)
                self.listbox.insert(tk.END, str(p))

    def _remove_selected(self) -> None:
        selected = list(self.listbox.curselection())
        for idx in reversed(selected):
            self.listbox.delete(idx)
            del self.paths[idx]

    def get_paths(self) -> list[Path]:
        """Return list of selected paths."""
        return list(self.paths)

    def use_subdirectories(self) -> bool:
        """Return whether subdirectories should be traversed."""
        return self.subdirectories.get()


# ── Main application ──


class EarkSipCreatorApp(ctk.CTk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("E-ARK SIP Creator")
        self.geometry("750x900")
        self.minsize(700, 800)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        # Scrollable main frame
        self.main_frame = ctk.CTkScrollableFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_header_section()
        self._build_agents_section()
        self._build_alt_record_ids_section()
        self._build_file_selectors_section()
        self._build_output_section()
        self._build_generate_section()

    # ── Header section ──

    def _build_header_section(self) -> None:
        section = ctk.CTkFrame(self.main_frame)
        section.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(section, text="METS Header", font=("", 15, "bold")).pack(
            anchor="w", padx=10, pady=(10, 5)
        )

        grid = ctk.CTkFrame(section, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=5)

        # LABEL
        ctk.CTkLabel(grid, text="LABEL:").grid(
            row=0, column=0, sticky="w", pady=3
        )
        self.label_entry = ctk.CTkEntry(grid, width=500)
        self.label_entry.grid(row=0, column=1, columnspan=2, sticky="w", pady=3)

        # TYPE
        ctk.CTkLabel(grid, text="TYPE:").grid(
            row=1, column=0, sticky="w", pady=3
        )
        self.type_var = ctk.StringVar(value="Datasets")
        type_options = [
            "Datasets",
            "Geospatial Data",
            "Databases",
            "Websites",
            "Collection",
            "Mixed",
            "Other",
        ]
        self.type_dropdown = ctk.CTkComboBox(
            grid,
            values=type_options,
            variable=self.type_var,
            width=200,
            state="readonly",
            command=self._on_type_change,
        )
        self.type_dropdown.grid(row=1, column=1, sticky="w", pady=3)

        self.other_type_entry = ctk.CTkEntry(
            grid, width=290, placeholder_text="Specify other type..."
        )
        self.other_type_entry.grid(row=1, column=2, sticky="w", padx=(5, 0), pady=3)
        self.other_type_entry.configure(state="disabled")

        # CONTENTINFORMATIONTYPE
        ctk.CTkLabel(grid, text="CONTENTINFORMATIONTYPE:").grid(
            row=2, column=0, sticky="w", pady=3
        )
        self.cit_var = ctk.StringVar(value="citserms_v2_1")
        cit_options = [
            "citserms_v2_1",
            "ERMS",
            "SIARD1",
            "SIARD2",
            "GeoData",
            "citssiard_v1_0",
            "MIXED",
            "OTHER",
        ]
        self.cit_dropdown = ctk.CTkComboBox(
            grid,
            values=cit_options,
            variable=self.cit_var,
            width=200,
            state="readonly",
            command=self._on_cit_change,
        )
        self.cit_dropdown.grid(row=2, column=1, sticky="w", pady=3)

        self.other_cit_entry = ctk.CTkEntry(
            grid, width=290, placeholder_text="Specify other CIT..."
        )
        self.other_cit_entry.grid(row=2, column=2, sticky="w", padx=(5, 0), pady=3)
        self.other_cit_entry.configure(state="disabled")

        # RECORDSTATUS
        ctk.CTkLabel(grid, text="RECORDSTATUS:").grid(
            row=3, column=0, sticky="w", pady=3
        )
        self.recordstatus_var = ctk.StringVar(value="NEW")
        ctk.CTkComboBox(
            grid,
            values=["NEW", "SUPPLEMENT", "REPLACEMENT", "TEST", "VERSION"],
            variable=self.recordstatus_var,
            width=200,
            state="readonly",
        ).grid(row=3, column=1, sticky="w", pady=3)

    def _on_type_change(self, value: str) -> None:
        if value == "Other":
            self.other_type_entry.configure(state="normal")
        else:
            self.other_type_entry.delete(0, "end")
            self.other_type_entry.configure(state="disabled")

    def _on_cit_change(self, value: str) -> None:
        if value == "OTHER":
            self.other_cit_entry.configure(state="normal")
        else:
            self.other_cit_entry.delete(0, "end")
            self.other_cit_entry.configure(state="disabled")

    # ── Agents section ──

    def _build_agents_section(self) -> None:
        section = ctk.CTkFrame(self.main_frame)
        section.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(section, text="Agents", font=("", 15, "bold")).pack(
            anchor="w", padx=10, pady=(10, 5)
        )

        grid = ctk.CTkFrame(section, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=5)

        id_types = ["ORG", "DUNS", "VAT", "HSA", "Local", "URI"]

        # ARCHIVIST
        ctk.CTkLabel(grid, text="ARCHIVIST", font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(5, 2)
        )
        ctk.CTkLabel(grid, text="Name:").grid(row=1, column=0, sticky="w")
        self.archivist_name = ctk.CTkEntry(grid, width=250)
        self.archivist_name.grid(row=1, column=1, sticky="w", padx=5)

        ctk.CTkLabel(grid, text="ID type:").grid(row=1, column=2, sticky="w")
        self.archivist_id_type = ctk.CTkComboBox(
            grid, values=id_types, width=100
        )
        self.archivist_id_type.grid(row=1, column=3, sticky="w", padx=5)

        ctk.CTkLabel(grid, text="ID value:").grid(row=2, column=0, sticky="w")
        self.archivist_id_value = ctk.CTkEntry(grid, width=250)
        self.archivist_id_value.grid(row=2, column=1, sticky="w", padx=5)

        # CREATOR
        ctk.CTkLabel(grid, text="CREATOR", font=("", 12, "bold")).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(10, 2)
        )
        ctk.CTkLabel(grid, text="Name:").grid(row=4, column=0, sticky="w")
        self.creator_name = ctk.CTkEntry(grid, width=250)
        self.creator_name.grid(row=4, column=1, sticky="w", padx=5)

        ctk.CTkLabel(grid, text="ID type:").grid(row=4, column=2, sticky="w")
        self.creator_id_type = ctk.CTkComboBox(
            grid, values=id_types, width=100
        )
        self.creator_id_type.grid(row=4, column=3, sticky="w", padx=5)

        ctk.CTkLabel(grid, text="ID value:").grid(row=5, column=0, sticky="w")
        self.creator_id_value = ctk.CTkEntry(grid, width=250)
        self.creator_id_value.grid(row=5, column=1, sticky="w", padx=5)

        # SYSTEM (software)
        ctk.CTkLabel(grid, text="SYSTEM (Software)", font=("", 12, "bold")).grid(
            row=6, column=0, columnspan=4, sticky="w", pady=(10, 2)
        )
        ctk.CTkLabel(grid, text="Software name:").grid(
            row=7, column=0, sticky="w"
        )
        self.system_name = ctk.CTkEntry(grid, width=250)
        self.system_name.grid(row=7, column=1, sticky="w", padx=5)

        ctk.CTkLabel(grid, text="Version:").grid(row=7, column=2, sticky="w")
        self.system_version = ctk.CTkEntry(grid, width=100)
        self.system_version.grid(row=7, column=3, sticky="w", padx=5)

    # ── AltRecordIDs section ──

    def _build_alt_record_ids_section(self) -> None:
        section = ctk.CTkFrame(self.main_frame)
        section.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(
            section, text="Alt Record IDs", font=("", 15, "bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        grid = ctk.CTkFrame(section, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(grid, text="SUBMISSIONAGREEMENT *:").grid(
            row=0, column=0, sticky="w", pady=3
        )
        self.submission_agreement = ctk.CTkEntry(grid, width=400)
        self.submission_agreement.grid(row=0, column=1, sticky="w", pady=3)

        ctk.CTkLabel(grid, text="PREVIOUSSUBMISSIONAGREEMENT:").grid(
            row=1, column=0, sticky="w", pady=3
        )
        self.prev_submission_agreement = ctk.CTkEntry(grid, width=400)
        self.prev_submission_agreement.grid(row=1, column=1, sticky="w", pady=3)

        ctk.CTkLabel(grid, text="REFERENCECODE:").grid(
            row=2, column=0, sticky="w", pady=3
        )
        self.reference_code = ctk.CTkEntry(grid, width=400)
        self.reference_code.grid(row=2, column=1, sticky="w", pady=3)

        ctk.CTkLabel(grid, text="PREVIOUSREFERENCECODE:").grid(
            row=3, column=0, sticky="w", pady=3
        )
        self.prev_reference_code = ctk.CTkEntry(grid, width=400)
        self.prev_reference_code.grid(row=3, column=1, sticky="w", pady=3)

    # ── File selectors section ──

    def _build_file_selectors_section(self) -> None:
        section = ctk.CTkFrame(self.main_frame)
        section.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(
            section, text="File Selection", font=("", 15, "bold")
        ).pack(anchor="w", padx=10, pady=(10, 5))

        self.file_selectors: dict[str, FileSelectorGroup] = {}

        categories = [
            ("schema", "Schemas", False),
            ("representation", "Representations", True),
            ("representationmetadata", "Representation Metadata", False),
            ("descriptivemetadata", "Descriptive Metadata", False),
            ("preservationmetadata", "Preservation Metadata", False),
            ("documentation", "Documentation", False),
        ]

        for key, label, has_subdir in categories:
            selector = FileSelectorGroup(
                section,
                label=label,
                show_subdirectory_checkbox=has_subdir,
            )
            selector.pack(fill="x", padx=5, pady=2)
            self.file_selectors[key] = selector

    # ── Output section ──

    def _build_output_section(self) -> None:
        section = ctk.CTkFrame(self.main_frame)
        section.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(section, text="Output", font=("", 15, "bold")).pack(
            anchor="w", padx=10, pady=(10, 5)
        )

        row = ctk.CTkFrame(section, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(row, text="Output folder:").pack(side="left")
        self.output_path_var = ctk.StringVar()
        self.output_entry = ctk.CTkEntry(
            row, textvariable=self.output_path_var, width=400
        )
        self.output_entry.pack(side="left", padx=5)

        ctk.CTkButton(
            row, text="Browse", width=80, command=self._browse_output
        ).pack(side="left")

        self.zip_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            section, text="Create ZIP archive", variable=self.zip_var
        ).pack(anchor="w", padx=10, pady=(0, 10))

    def _browse_output(self) -> None:
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_path_var.set(folder)

    # ── Generate section ──

    def _build_generate_section(self) -> None:
        section = ctk.CTkFrame(self.main_frame)
        section.pack(fill="x", padx=5, pady=5)

        self.generate_btn = ctk.CTkButton(
            section,
            text="Generate SIP Package",
            font=("", 14, "bold"),
            height=40,
            command=self._on_generate,
        )
        self.generate_btn.pack(padx=10, pady=10)

        self.progress_bar = ctk.CTkProgressBar(section, width=600)
        self.progress_bar.pack(padx=10, pady=(0, 5))
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(section, text="")
        self.status_label.pack(padx=10, pady=(0, 10))

    # ── Validation ──

    def _validate(self) -> bool:
        """Validate form before generation. Returns True if valid."""
        errors = []

        if self.type_var.get() == "Other" and not self.other_type_entry.get().strip():
            errors.append("TYPE is 'Other' but no custom type specified.")

        if self.cit_var.get() == "OTHER" and not self.other_cit_entry.get().strip():
            errors.append(
                "CONTENTINFORMATIONTYPE is 'OTHER' but no custom value specified."
            )

        if not self.submission_agreement.get().strip():
            errors.append("SUBMISSIONAGREEMENT is required.")

        output_path = self.output_path_var.get().strip()
        if not output_path:
            errors.append("No output folder selected.")
        elif not Path(output_path).is_dir():
            errors.append("Output folder does not exist.")

        if errors:
            messagebox.showerror(
                "Validation Error", "\n".join(errors)
            )
            return False

        return True

    # ── Build header from GUI ──

    def _build_header(self) -> MetsHeader:
        """Construct a MetsHeader from current GUI values."""
        agents = []

        # Archivist agent
        arch_name = self.archivist_name.get().strip()
        if arch_name:
            arch_id_type = self.archivist_id_type.get()
            arch_id_value = self.archivist_id_value.get().strip()
            note = (
                f"{arch_id_type}:{arch_id_value}"
                if arch_id_value
                else None
            )
            agents.append(
                Agent(
                    role="ARCHIVIST",
                    type="ORGANIZATION",
                    name=arch_name,
                    note=note,
                    notetype="IDENTIFICATIONCODE" if note else None,
                )
            )

        # Creator agent
        creator_name = self.creator_name.get().strip()
        if creator_name:
            cr_id_type = self.creator_id_type.get()
            cr_id_value = self.creator_id_value.get().strip()
            note = (
                f"{cr_id_type}:{cr_id_value}"
                if cr_id_value
                else None
            )
            agents.append(
                Agent(
                    role="CREATOR",
                    type="ORGANIZATION",
                    name=creator_name,
                    note=note,
                    notetype="IDENTIFICATIONCODE" if note else None,
                )
            )

        # System agent
        sys_name = self.system_name.get().strip()
        if sys_name:
            sys_version = self.system_version.get().strip()
            agents.append(
                Agent(
                    role="OTHER",
                    type="OTHER",
                    othertype="SOFTWARE",
                    otherrole="PRODUCER",
                    name=sys_name,
                    note=sys_version or None,
                    notetype="SOFTWARE VERSION" if sys_version else None,
                )
            )

        # Alt record IDs
        alt_records = [
            AltRecordID("SUBMISSIONAGREEMENT", self.submission_agreement.get().strip()),
            AltRecordID(
                "PREVIOUSSUBMISSIONAGREEMENT",
                self.prev_submission_agreement.get().strip(),
            ),
            AltRecordID("REFERENCECODE", self.reference_code.get().strip()),
            AltRecordID(
                "PREVIOUSREFERENCECODE",
                self.prev_reference_code.get().strip(),
            ),
        ]

        return MetsHeader(
            label=self.label_entry.get().strip(),
            type=self.type_var.get(),
            other_type=self.other_type_entry.get().strip(),
            contentinformationtype=self.cit_var.get(),
            other_contentinformationtype=self.other_cit_entry.get().strip(),
            recordstatus=self.recordstatus_var.get(),
            agents=agents,
            alt_record_ids=alt_records,
        )

    # ── Collect file paths from selectors (main thread only) ──

    def _snapshot_file_paths(self) -> dict[str, tuple[list[Path], bool]]:
        """Snapshot file selector state on the main thread.

        Returns dict mapping category key to (paths, use_subdirs).
        """
        result = {}
        for key, selector in self.file_selectors.items():
            paths = selector.get_paths()
            if paths:
                result[key] = (paths, selector.use_subdirectories())
        return result

    # ── Generation ──

    def _on_generate(self) -> None:
        """Handle Generate button click.

        Snapshots all GUI state on the main thread, then hands
        plain Python objects to the background worker.
        """
        if not self._validate():
            return

        # Snapshot all GUI state on main thread (tkinter is not thread-safe)
        header = self._build_header()
        file_path_snapshot = self._snapshot_file_paths()
        output_dir = Path(self.output_path_var.get().strip())
        zip_output = self.zip_var.get()

        self.generate_btn.configure(state="disabled")
        self.status_label.configure(text="Collecting files...")
        self.progress_bar.set(0)

        thread = threading.Thread(
            target=self._generate_worker,
            args=(header, file_path_snapshot, output_dir, zip_output),
            daemon=True,
        )
        thread.start()

    def _generate_worker(
        self,
        header: MetsHeader,
        file_path_snapshot: dict[str, tuple[list[Path], bool]],
        output_dir: Path,
        zip_output: bool,
    ) -> None:
        """Run package generation in a background thread.

        All GUI state is passed as arguments — this method never
        reads widget state directly.
        """
        try:
            # Collect files (file I/O — safe in background thread)
            file_categories: dict[str, dict] = {}
            collect_warnings: list[str] = []
            for key, (paths, use_subdirs) in file_path_snapshot.items():
                files = collect_files(
                    paths,
                    key,
                    subdirectories=use_subdirs,
                    warnings=collect_warnings,
                )
                if files:
                    file_categories[key] = files

            self.after(0, lambda: self.status_label.configure(
                text="Building METS XML..."
            ))

            # Build METS
            mets_tree = build_mets(header, file_categories)

            self.after(0, lambda: self.status_label.configure(
                text="Assembling package..."
            ))

            # Create package
            def progress_cb(current: int, total: int) -> None:
                if total > 0:
                    self.after(
                        0,
                        lambda c=current, t=total: self.progress_bar.set(c / t),
                    )

            result_path = create_package(
                output_dir,
                mets_tree,
                file_categories,
                zip_output=zip_output,
                progress_callback=progress_cb,
            )

            self.after(
                0,
                lambda: self._on_generation_complete(
                    result_path, collect_warnings
                ),
            )

        except Exception as e:
            logger.exception("Generation failed")
            self.after(
                0,
                lambda: self._on_generation_error(str(e)),
            )

    def _on_generation_complete(
        self, result_path: Path, warnings: list[str] | None = None
    ) -> None:
        """Called on main thread when generation succeeds."""
        self.progress_bar.set(1)
        warnings = warnings or []
        if warnings:
            self.status_label.configure(
                text=(
                    f"Package created with {len(warnings)} warning(s): "
                    f"{result_path}"
                )
            )
        else:
            self.status_label.configure(
                text=f"Package created: {result_path}"
            )
        self.generate_btn.configure(state="normal")

        message = f"E-ARK SIP package created:\n{result_path}"
        if warnings:
            joined = "\n".join(f"  - {w}" for w in warnings)
            message += (
                f"\n\nSkipped {len(warnings)} entry/entries:\n{joined}"
            )
            messagebox.showwarning("Success (with warnings)", message)
        else:
            messagebox.showinfo("Success", message)

    def _on_generation_error(self, error_msg: str) -> None:
        """Called on main thread when generation fails."""
        self.status_label.configure(text=f"Error: {error_msg}")
        self.generate_btn.configure(state="normal")
        messagebox.showerror("Error", f"Generation failed:\n{error_msg}")


def main() -> None:
    """Application entry point."""
    _setup_file_logging()
    app = EarkSipCreatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
