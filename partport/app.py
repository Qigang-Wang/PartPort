"""wxPython user interface for PartPort."""

from __future__ import annotations

import html
import threading
import webbrowser
from pathlib import Path

import wx
import wx.html2

from .catalog import CatalogClient, CatalogError, PartRecord, SearchResult
from .global_import import GlobalLibraryImporter
from .i18n import translate
from .jlc2_runner import JLC2Runner
from .kicad_context import discover_project_context, find_project_file
from .library_catalog import LibraryEntry, load_global_library_catalog
from .library_tables import LibraryTableError, register_project_libraries
from .models import ResultStatus, RunnerOptions
from .preview import build_preview_html, extract_svg_documents, sanitize_svg
from .settings import PartPortSettings, load_settings, save_settings
from .validation import OutputSnapshot, validate_import


class PartPortFrame(wx.Frame):
    def __init__(self, parent: wx.Window | None) -> None:
        settings = load_settings()
        super().__init__(
            parent,
            title=translate(settings.language, "PartPort — Component Search & Import"),
            size=(1180, 800),
        )
        self.settings = settings
        self.catalog_client = CatalogClient()
        self.catalog = load_global_library_catalog()
        self.runner = JLC2Runner()
        self.global_importer = GlobalLibraryImporter(self.runner)
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.search_generation = 0
        self.detail_generation = 0
        self.results: list[PartRecord] = []
        self.selected_part: PartRecord | None = None
        self.symbol_entries: list[LibraryEntry] = []
        self.footprint_entries: list[LibraryEntry] = []
        self._build_ui()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        wx.CallAfter(self._discover_project)

    def _t(self, text: str, **values) -> str:
        return translate(self.settings.language, text, **values)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(panel)
        search_page = wx.Panel(self.notebook)
        settings_page = wx.ScrolledWindow(self.notebook, style=wx.VSCROLL)
        settings_page.SetScrollRate(0, 12)
        self.notebook.AddPage(search_page, self._t("Search & Import"))
        self.notebook.AddPage(settings_page, self._t("Settings"))
        self._build_search_page(search_page)
        self._build_settings_page(settings_page)
        outer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(outer)
        self.Centre()

    def _build_search_page(self, panel: wx.Panel) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.search_ctrl = wx.SearchCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetDescriptiveText(self._t("Search by model, LCSC code, keyword or URL"))
        self.search_ctrl.ShowCancelButton(True)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._start_search)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self._start_search)
        self.search_btn = wx.Button(panel, label=self._t("Search"))
        self.search_btn.Bind(wx.EVT_BUTTON, self._start_search)
        self.search_status = wx.StaticText(panel, label=self._source_summary())
        search_row.Add(self.search_ctrl, 1, wx.EXPAND | wx.RIGHT, 8)
        search_row.Add(self.search_btn, 0, wx.RIGHT, 12)
        search_row.Add(self.search_status, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(search_row, 0, wx.EXPAND | wx.ALL, 10)

        splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        left = wx.Panel(splitter)
        right = wx.Panel(splitter)
        self._build_result_panel(left)
        self._build_preview_panel(right)
        splitter.SplitVertically(left, right, 525)
        splitter.SetMinimumPaneSize(330)
        splitter.SetSashGravity(0.46)
        outer.Add(splitter, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self._build_action_panel(panel, outer)

        self.log_pane = wx.CollapsiblePane(panel, label=self._t("Activity log"))
        self.log_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda _event: panel.Layout())
        log_parent = self.log_pane.GetPane()
        log_sizer = wx.BoxSizer(wx.VERTICAL)
        self.log_ctrl = wx.TextCtrl(
            log_parent,
            size=(-1, 105),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        log_sizer.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        log_parent.SetSizer(log_sizer)
        outer.Add(self.log_pane, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(outer)

    def _build_result_panel(self, panel: wx.Panel) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label=self._t("Search results"))
        font = title.GetFont()
        font.MakeBold()
        title.SetFont(font)
        outer.Add(title, 0, wx.LEFT | wx.BOTTOM, 4)
        self.result_list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SIMPLE
        )
        for index, (label, width) in enumerate(
            (
                ("LCSC", 85),
                (self._t("Model"), 150),
                (self._t("Manufacturer"), 105),
                (self._t("Package"), 105),
                (self._t("Stock"), 75),
                (self._t("Price"), 70),
            )
        ):
            self.result_list.InsertColumn(index, label, width=width)
        self.result_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_result_selected)
        self.result_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._start_import)
        outer.Add(self.result_list, 1, wx.EXPAND)
        self.result_count = wx.StaticText(panel, label=self._t("Enter a keyword to begin."))
        outer.Add(self.result_count, 0, wx.TOP, 5)
        panel.SetSizer(outer)

    def _build_preview_panel(self, panel: wx.Panel) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)
        heading_row = wx.BoxSizer(wx.HORIZONTAL)
        self.part_heading = wx.StaticText(panel, label=self._t("Select a result to preview"))
        font = self.part_heading.GetFont()
        font.SetPointSize(font.GetPointSize() + 2)
        font.MakeBold()
        self.part_heading.SetFont(font)
        heading_row.Add(self.part_heading, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(heading_row, 0, wx.EXPAND | wx.BOTTOM, 5)

        self.preview_tabs = wx.Notebook(panel)
        self.details_ctrl = wx.TextCtrl(
            self.preview_tabs,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.BORDER_NONE,
        )
        self.symbol_view = wx.html2.WebView.New(self.preview_tabs)
        self.footprint_view = wx.html2.WebView.New(self.preview_tabs)
        self.image_view = wx.html2.WebView.New(self.preview_tabs)
        self.preview_tabs.AddPage(self.details_ctrl, self._t("Data"))
        self.preview_tabs.AddPage(self.symbol_view, self._t("Symbol"))
        self.preview_tabs.AddPage(self.footprint_view, self._t("Footprint"))
        self.preview_tabs.AddPage(self.image_view, self._t("Part image"))
        outer.Add(self.preview_tabs, 1, wx.EXPAND)
        self._set_preview_message(self.symbol_view, self._t("No symbol preview selected."))
        self._set_preview_message(self.footprint_view, self._t("No footprint preview selected."))
        self._set_preview_message(self.image_view, self._t("No part image selected."))
        panel.SetSizer(outer)

    def _build_action_panel(self, panel: wx.Panel, outer: wx.BoxSizer) -> None:
        box = wx.StaticBoxSizer(wx.VERTICAL, panel, self._t("Actions"))
        parent = box.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.symbol_cb = wx.CheckBox(parent, label=self._t("Symbol"))
        self.symbol_cb.SetValue(True)
        self.footprint_cb = wx.CheckBox(parent, label=self._t("Footprint"))
        self.footprint_cb.SetValue(True)
        self.step_cb = wx.CheckBox(parent, label="STEP")
        self.step_cb.SetValue(True)
        self.wrl_cb = wx.CheckBox(parent, label="WRL")
        self.skip_cb = wx.CheckBox(parent, label=self._t("Skip existing"))
        self.skip_cb.SetValue(True)
        for control in (
            self.symbol_cb,
            self.footprint_cb,
            self.step_cb,
            self.wrl_cb,
            self.skip_cb,
        ):
            row.Add(control, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 12)
        row.AddStretchSpacer()
        self.open_source_btn = wx.Button(parent, label=self._t("Open product page"))
        self.open_source_btn.Enable(False)
        self.open_source_btn.Bind(wx.EVT_BUTTON, self._open_product_page)
        self.import_btn = wx.Button(parent, label=self._t("Download and import"))
        self.import_btn.Enable(False)
        self.import_btn.Bind(wx.EVT_BUTTON, self._start_import)
        self.cancel_btn = wx.Button(parent, label=self._t("Cancel"))
        self.cancel_btn.Enable(False)
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._cancel_import)
        row.Add(self.open_source_btn, 0, wx.RIGHT, 8)
        row.Add(self.import_btn, 0, wx.RIGHT, 8)
        row.Add(self.cancel_btn, 0)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        info_row = wx.BoxSizer(wx.HORIZONTAL)
        self.destination_hint = wx.StaticText(parent, label="")
        info_row.Add(self.destination_hint, 1, wx.ALIGN_CENTER_VERTICAL)
        self.progress = wx.Gauge(parent, range=1, size=(210, -1))
        info_row.Add(self.progress, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 8)
        box.Add(info_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        outer.Add(box, 0, wx.EXPAND | wx.ALL, 10)

    def _build_settings_page(self, panel: wx.ScrolledWindow) -> None:
        outer = wx.BoxSizer(wx.VERTICAL)

        general = wx.StaticBoxSizer(wx.VERTICAL, panel, self._t("General"))
        general_parent = general.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(general_parent, label=self._t("Interface language")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.language_choice = wx.Choice(general_parent, choices=("中文", "English"))
        self.language_choice.SetSelection(0 if self.settings.language == "zh_CN" else 1)
        row.Add(self.language_choice, 0)
        general.Add(row, 0, wx.ALL, 8)
        outer.Add(general, 0, wx.EXPAND | wx.ALL, 10)

        sources_box = wx.StaticBoxSizer(wx.VERTICAL, panel, self._t("Data sources"))
        sources_parent = sources_box.GetStaticBox()
        source_row = wx.BoxSizer(wx.HORIZONTAL)
        self.lcsc_source_cb = wx.CheckBox(sources_parent, label="LCSC.com")
        self.lcsc_source_cb.SetValue("lcsc" in self.settings.data_sources)
        self.szlcsc_source_cb = wx.CheckBox(sources_parent, label="SZLCSC.com / item.szlcsc.com")
        self.szlcsc_source_cb.SetValue("szlcsc" in self.settings.data_sources)
        source_row.Add(self.lcsc_source_cb, 0, wx.RIGHT, 24)
        source_row.Add(self.szlcsc_source_cb, 0)
        sources_box.Add(source_row, 0, wx.ALL, 8)
        source_note = wx.StaticText(
            sources_parent,
            label=self._t(
                "Choose one or both storefronts for catalog metadata. CAD previews and conversion use the EasyEDA/Lceda component record linked to the LCSC code."
            ),
        )
        source_note.Wrap(1000)
        sources_box.Add(source_note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        outer.Add(sources_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        destination_box = wx.StaticBoxSizer(wx.VERTICAL, panel, self._t("Library destination"))
        destination_parent = destination_box.GetStaticBox()
        self.destination_radio = wx.RadioBox(
            destination_parent,
            choices=(
                self._t("Project-local PartPort library (recommended)"),
                self._t("Existing global libraries"),
            ),
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.destination_radio.SetSelection(1 if self.settings.destination == "global" else 0)
        self.destination_radio.Bind(wx.EVT_RADIOBOX, self._on_destination_changed)
        destination_box.Add(self.destination_radio, 0, wx.EXPAND | wx.ALL, 8)

        project_grid = wx.FlexGridSizer(cols=2, hgap=8, vgap=6)
        project_grid.AddGrowableCol(1, 1)
        project_grid.Add(wx.StaticText(destination_parent, label=self._t("KiCad project folder")), 0, wx.ALIGN_CENTER_VERTICAL)
        project_row = wx.BoxSizer(wx.HORIZONTAL)
        self.project_ctrl = wx.TextCtrl(destination_parent, value=self.settings.project_directory)
        project_row.Add(self.project_ctrl, 1, wx.RIGHT, 8)
        browse_btn = wx.Button(destination_parent, label=self._t("Browse…"))
        browse_btn.Bind(wx.EVT_BUTTON, self._browse_project)
        project_row.Add(browse_btn, 0)
        project_grid.Add(project_row, 1, wx.EXPAND)
        project_grid.AddSpacer(1)
        self.context_hint = wx.StaticText(destination_parent, label=self._t("Detecting the current KiCad project…"))
        project_grid.Add(self.context_hint, 1, wx.EXPAND)
        destination_box.Add(project_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        outer.Add(destination_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        global_box = wx.StaticBoxSizer(wx.VERTICAL, panel, self._t("Global library selection"))
        global_parent = global_box.GetStaticBox()
        grid = wx.FlexGridSizer(cols=2, hgap=8, vgap=8)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(global_parent, label=self._t("Symbol library")), 0, wx.ALIGN_CENTER_VERTICAL)
        self.global_symbol_choice = wx.Choice(global_parent)
        self.global_symbol_choice.Bind(wx.EVT_CHOICE, self._on_library_choice)
        grid.Add(self.global_symbol_choice, 1, wx.EXPAND)
        grid.Add(wx.StaticText(global_parent, label=self._t("Symbol path")), 0, wx.ALIGN_TOP)
        self.global_symbol_path = wx.StaticText(global_parent, label="—")
        grid.Add(self.global_symbol_path, 1, wx.EXPAND)
        grid.Add(wx.StaticText(global_parent, label=self._t("Footprint library")), 0, wx.ALIGN_CENTER_VERTICAL)
        self.global_footprint_choice = wx.Choice(global_parent)
        self.global_footprint_choice.Bind(wx.EVT_CHOICE, self._on_library_choice)
        grid.Add(self.global_footprint_choice, 1, wx.EXPAND)
        grid.Add(wx.StaticText(global_parent, label=self._t("Footprint path")), 0, wx.ALIGN_TOP)
        self.global_footprint_path = wx.StaticText(global_parent, label="—")
        grid.Add(self.global_footprint_path, 1, wx.EXPAND)
        grid.Add(wx.StaticText(global_parent, label=self._t("3D model path")), 0, wx.ALIGN_TOP)
        self.model_path = wx.StaticText(global_parent, label="—")
        grid.Add(self.model_path, 1, wx.EXPAND)
        global_box.Add(grid, 1, wx.EXPAND | wx.ALL, 8)
        model_note = wx.StaticText(
            global_parent,
            label=self._t("3D models are stored in the packages3d folder inside the selected footprint library."),
        )
        model_note.Wrap(1000)
        global_box.Add(model_note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        outer.Add(global_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        refresh = wx.Button(panel, label=self._t("Refresh libraries"))
        refresh.Bind(wx.EVT_BUTTON, self._refresh_global_libraries)
        save = wx.Button(panel, label=self._t("Save settings"))
        save.Bind(wx.EVT_BUTTON, self._save_configuration)
        button_row.Add(refresh, 0, wx.RIGHT, 8)
        button_row.Add(save, 0)
        outer.Add(button_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.config_status = wx.StaticText(panel, label="")
        outer.Add(self.config_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        panel.SetSizer(outer)
        self._populate_library_choices()
        self._update_settings_state()

    def _source_summary(self) -> str:
        labels = ["LCSC" if source == "lcsc" else "SZLCSC" for source in self.settings.data_sources]
        return self._t("Sources: {sources}", sources=" + ".join(labels))

    def _start_search(self, _event: wx.CommandEvent) -> None:
        query = self.search_ctrl.GetValue().strip()
        if not query:
            return
        self.search_generation += 1
        generation = self.search_generation
        self.search_btn.Enable(False)
        self.search_status.SetLabel(self._t("Searching…"))
        self.result_count.SetLabel(self._t("Searching catalog…"))
        threading.Thread(
            target=self._search_worker,
            args=(generation, query, self.settings.data_sources),
            daemon=True,
        ).start()

    def _search_worker(self, generation: int, query: str, sources: tuple[str, ...]) -> None:
        try:
            result = self.catalog_client.search(query, sources)
            error = ""
        except CatalogError as exc:
            result = SearchResult(())
            error = str(exc)
        wx.CallAfter(self._finish_search, generation, result, error)

    def _finish_search(self, generation: int, result: SearchResult, error: str) -> None:
        if generation != self.search_generation:
            return
        self.search_btn.Enable(True)
        self.search_status.SetLabel(self._source_summary())
        self.results = list(result.parts)
        self.selected_part = None
        self.result_list.DeleteAllItems()
        for row, part in enumerate(self.results):
            index = self.result_list.InsertItem(row, part.code)
            values = (
                part.model,
                part.manufacturer,
                part.package,
                f"{part.stock:,}" if part.stock is not None else "—",
                part.price or "—",
            )
            for column, value in enumerate(values, start=1):
                self.result_list.SetItem(index, column, value)
        if error:
            self.result_count.SetLabel(self._t("Search failed: {message}", message=error))
            self._append_log(self._t("Search failed: {message}", message=error))
        else:
            self.result_count.SetLabel(self._t("{count} result(s)", count=len(self.results)))
            if result.warnings:
                self._append_log("; ".join(result.warnings))
        if self.results:
            self.result_list.Select(0)
            self.result_list.Focus(0)

    def _on_result_selected(self, event: wx.ListEvent) -> None:
        index = event.GetIndex()
        if not 0 <= index < len(self.results):
            return
        self.selected_part = self.results[index]
        self.import_btn.Enable(True)
        self.open_source_btn.Enable(bool(self.selected_part.product_url))
        self._show_part(self.selected_part, loading=True)
        self.detail_generation += 1
        generation = self.detail_generation
        threading.Thread(
            target=self._detail_worker,
            args=(generation, self.selected_part, self.settings.data_sources),
            daemon=True,
        ).start()

    def _detail_worker(
        self, generation: int, part: PartRecord, sources: tuple[str, ...]
    ) -> None:
        try:
            detailed = self.catalog_client.detail(part, sources)
            error = ""
        except CatalogError as exc:
            detailed = part
            error = str(exc)
        wx.CallAfter(self._finish_detail, generation, detailed, error)

    def _finish_detail(self, generation: int, part: PartRecord, error: str) -> None:
        if generation != self.detail_generation:
            return
        self.selected_part = part
        self._show_part(part, loading=False)
        self.open_source_btn.Enable(bool(part.product_url))
        if error:
            self._append_log(self._t("Detail warning: {message}", message=error))

    def _show_part(self, part: PartRecord, loading: bool) -> None:
        self.part_heading.SetLabel(f"{part.code}   {part.model}")
        source_names = ", ".join("LCSC" if x == "lcsc" else "SZLCSC" for x in part.sources)
        lines = [
            f"{self._t('Source')}: {source_names or '—'}",
            f"LCSC: {part.code}",
            f"{self._t('Model')}: {part.model or '—'}",
            f"{self._t('Manufacturer')}: {part.manufacturer or '—'}",
            f"{self._t('Package')}: {part.package or '—'}",
            f"{self._t('Category')}: {part.category or '—'}",
            f"{self._t('Stock')}: {part.stock if part.stock is not None else '—'}",
            f"{self._t('Price')}: {part.price or '—'}",
            "",
            part.description or "",
        ]
        if part.attributes:
            lines.extend(("", self._t("Parameters")))
            lines.extend(f"{key}: {value}" for key, value in part.attributes)
        if loading:
            lines.extend(("", self._t("Loading details and previews…")))
        self.details_ctrl.SetValue("\n".join(lines))
        self._refresh_preview_views(part, loading)

    def _refresh_preview_views(self, part: PartRecord, loading: bool) -> None:
        symbols = tuple(
            sanitize_svg(item) for item in extract_svg_documents(part.symbol_svg)
        )
        footprint = sanitize_svg(part.footprint_svg) if part.footprint_svg else ""
        self._set_svg_preview(
            self.symbol_view,
            symbols,
            self._t("Symbol preview unavailable."),
            loading,
        )
        self._set_svg_preview(
            self.footprint_view,
            (footprint,) if footprint else (),
            self._t("Footprint preview unavailable."),
            loading,
        )
        self._set_part_image(part, loading)

    def _set_svg_preview(
        self,
        view: wx.html2.WebView,
        documents: tuple[str, ...],
        empty_message: str,
        loading: bool,
    ) -> None:
        if documents:
            cards = []
            for index, svg in enumerate(documents, start=1):
                graphic = (
                    f'<img src="{html.escape(svg, quote=True)}">'
                    if svg.startswith(("http://", "https://"))
                    else svg
                )
                unit = (
                    f"<div class='unit'>{html.escape(self._t('Unit {index}', index=index))}</div>"
                    if len(documents) > 1
                    else ""
                )
                cards.append(f'<section class="canvas">{unit}{graphic}</section>')
            body = "".join(cards)
            view.SetPage(self._preview_html(body), "https://lceda.cn/")
        else:
            self._set_preview_message(
                view, self._t("Loading preview…") if loading else empty_message
            )

    def _set_part_image(self, part: PartRecord, loading: bool) -> None:
        if loading:
            self._set_preview_message(self.image_view, self._t("Loading part image…"))
            return
        if not part.image_url:
            self._set_preview_message(self.image_view, self._t("Part image unavailable."))
            return
        body = (
            f'<section class="canvas model-canvas"><img class="product" '
            f'src="{html.escape(part.image_url, quote=True)}"></section>'
            f"<h3>{html.escape(part.code)} {html.escape(part.model)}</h3>"
            f"<p class='muted'>{html.escape(self._t('Product image from the selected data source.'))}</p>"
        )
        self.image_view.SetPage(
            self._preview_html(body), part.product_url or "https://www.lcsc.com/"
        )

    def _preview_html(self, body: str) -> str:
        return build_preview_html(
            body,
            self._t("Zoom out"),
            self._t("Reset zoom"),
            self._t("Zoom in"),
            self._t("Mouse wheel"),
        )

    def _set_preview_message(self, view: wx.html2.WebView, message: str) -> None:
        view.SetPage(self._preview_html(f"<p class='muted'>{html.escape(message)}</p>"), "")

    def _open_product_page(self, _event: wx.CommandEvent) -> None:
        if self.selected_part and self.selected_part.product_url:
            webbrowser.open(self.selected_part.product_url)

    def _entry_label(self, entry: LibraryEntry) -> str:
        suffix = "" if entry.writable else f" [{self._t('unavailable')}: {self._t(entry.reason)}]"
        return f"{entry.nickname} — {entry.path or entry.uri}{suffix}"

    def _populate_library_choices(self) -> None:
        self.symbol_entries = list(self.catalog.symbols)
        self.footprint_entries = list(self.catalog.footprints)
        self.global_symbol_choice.Set([self._entry_label(item) for item in self.symbol_entries])
        self.global_footprint_choice.Set([self._entry_label(item) for item in self.footprint_entries])
        self._select_library(self.global_symbol_choice, self.symbol_entries, self.settings.global_symbol_library)
        self._select_library(self.global_footprint_choice, self.footprint_entries, self.settings.global_footprint_library)
        self._update_library_paths()

    @staticmethod
    def _select_library(choice: wx.Choice, entries: list[LibraryEntry], nickname: str) -> None:
        index = next((i for i, item in enumerate(entries) if item.nickname == nickname), -1)
        if index < 0:
            index = next((i for i, item in enumerate(entries) if item.writable), -1)
        choice.SetSelection(index)

    @staticmethod
    def _selected_entry(choice: wx.Choice, entries: list[LibraryEntry]) -> LibraryEntry | None:
        index = choice.GetSelection()
        return entries[index] if 0 <= index < len(entries) else None

    def _update_library_paths(self) -> None:
        symbol = self._selected_entry(self.global_symbol_choice, self.symbol_entries)
        footprint = self._selected_entry(self.global_footprint_choice, self.footprint_entries)
        self.global_symbol_path.SetLabel(str(symbol.path) if symbol and symbol.path else "—")
        self.global_footprint_path.SetLabel(str(footprint.path) if footprint and footprint.path else "—")
        self._update_model_path()

    def _model_path_text(self) -> str:
        if self.destination_radio.GetSelection() == 1:
            footprint = self._selected_entry(self.global_footprint_choice, self.footprint_entries)
            return str(footprint.path / "packages3d") if footprint and footprint.path else "—"
        project = self.project_ctrl.GetValue().strip()
        return (
            str(Path(project) / "PartPortLib" / "partport.pretty" / "packages3d")
            if project
            else "${KIPRJMOD}/PartPortLib/partport.pretty/packages3d"
        )

    def _update_model_path(self) -> None:
        self.model_path.SetLabel(self._model_path_text())

    def _on_library_choice(self, _event: wx.CommandEvent) -> None:
        self._update_library_paths()

    def _on_destination_changed(self, _event: wx.CommandEvent) -> None:
        self._update_settings_state()

    def _update_settings_state(self) -> None:
        global_enabled = self.destination_radio.GetSelection() == 1
        self.global_symbol_choice.Enable(global_enabled)
        self.global_footprint_choice.Enable(global_enabled)
        self.project_ctrl.Enable(not global_enabled)
        self._update_model_path()
        self._update_destination_hint()

    def _update_destination_hint(self) -> None:
        if self.destination_radio.GetSelection() == 1:
            symbol = self._selected_entry(self.global_symbol_choice, self.symbol_entries)
            footprint = self._selected_entry(self.global_footprint_choice, self.footprint_entries)
            target = f"{self._t('global')} {symbol.nickname if symbol else '?'} / {footprint.nickname if footprint else '?'}"
        else:
            target = self._t("project-local PartPort library")
        self.destination_hint.SetLabel(self._t("Destination: {target}", target=target))

    def _refresh_global_libraries(self, _event: wx.CommandEvent) -> None:
        self.catalog = load_global_library_catalog()
        self._populate_library_choices()
        self.config_status.SetLabel(self._t("Reloaded: {path}", path=self.catalog.config_dir))

    def _settings_from_controls(self) -> PartPortSettings:
        symbol = self._selected_entry(self.global_symbol_choice, self.symbol_entries)
        footprint = self._selected_entry(self.global_footprint_choice, self.footprint_entries)
        sources = tuple(
            source
            for source, enabled in (
                ("lcsc", self.lcsc_source_cb.GetValue()),
                ("szlcsc", self.szlcsc_source_cb.GetValue()),
            )
            if enabled
        )
        return PartPortSettings(
            destination="global" if self.destination_radio.GetSelection() == 1 else "project",
            global_symbol_library=symbol.nickname if symbol else "",
            global_footprint_library=footprint.nickname if footprint else "",
            language="zh_CN" if self.language_choice.GetSelection() == 0 else "en",
            project_directory=self.project_ctrl.GetValue().strip(),
            data_sources=sources,
        )

    def _save_configuration(self, _event: wx.CommandEvent | None = None) -> bool:
        settings = self._settings_from_controls()
        if not settings.data_sources:
            message = self._t("Select at least one data source.")
            self.config_status.SetLabel(message)
            if _event is not None:
                wx.MessageBox(message, "PartPort", wx.OK | wx.ICON_WARNING)
            return False
        if settings.destination == "global":
            symbol = self._selected_entry(self.global_symbol_choice, self.symbol_entries)
            footprint = self._selected_entry(self.global_footprint_choice, self.footprint_entries)
            unavailable = [
                item.reason if item else self._t("No library selected")
                for item in (symbol, footprint)
                if not item or not item.writable
            ]
            if unavailable:
                message = self._t("Cannot use the selected global libraries") + ": " + "; ".join(unavailable)
                self.config_status.SetLabel(message)
                if _event is not None:
                    wx.MessageBox(message, "PartPort", wx.OK | wx.ICON_ERROR)
                return False
        language_changed = settings.language != self.settings.language
        self.settings = settings
        path = save_settings(settings)
        self.search_status.SetLabel(self._source_summary())
        self._update_destination_hint()
        status = self._t("Saved to {path}", path=path)
        if language_changed:
            status += " " + translate(settings.language, "Language changes take effect after reopening PartPort.")
        self.config_status.SetLabel(status)
        return True

    def _discover_project(self) -> None:
        if self.project_ctrl.GetValue().strip():
            project = find_project_file(Path(self.project_ctrl.GetValue()).expanduser())
            self.context_hint.SetLabel(
                self._t("Project: {path}", path=project)
                if project
                else self._t("Saved folder; no unique .kicad_pro found.")
            )
            self._update_model_path()
            return
        context = discover_project_context()
        if context.project_dir:
            self.project_ctrl.SetValue(str(context.project_dir))
            self.context_hint.SetLabel(self._t("Detected: {path}", path=context.project_file or context.project_dir))
        else:
            self.context_hint.SetLabel(
                context.warning
                if self.settings.language == "en"
                else self._t("Could not automatically detect the project. Select its folder manually.")
            )
        self._update_model_path()

    def _browse_project(self, _event: wx.CommandEvent) -> None:
        current = self.project_ctrl.GetValue().strip()
        default = current if current and Path(current).is_dir() else ""
        dialog = wx.DirDialog(self, self._t("Select the KiCad project folder"), defaultPath=default)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                selected = Path(dialog.GetPath()).resolve()
                self.project_ctrl.SetValue(str(selected))
                project = find_project_file(selected)
                self.context_hint.SetLabel(
                    self._t("Project: {path}", path=project)
                    if project
                    else self._t("Folder selected; no unique .kicad_pro found.")
                )
                self._update_model_path()
        finally:
            dialog.Destroy()

    def _start_import(self, _event: wx.CommandEvent) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.selected_part:
            wx.MessageBox(self._t("Select a search result first."), "PartPort", wx.OK | wx.ICON_WARNING)
            return
        if not self._save_configuration():
            self.notebook.SetSelection(1)
            return
        project_dir = Path(self.project_ctrl.GetValue().strip()).expanduser()
        if self.settings.destination == "project" and not project_dir.is_dir():
            wx.MessageBox(self._t("Select a valid KiCad project folder in Settings."), "PartPort", wx.OK | wx.ICON_ERROR)
            self.notebook.SetSelection(1)
            return
        if self.settings.destination == "project" and find_project_file(project_dir) is None:
            wx.MessageBox(self._t("The selected folder must contain exactly one .kicad_pro file."), "PartPort", wx.OK | wx.ICON_ERROR)
            self.notebook.SetSelection(1)
            return
        if not self.symbol_cb.GetValue() and not self.footprint_cb.GetValue():
            wx.MessageBox(self._t("Select Symbol or Footprint."), "PartPort", wx.OK | wx.ICON_WARNING)
            return
        models = tuple(
            model
            for model, enabled in (("STEP", self.step_cb.GetValue()), ("WRL", self.wrl_cb.GetValue()))
            if enabled
        )
        options = RunnerOptions(
            import_symbol=self.symbol_cb.GetValue(),
            import_footprint=self.footprint_cb.GetValue(),
            models=models,
            skip_existing=self.skip_cb.GetValue(),
        )
        self.cancel_event.clear()
        self.progress.SetRange(1)
        self.progress.SetValue(0)
        self.import_btn.Enable(False)
        self.cancel_btn.Enable(True)
        symbol_target = self._selected_entry(self.global_symbol_choice, self.symbol_entries)
        footprint_target = self._selected_entry(self.global_footprint_choice, self.footprint_entries)
        self._append_log(self._t("Starting import of {code}", code=self.selected_part.code))
        self.worker = threading.Thread(
            target=self._import_worker,
            args=(
                project_dir.resolve() if project_dir.is_dir() else Path.cwd(),
                [self.selected_part.code],
                options,
                self.settings,
                symbol_target,
                footprint_target,
            ),
            daemon=True,
        )
        self.worker.start()

    def _import_worker(
        self,
        project_dir: Path,
        codes: list[str],
        options: RunnerOptions,
        settings: PartPortSettings,
        symbol_target: LibraryEntry | None,
        footprint_target: LibraryEntry | None,
    ) -> None:
        successes = skipped = partial = 0
        failures: list[str] = []
        for index, code in enumerate(codes, start=1):
            if self.cancel_event.is_set():
                break
            wx.CallAfter(self._append_log, f"\n[{index}/{len(codes)}] {code}")
            line_callback = lambda line: wx.CallAfter(self._append_log, line)
            if settings.destination == "global":
                assert symbol_target is not None and footprint_target is not None
                result = self.global_importer.import_code(
                    code, options, symbol_target, footprint_target, line_callback, self.cancel_event
                )
            else:
                snapshot = OutputSnapshot.capture(project_dir)
                result = self.runner.run(code, project_dir, options, line_callback, self.cancel_event)
                if result.status == ResultStatus.SUCCESS:
                    report = validate_import(project_dir, options, snapshot, result.output)
                    result.status = report.status
                    for warning in report.warnings:
                        wx.CallAfter(self._append_log, self._t("Validation warning: {message}", message=warning))
                    if report.errors:
                        result.message = " ".join(report.errors)
            if result.status == ResultStatus.SUCCESS:
                successes += 1
                wx.CallAfter(self._append_log, self._t("Result: OK ({seconds:.1f}s)", seconds=result.elapsed_seconds))
            elif result.status == ResultStatus.PARTIAL:
                successes += 1
                partial += 1
                wx.CallAfter(self._append_log, self._t("Result: PARTIAL ({seconds:.1f}s)", seconds=result.elapsed_seconds))
            elif result.status == ResultStatus.SKIPPED:
                successes += 1
                skipped += 1
                wx.CallAfter(self._append_log, self._t("Result: SKIPPED (already exists)"))
            else:
                failures.append(code)
                wx.CallAfter(self._append_log, self._t("Result: {status} — {message}", status=result.status.value.upper(), message=result.message))
            wx.CallAfter(self.progress.SetValue, index)

        tables_changed = False
        table_error = ""
        if successes and settings.destination == "project":
            try:
                tables_changed = register_project_libraries(
                    project_dir, symbol=options.import_symbol, footprint=options.import_footprint
                )
            except LibraryTableError as exc:
                table_error = str(exc)
        wx.CallAfter(
            self._finish_import,
            successes,
            skipped,
            partial,
            failures,
            tables_changed,
            table_error,
            self.cancel_event.is_set(),
        )

    def _finish_import(
        self,
        successes: int,
        skipped: int,
        partial: int,
        failures: list[str],
        tables_changed: bool,
        table_error: str,
        cancelled: bool,
    ) -> None:
        self.import_btn.Enable(self.selected_part is not None)
        self.cancel_btn.Enable(False)
        if table_error:
            self._append_log(self._t("Library registration failed: {message}", message=table_error))
        if tables_changed:
            self._append_log(self._t("Project library tables were updated. Close and reopen the Schematic Editor before placing symbols."))
        summary = self._t(
            "Imported: {imported}; skipped: {skipped}; partial: {partial}; failed: {failed}",
            imported=successes - skipped,
            skipped=skipped,
            partial=partial,
            failed=len(failures),
        )
        if cancelled:
            summary += "; " + self._t("cancelled")
        self._append_log("\n" + summary)
        if not self.log_pane.IsExpanded():
            self.log_pane.Expand()
            self.Layout()
        icon = wx.ICON_WARNING if failures or table_error or cancelled else wx.ICON_INFORMATION
        wx.MessageBox(summary, "PartPort", wx.OK | icon)

    def _cancel_import(self, _event: wx.CommandEvent) -> None:
        self.cancel_event.set()
        self.runner.cancel()
        self.cancel_btn.Enable(False)
        self._append_log(self._t("Cancellation requested…"))

    def _append_log(self, line: str) -> None:
        self.log_ctrl.AppendText(line + "\n")
        self.log_ctrl.ShowPosition(self.log_ctrl.GetLastPosition())

    def _on_close(self, event: wx.CloseEvent) -> None:
        self.search_generation += 1
        self.detail_generation += 1
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.runner.cancel()
        event.Skip()
