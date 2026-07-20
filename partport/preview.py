"""Safe source-preview helpers for symbols, footprints, and product images."""

from __future__ import annotations

import html
import re


def extract_svg_documents(value: str) -> tuple[str, ...]:
    """Split concatenated SVG roots returned for multi-unit symbols."""
    if not value:
        return ()
    documents = re.findall(r"<svg\b.*?</svg>", value, flags=re.IGNORECASE | re.DOTALL)
    return tuple(documents or (value,))


def sanitize_svg(value: str) -> str:
    """Remove executable and externally loaded content before WebView display."""
    value = re.sub(
        r"<\s*(script|foreignObject)\b.*?<\s*/\s*\1\s*>",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    value = re.sub(
        r"\s+on[a-zA-Z]+\s*=\s*(?:\"[^\"]*\"|'[^']*')",
        "",
        value,
        flags=re.IGNORECASE,
    )

    def clean_link(match: re.Match[str]) -> str:
        name, quote, target = match.group(1), match.group(2), match.group(3).strip()
        if target.startswith(("#", "data:image/")):
            return f" {name}={quote}{html.escape(target, quote=True)}{quote}"
        return ""

    return re.sub(
        r"\s+(href|xlink:href)\s*=\s*([\"'])(.*?)\2",
        clean_link,
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )


def build_preview_html(
    body: str,
    zoom_out: str,
    zoom_reset: str,
    zoom_in: str,
    zoom_help: str,
) -> str:
    """Wrap local preview content with CSP-protected zoom controls."""
    labels = [html.escape(value, quote=True) for value in (zoom_out, zoom_reset, zoom_in)]
    help_text = html.escape(zoom_help)
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
        "img-src data: https:; style-src 'unsafe-inline'; "
        "script-src 'nonce-partport-preview'\"><style>"
        "body{font-family:Segoe UI,Arial,sans-serif;background:#fafafa;color:#202124;"
        "margin:0;text-align:center}"
        ".zoom-tools{position:sticky;top:0;z-index:10;display:flex;align-items:center;"
        "justify-content:center;gap:6px;padding:7px;background:#f1f3f4;border-bottom:1px solid #ddd}"
        ".zoom-tools button{min-width:34px;height:28px;border:1px solid #aaa;border-radius:4px;"
        "background:white;color:#202124;cursor:pointer;font:14px Segoe UI,Arial,sans-serif}"
        ".zoom-tools button:hover{background:#e8f0fe;border-color:#6a8fd8}"
        "#zoom-reset{min-width:58px}.zoom-help{color:#666;font-size:12px;margin-left:5px}"
        "#zoom-viewport{padding:18px;overflow:auto}"
        ".canvas{position:relative;min-height:390px;display:flex;align-items:center;"
        "justify-content:center;overflow:auto;background:white;border:1px solid #ddd;"
        "border-radius:8px;margin-bottom:12px}.canvas svg{width:94%;height:auto;max-height:500px}"
        ".unit{position:absolute;top:8px;left:10px;color:#666}"
        ".model-canvas{min-height:260px}"
        ".product{display:block;width:90%;height:auto;max-height:510px;object-fit:contain}"
        ".muted{color:#666}"
        "code{word-break:break-all}</style>"
        f"<div class='zoom-tools' role='toolbar' aria-label='{labels[1]}'>"
        f"<button type='button' id='zoom-out' title='{labels[0]}' aria-label='{labels[0]}'>−</button>"
        f"<button type='button' id='zoom-reset' title='{labels[1]}' aria-label='{labels[1]}'>100%</button>"
        f"<button type='button' id='zoom-in' title='{labels[2]}' aria-label='{labels[2]}'>+</button>"
        f"<span class='zoom-help'>{help_text}</span></div>"
        f"<div id='zoom-viewport'><div id='zoom-content'>{body}</div></div>"
        "<script nonce='partport-preview'>(()=>{"
        "let scale=1;const content=document.getElementById('zoom-content');"
        "const targets=[...content.querySelectorAll('.canvas svg,.canvas img')];"
        "const reset=document.getElementById('zoom-reset');"
        "function apply(next){scale=Math.max(.25,Math.min(4,next));"
        "for(const target of targets){let width=Number(target.dataset.zoomWidth||0);"
        "let height=Number(target.dataset.zoomHeight||0);"
        "if(!width||!height){const box=target.getBoundingClientRect();width=box.width;height=box.height;"
        "if(width>1&&height>1){target.dataset.zoomWidth=String(width);target.dataset.zoomHeight=String(height);}}"
        "if(width&&height){target.style.maxWidth='none';target.style.maxHeight='none';"
        "target.style.width=(width*scale)+'px';target.style.height=(height*scale)+'px';}}"
        "reset.textContent=Math.round(scale*100)+'%';}"
        "for(const target of targets){if(target.tagName==='IMG'&&!target.complete)"
        "target.addEventListener('load',()=>apply(scale),{once:true});}"
        "document.getElementById('zoom-out').addEventListener('click',()=>apply(scale/1.25));"
        "document.getElementById('zoom-in').addEventListener('click',()=>apply(scale*1.25));"
        "reset.addEventListener('click',()=>apply(1));"
        "document.getElementById('zoom-viewport').addEventListener('wheel',event=>{"
        "event.preventDefault();apply(scale*(event.deltaY<0?1.1:1/1.1));"
        "},{passive:false});"
        "document.addEventListener('keydown',event=>{if(!(event.ctrlKey||event.metaKey))return;"
        "if(event.key==='+'||event.key==='='){event.preventDefault();apply(scale*1.25);}"
        "else if(event.key==='-'){event.preventDefault();apply(scale/1.25);}"
        "else if(event.key==='0'){event.preventDefault();apply(1);}});"
        "window.addEventListener('resize',()=>{const previous=scale;"
        "for(const target of targets){target.style.width='';target.style.height='';"
        "target.style.maxWidth='';target.style.maxHeight='';delete target.dataset.zoomWidth;"
        "delete target.dataset.zoomHeight;}requestAnimationFrame(()=>apply(previous));});"
        "apply(1);})()</script>"
    )
