"""Musiker-Bericht als PDF: die Berichtsseite der Oberfläche in Headless-Chromium rendern und drucken.

Die Seite rendert Notenausschnitte mit alphaTab im Browser; so entsteht im PDF exakt dasselbe Bild wie in der
Vorschau. Benötigt Playwright samt Chromium (`uv sync --extra pdf && uv run playwright install chromium`).
"""

from __future__ import annotations

from .i18n import Msg, msg

READY_SELECTOR = "body[data-report-ready]"
TIMEOUT_MS = 90_000


class PdfError(Exception):
    def __init__(self, message: Msg):
        super().__init__(str(message))
        self.message = message


def render_pdf(url: str, lang: str) -> bytes:
    """Berichtsseite unter `url` laden, warten bis alle Ausschnitte gerendert sind, als A4-PDF zurückgeben."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise PdfError(msg("err_pdf_unavailable")) from None

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except PlaywrightError:
            raise PdfError(msg("err_pdf_unavailable")) from None
        try:
            # Sprache der Seite folgt navigator.language – im frischen Kontext ohne gespeicherte Wahl
            page = browser.new_page(locale=lang, color_scheme="light")
            page.goto(url)
            page.wait_for_selector(READY_SELECTOR, state="attached", timeout=TIMEOUT_MS)
            failed = page.get_attribute("body", "data-report-error")
            if failed:
                raise PdfError(msg("err_pdf_render", error=failed))
            return page.pdf(
                format="A4", print_background=True, prefer_css_page_size=True,
                display_header_footer=True, header_template="<span></span>",
                footer_template='<div style="font-size:8px;width:100%;text-align:right;padding:0 14mm;color:#777">'
                                '<span class="pageNumber"></span> / <span class="totalPages"></span></div>',
            )
        except PlaywrightError as exc:
            raise PdfError(msg("err_pdf_render", error=str(exc).splitlines()[0])) from None
        finally:
            browser.close()
