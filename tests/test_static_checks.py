import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_FILES = ["app.js", "api.js", "employees.js", "functional.js", "portal.js", "fixes.js"]

INLINE_EVENT_RE = re.compile(r'(?<!data-)\bon\w+="')
INLINE_STYLE_RE = re.compile(r'(?<!data-)\bstyle="')
PAGES_LITERAL_RE = re.compile(r"const pages\s*=\s*\{([^}]*)\}")
META_LITERAL_RE = re.compile(r"const meta\s*=\s*\{([^}]*)\}")
PAGES_ASSIGN_RE = re.compile(r"pages\.(\w+)\s*=")
META_ASSIGN_RE = re.compile(r"meta\.(\w+)\s*=")
OBJECT_KEY_RE = re.compile(r"(\w+)\s*:")


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


class NoInlineAttributesTestCase(unittest.TestCase):
    """CSP (script-src/style-src 'self', no unsafe-inline) silently drops inline
    onclick="..."/oninput="..."/style="..." attributes in generated HTML — the browser
    just no-ops the click or ignores the style, with no visible error unless you open
    devtools. Both bugs happened once already (see CHANGELOG 0.2.0) and were invisible
    without clicking through the whole app in a real browser. These checks catch a
    reintroduction without needing a browser at all."""

    def test_no_inline_event_handler_attributes(self):
        for name in JS_FILES:
            matches = INLINE_EVENT_RE.findall(_read(name))
            self.assertEqual(matches, [], f"{name} has inline onclick/oninput/... attribute(s) — blocked by CSP script-src")

    def test_no_inline_style_attributes(self):
        for name in JS_FILES:
            matches = INLINE_STYLE_RE.findall(_read(name))
            self.assertEqual(matches, [], f'{name} has inline style="..." attribute(s) — blocked by CSP style-src')


class PagesMetaConsistencyTestCase(unittest.TestCase):
    """go(page) reads meta[page] to fill the breadcrumb. A page registered without a
    matching meta entry throws mid-navigation, which — because it happens before
    go() dispatches the page:show event — silently breaks the page's own data
    loading too (see CHANGELOG 0.2.0, the Administração page bug)."""

    def test_every_registered_page_has_a_meta_entry(self):
        combined = "\n".join(_read(name) for name in JS_FILES)
        page_keys = set(OBJECT_KEY_RE.findall(PAGES_LITERAL_RE.search(combined).group(1)))
        page_keys |= set(PAGES_ASSIGN_RE.findall(combined))
        meta_keys = set(OBJECT_KEY_RE.findall(META_LITERAL_RE.search(combined).group(1)))
        meta_keys |= set(META_ASSIGN_RE.findall(combined))
        missing = page_keys - meta_keys
        self.assertEqual(missing, set(), f"pages registered without a matching meta entry: {missing}")


if __name__ == "__main__":
    unittest.main()
