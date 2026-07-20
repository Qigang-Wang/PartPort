# PartPort

PartPort is a KiCad 10 IPC plugin that searches LCSC/SZLCSC and imports
EasyEDA symbols, footprints, and 3D models into KiCad libraries. It appears in the
Schematic Editor and does not require `JLC2KiCadLib.exe` or a system Python
installation.

## Development install on Windows

1. In KiCad, enable the API server under **Preferences → Plugins**.
2. Run:

   ```powershell
   .\scripts\install-dev.ps1
   ```

3. Restart KiCad. On first load, KiCad creates a private Python environment
   and installs the pinned dependencies from `requirements.txt`; the toolbar
   action may take a minute to appear. If the Schematic Editor was already
   open while that setup completed, close and reopen it once more.
4. Open the Schematic Editor and click **Search and Import Parts**.

The main page is organized as a search workflow: search field at the top,
results on the left, data/symbol/footprint/product-image previews on the right, and
the download/import operation at the bottom. The activity log is collapsed by
default.

The symbol and footprint pages display only sanitized EasyEDA source SVG.
PartPort does not run background KiCad symbol or footprint SVG exports and does
not offer a separate "KiCad output" mode. The Part image page displays the
product image supplied by the selected catalog source. Selecting a result does
not start JLC2KiCadLib or any `kicad-cli` process. Symbol, footprint, and 3D
model conversion occurs only when the user chooses **Download and import**.

Symbol, footprint, and product-image pages provide zoom out,
reset, and zoom in buttons. The mouse wheel and `Ctrl` + `+`/`-`/`0`
provide the same controls from the keyboard and mouse. SVG symbol and
footprint previews automatically fit the available width at 100% and refit
when the preview pane is resized.

SVG is sanitized before it is placed in the embedded browser. Product images
are loaded directly over HTTPS and are not converted by KiCad. When both
storefronts provide an image, the LCSC large image is preferred over the
SZLCSC breviary thumbnail, and the preview fits it to the available width.

The **Settings** page selects one or both catalog data sources:

- `LCSC.com` supplies the international catalog, prices, stock, images, and
  English metadata.
- `SZLCSC.com` / `item.szlcsc.com` enriches product details with the Chinese
  storefront metadata.

Both storefronts share LCSC product codes and product IDs. CAD SVG previews
and the symbol/footprint/3D conversion use the associated EasyEDA/Lceda
component record; changing storefront metadata does not create a different
CAD drawing.

The plugin writes project-local data to:

```text
<project>/PartPortLib/
```

The **Settings** page also contains the project-folder selector and can instead
target existing global KiCad file libraries.
PartPort reads the global symbol and footprint tables, rejects table-based,
missing, installation-owned, or non-writable libraries, and lets the symbol
and footprint destinations be selected separately. Global imports are first
generated and validated in a temporary directory, then merged with
`.partport.bak` backups. The project-local destination remains the default.
The same page selects either Chinese or English for the PartPort interface;
reopen the PartPort window after saving a language change.

3D models are stored inside the active footprint library:

```text
project mode: <project>/PartPortLib/partport.pretty/packages3d/
global mode:  <selected-global-library>.pretty/packages3d/
```

The resolved model destination is shown directly on the Settings page.
The project-folder selector remains on the Settings page and is disabled in
global-library mode; global-library imports do not require a project path.

If KiCad 10 cannot expose the active project path through IPC, select the
project folder on the Settings page. After the first import updates the
project library tables, close and reopen the Schematic Editor before placing
the imported symbol.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Generated third-party library content must be checked before production use,
especially pin numbers, pads, package dimensions, and 3D alignment.
