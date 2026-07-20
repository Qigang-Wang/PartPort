"""KiCad IPC action entry point for PartPort."""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        import wx

        from partport.app import PartPortFrame

        app = wx.App(False)
        frame = PartPortFrame(None)
        frame.Show()
        app.MainLoop()
        return 0
    except Exception:
        details = traceback.format_exc()
        print(details, file=sys.stderr)
        try:
            import wx

            app = wx.App.Get() or wx.App(False)
            wx.MessageBox(details, "PartPort startup error", wx.OK | wx.ICON_ERROR)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
