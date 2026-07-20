"""Catalog search, metadata enrichment and EasyEDA preview retrieval."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Iterable

import requests


LCSC_API = "https://wmsc.lcsc.com/ftps/wm"
SZ_ITEM = "https://item.szlcsc.com"
EDA_API = "https://lceda.cn/api"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PartPort/0.4",
    "Accept": "application/json, text/plain, */*",
}
CODE_RE = re.compile(r"\bC\d+\b", re.IGNORECASE)
ITEM_ID_RE = re.compile(r"item\.szlcsc\.com/(\d+)\.html", re.IGNORECASE)


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class PartRecord:
    code: str
    product_id: str = ""
    model: str = ""
    manufacturer: str = ""
    package: str = ""
    category: str = ""
    description: str = ""
    stock: int | None = None
    price: str = ""
    image_url: str = ""
    datasheet_url: str = ""
    product_url: str = ""
    sources: tuple[str, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()
    symbol_svg: str = ""
    footprint_svg: str = ""
    has_3d_model: bool | None = None
    eda_update_time: int = 0

    def merged(self, other: "PartRecord") -> "PartRecord":
        """Prefer non-empty values from *other*, retaining all provenance."""
        values: dict[str, Any] = {}
        for name in self.__dataclass_fields__:
            if name in {"sources", "attributes"}:
                continue
            candidate = getattr(other, name)
            values[name] = candidate if candidate not in (None, "") else getattr(self, name)
        values["sources"] = tuple(dict.fromkeys((*self.sources, *other.sources)))
        values["attributes"] = other.attributes or self.attributes
        return replace(self, **values)


@dataclass(frozen=True)
class SearchResult:
    parts: tuple[PartRecord, ...]
    warnings: tuple[str, ...] = ()


class CatalogClient:
    def __init__(self, timeout: float = 18.0, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def search(self, query: str, sources: Iterable[str], limit: int = 40) -> SearchResult:
        query = query.strip()
        if not query:
            return SearchResult(())
        selected = tuple(dict.fromkeys(sources))
        if not selected:
            raise CatalogError("Select at least one data source in Settings.")

        item_match = ITEM_ID_RE.search(query)
        if item_match and "szlcsc" in selected:
            part = self._sz_detail(item_match.group(1))
            return SearchResult((part,))

        # Both storefronts use the same LCSC code/product-id catalog.  The public
        # LCSC index is also the stable resolver for SZLCSC product detail pages.
        parts = self._lcsc_search(query, limit)
        if "lcsc" not in selected:
            parts = [replace(item, sources=("szlcsc",), product_url="") for item in parts]
        elif "szlcsc" in selected:
            parts = [replace(item, sources=("lcsc", "szlcsc")) for item in parts]
        return SearchResult(tuple(parts))

    def detail(self, part: PartRecord, sources: Iterable[str]) -> PartRecord:
        selected = tuple(dict.fromkeys(sources))
        result = part
        # The LCSC search/detail payload normally supplies productImageUrlBig,
        # while the SZLCSC detail payload often contains only a small thumbnail.
        # Preserve the best image already found instead of allowing later
        # metadata enrichment to downgrade it.
        preferred_image = result.image_url
        if "lcsc" in selected:
            lcsc_detail = self._lcsc_detail(part.code)
            result = result.merged(lcsc_detail)
            preferred_image = lcsc_detail.image_url or preferred_image
        if "szlcsc" in selected and part.product_id:
            try:
                result = result.merged(self._sz_detail(part.product_id))
            except CatalogError:
                pass
        if preferred_image:
            result = replace(result, image_url=preferred_image)
        try:
            result = result.merged(self._eda_previews(part.code))
        except CatalogError:
            pass
        return result

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CatalogError(f"Catalog request failed: {exc}") from exc
        if isinstance(data, dict) and data.get("code") not in (None, 0, 200):
            raise CatalogError(str(data.get("msg") or "Catalog returned an error"))
        return data

    def _lcsc_search(self, query: str, limit: int) -> list[PartRecord]:
        data = self._request_json(
            "POST",
            f"{LCSC_API}/product/query/list",
            json={"keyword": query, "currentPage": 1, "pageSize": max(1, min(limit, 100))},
            headers={"Origin": "https://www.lcsc.com", "Referer": "https://www.lcsc.com/"},
        )
        rows = (data.get("result") or {}).get("dataList") or []
        return [self._from_lcsc(item) for item in rows]

    def _lcsc_detail(self, code: str) -> PartRecord:
        data = self._request_json(
            "GET",
            f"{LCSC_API}/product/detail",
            params={"productCode": code.upper()},
            headers={"Referer": "https://www.lcsc.com/"},
        )
        row = data.get("result") or {}
        if not row:
            raise CatalogError(f"No LCSC detail found for {code}")
        part = self._from_lcsc(row)
        svg_info = row.get("edaSvgInfo") or {}
        attrs = tuple(
            (
                str(item.get("paramNameEn") or item.get("paramName") or ""),
                str(item.get("paramValueEn") or item.get("paramValue") or ""),
            )
            for item in (row.get("paramVOList") or [])
            if item.get("paramNameEn") or item.get("paramName")
        )
        return replace(
            part,
            attributes=attrs,
            symbol_svg=self._absolute(svg_info.get("schSvg", "")),
            footprint_svg=self._absolute(svg_info.get("pcbSvg", "")),
        )

    @staticmethod
    def _from_lcsc(row: dict[str, Any]) -> PartRecord:
        prices = row.get("productPriceList") or []
        first_price = prices[0] if prices else {}
        price_value = first_price.get("currencyPrice", first_price.get("productPrice", ""))
        symbol = first_price.get("currencySymbol", "$") if price_value != "" else ""
        images = row.get("productImages") or []
        code = str(row.get("productCode") or "").upper()
        return PartRecord(
            code=code,
            product_id=str(row.get("productId") or ""),
            model=str(row.get("productModel") or ""),
            manufacturer=str(row.get("brandNameEn") or ""),
            package=str(row.get("encapStandard") or ""),
            category=str(row.get("catalogName") or row.get("wmCatalogNameEn") or ""),
            description=str(row.get("productNameEn") or row.get("productIntroEn") or ""),
            stock=CatalogClient._integer(row.get("stockNumber")),
            price=f"{symbol}{price_value}" if price_value != "" else "",
            image_url=str(row.get("productImageUrlBig") or (images[0] if images else "")),
            datasheet_url=str(row.get("pdfUrl") or ""),
            product_url=str(row.get("url") or f"https://www.lcsc.com/product-detail/{code}.html"),
            sources=("lcsc",),
        )

    def _sz_detail(self, product_id: str) -> PartRecord:
        try:
            response = self.session.get(f"{SZ_ITEM}/{product_id}.html", timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CatalogError(f"SZLCSC detail request failed: {exc}") from exc
        match = re.search(
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', response.text, re.S
        )
        if not match:
            raise CatalogError("SZLCSC blocked or changed its product page format.")
        try:
            props = json.loads(match.group(1))["props"]["pageProps"]
            row = props["webData"]["productRecord"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogError("SZLCSC product data was incomplete.") from exc
        image_list = str(row.get("luceneBreviaryImageUrls") or "").split("<$>")
        file_lists = row.get("fileTypeVOList") or []
        datasheet = ""
        for group in file_lists:
            if group.get("fileType") == "pdf_property" and group.get("detailVOList"):
                datasheet = self._absolute_sz(group["detailVOList"][0].get("fileUrl", ""))
                break
        price = props.get("price")
        attrs = (
            ("Product", str(row.get("productName") or "")),
            ("Arrangement", str(row.get("productArrange") or "")),
            ("Minimum order", str(row.get("minBuyNumber") or "")),
        )
        return PartRecord(
            code=str(row.get("productCode") or "").upper(),
            product_id=str(row.get("productId") or product_id),
            model=str(row.get("productModel") or ""),
            manufacturer=str(row.get("productGradePlateName") or ""),
            package=str(row.get("encapsulationModel") or ""),
            category=str(row.get("productType") or ""),
            description=str(row.get("productName") or row.get("remark") or ""),
            stock=self._integer(row.get("stockNumber")),
            price=f"¥{price}" if price not in (None, "") else "",
            image_url=image_list[0] if image_list and image_list[0] else "",
            datasheet_url=datasheet,
            product_url=f"{SZ_ITEM}/{product_id}.html",
            sources=("szlcsc",),
            attributes=tuple((key, value) for key, value in attrs if value),
        )

    def _eda_previews(self, code: str) -> PartRecord:
        data = self._request_json("GET", f"{EDA_API}/products/{code.upper()}/svgs")
        rows = data.get("result") or []
        symbols = [str(item.get("svg") or "") for item in rows if item.get("docType") == 2]
        footprint = next(
            (str(item.get("svg") or "") for item in rows if item.get("docType") == 4), ""
        )
        footprint_uuid = next(
            (str(item.get("component_uuid") or "") for item in rows if item.get("docType") == 4),
            "",
        )
        update_time = max(
            (self._integer(item.get("updateTime")) or 0 for item in rows), default=0
        )
        has_3d_model = False
        if footprint_uuid:
            try:
                component = self._request_json(
                    "GET", f"{EDA_API}/components/{footprint_uuid}"
                ).get("result") or {}
                has_3d_model = "outline3D" in json.dumps(
                    component.get("dataStr") or {}, ensure_ascii=False
                )
            except CatalogError:
                has_3d_model = False
        return PartRecord(
            code=code.upper(),
            symbol_svg="\n".join(symbols),
            footprint_svg=footprint,
            has_3d_model=has_3d_model,
            eda_update_time=update_time,
        )

    @staticmethod
    def _absolute(value: str) -> str:
        return f"https:{value}" if value.startswith("//") else value

    @staticmethod
    def _absolute_sz(value: str) -> str:
        if value.startswith("/"):
            return f"https://alimg.szlcsc.com{value}"
        return value

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
