"""Render deterministic PartPort toolbar icons using KiCad's wxPython."""

from __future__ import annotations

import sys
from pathlib import Path

import wx


def render(path: Path, background: wx.Colour, accent: wx.Colour) -> None:
    bitmap = wx.Bitmap.FromRGBA(32, 32, 0, 0, 0, 0)
    dc = wx.MemoryDC(bitmap)
    graphics = wx.GraphicsContext.Create(dc)
    graphics.SetBrush(wx.Brush(background))
    graphics.SetPen(wx.Pen(background))
    graphics.DrawRoundedRectangle(3, 3, 26, 26, 5)
    graphics.SetPen(wx.Pen(accent, 2))
    for y in (11, 16, 21):
        graphics.StrokeLine(0, y, 4, y)
        graphics.StrokeLine(28, y, 32, y)
    graphics.SetFont(wx.Font(18, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.WHITE)
    graphics.DrawText("P", 9, 5)
    del graphics
    dc.SelectObject(wx.NullBitmap)
    if not bitmap.ConvertToImage().SaveFile(str(path), wx.BITMAP_TYPE_PNG):
        raise RuntimeError(f"Could not save {path}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    resources = root / "resources"
    resources.mkdir(exist_ok=True)
    app = wx.App(False)
    render(resources / "icon-light.png", wx.Colour("#1677c8"), wx.Colour("#5bd6ff"))
    render(resources / "icon-dark.png", wx.Colour("#2997e8"), wx.Colour("#8be5ff"))
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
