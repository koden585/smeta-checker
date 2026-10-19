"""Source-backed claim details for the existing Streamlit inspector."""
from __future__ import annotations

import html
import re


def source_snippet(text, limit=1200):
    """Strip markup before truncation; persisted source text remains untouched."""
    return html.unescape(re.sub(r"<[^>]*>", " ", str(text)))[:limit]


def render_claim_sources(checks, doc):
    import pymupdf
    import streamlit as st
    from pdf_text import bounded_page_dpi

    for check in checks:
        facts = check.get("facts") or []
        if not facts:
            continue
        with st.expander(f"Источники: {check['claim_id']} — {check.get('state', '')}"):
            for fact in facts:
                st.text(source_snippet(fact.get("value", "")))
                st.caption("Source IDs: " + ", ".join(fact.get("source_ids") or []))
                for locator in fact.get("locators") or []:
                    origin = locator.get("origin", "unknown")
                    quality = locator.get("quality", "unknown")
                    st.caption(f"Источник: {origin}; качество: {quality}; "
                               f"поворот OCR: {locator.get('rotation', 0)}°")
                    if origin == "ocr":
                        st.caption("Распознанный текст, не native-цитата. "
                                   + "; ".join(locator.get("reasons") or []))
                    bbox, page_number = locator.get("bbox"), locator.get("page")
                    if not doc or not bbox or not isinstance(page_number, int) or not 0 < page_number <= len(doc):
                        st.caption("Координаты источника недоступны.")
                        continue
                    page = doc[page_number - 1]
                    area = pymupdf.Rect(bbox)
                    # Stored locators always use unrotated PDF points.
                    area = area * page.rotation_matrix
                    area = pymupdf.Rect(area.x0 - 8, area.y0 - 8,
                                        area.x1 + 8, area.y1 + 8) & page.rect
                    if area.is_empty or area.is_infinite:
                        st.caption("Координаты источника вне страницы.")
                        continue
                    image = page.get_pixmap(dpi=bounded_page_dpi(page, 250),
                                            clip=area).tobytes("png")
                    st.image(image, caption=f"Стр. {page_number}: {check['claim_id']}",
                             width="stretch")
                    st.text(source_snippet(locator.get("text", "")))
