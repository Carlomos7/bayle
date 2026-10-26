"""The Qt side of the code editor (Components/CodeEditor.qml): `CodeSupport`, a QML type that colours the editor's
document per block (QSyntaxHighlighter), parses it for errors in the background, and does the document edits QML
cannot do without losing undo (indent, replace all). The syntax itself is in code_syntax.py (no Qt)."""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextBlock,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtQml import QmlElement
from PySide6.QtQuick import QQuickTextDocument

from bayle_qt import code_syntax, find
from bayle_qt.jobs import run_async

QML_IMPORT_NAME = "Roundtable.Code"
QML_IMPORT_MAJOR_VERSION = 1

TAB = 4  # spaces per indent step


class BlockHighlighter(QSyntaxHighlighter):
    """Colours one block at a time; the carry-over state of a multi-line string or comment lives in the block, so
    typing re-highlights only the block (and the ones after it while its state changes)."""

    def __init__(self, document: QTextDocument, language: str, colors: dict[str, str]):
        super().__init__(document)
        self.language = language
        self.formats: dict[str, QTextCharFormat] = {}
        self.set_colors(colors, rehighlight=False)

    def set_colors(self, colors: dict[str, str], *, rehighlight: bool = True) -> None:
        self.formats = {}
        for role in code_syntax.ROLES:
            if role in colors:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(colors[role]))
                if role == "header":
                    fmt.setFontWeight(QFont.Weight.DemiBold)
                self.formats[role] = fmt
        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        spans, state = code_syntax.highlight_line(self.language, text, max(self.previousBlockState(), 0))
        self.setCurrentBlockState(state)
        for start, length, role in spans:
            fmt = self.formats.get(role)
            if fmt is not None:
                self.setFormat(start, length, fmt)


@QmlElement
class CodeSupport(QObject):
    """One per editor. QML sets `textDocument` (the TextArea's), `language` and `colors` (role -> colour); calls
    `check(text)` after typing stops and reads `errorLine` / `errorMessage` when `checked` fires."""

    languageChanged = Signal()
    colorsChanged = Signal()
    checked = Signal()
    _done = Signal(int, int, str)  # generation, line, message (from the worker thread)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._qdoc: QQuickTextDocument | None = None
        self._language = ""
        self._colors: dict[str, str] = {}
        self._highlighter: BlockHighlighter | None = None
        self._generation = 0
        self._line = 0
        self._message = ""
        self._done.connect(self._finish)

    # ---- properties
    def _get_doc(self) -> QQuickTextDocument | None:
        return self._qdoc

    def _set_doc(self, qdoc: QQuickTextDocument | None) -> None:
        if qdoc is self._qdoc:
            return
        self._qdoc = qdoc
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None
        self._rebuild()

    def _get_language(self) -> str:
        return self._language

    def _set_language(self, language: str) -> None:
        if language != self._language:
            self._language = language
            self._rebuild()
            self.languageChanged.emit()

    def _get_colors(self) -> dict:
        return self._colors

    def _set_colors(self, colors: dict) -> None:
        self._colors = {k: QColor(v).name() for k, v in colors.items() if isinstance(k, str)}
        if self._highlighter is not None:
            self._highlighter.set_colors(self._colors)
        self.colorsChanged.emit()

    textDocument = Property(QQuickTextDocument, _get_doc, _set_doc)  # noqa: N815
    language = Property(str, _get_language, _set_language, notify=languageChanged)
    colors = Property("QVariantMap", _get_colors, _set_colors, notify=colorsChanged)  # pyright: ignore[reportArgumentType]
    errorLine = Property(int, lambda self: self._line, notify=checked)  # noqa: N815
    errorMessage = Property(str, lambda self: self._message, notify=checked)  # noqa: N815

    def _document(self) -> QTextDocument:
        assert self._qdoc is not None
        doc = self._qdoc.textDocument()
        assert doc is not None
        return doc

    def _rebuild(self) -> None:
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None
        if self._qdoc is not None and self._language in code_syntax.LANGUAGES:
            self._highlighter = BlockHighlighter(self._document(), self._language, self._colors)

    # ---- error check, off the UI thread
    @Slot(str)
    def check(self, text: str) -> None:
        """Parse text in the background; `checked` fires with the first error (errorLine 0 = none)."""
        self._generation += 1
        generation, language = self._generation, self._language
        if language not in ("toml", "json", "ini"):
            self._done.emit(generation, 0, "")
            return

        def work() -> None:
            found = code_syntax.first_error(language, text)
            self._done.emit(generation, found[0] if found else 0, found[1] if found else "")

        run_async(work)

    @Slot(int, int, str)
    def _finish(self, generation: int, line: int, message: str) -> None:
        if generation == self._generation:  # a newer check superseded this one
            self._line, self._message = line, message
            self.checked.emit()

    # ---- lines
    @Slot(int, result=int)
    def lineOfPosition(self, position: int) -> int:  # noqa: N802
        """The 1-based line a character position is on."""
        return self._document().findBlock(max(position, 0)).blockNumber() + 1 if self._qdoc else 1

    @Slot(int, result=int)
    def positionOfLine(self, line: int) -> int:  # noqa: N802
        """The character position where a 1-based line starts (clamped to the document)."""
        if self._qdoc is None:
            return 0
        doc = self._document()
        return doc.findBlockByNumber(min(max(line, 1), doc.blockCount()) - 1).position()

    # ---- edits (through QTextCursor, so the TextArea's undo stack keeps them)
    @Slot(int, int, bool, result="QVariantList")
    def indent(self, start: int, end: int, outdent: bool) -> list[int]:
        """Tab / Shift+Tab: no selection, Tab inserts spaces to the next stop and Shift+Tab removes one step of the
        line's indent; with a selection every line it touches is indented or outdented. Returns the new selection."""
        doc = self._document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        try:
            if start == end:
                block = doc.findBlock(start)
                if not outdent:
                    n = TAB - (start - block.position()) % TAB
                    cur.setPosition(start)
                    cur.insertText(" " * n)
                    return [start + n, start + n]
                removed = self._outdent(cur, block)
                at = max(start - removed, block.position())
                return [at, at]
            first = doc.findBlock(start)
            last = doc.findBlock(end - 1 if end > start else end)
            block = first
            while block.isValid() and block.blockNumber() <= last.blockNumber():
                if outdent:
                    self._outdent(cur, block)
                else:
                    cur.setPosition(block.position())
                    cur.insertText(" " * TAB)
                block = block.next()
            return [first.position(), last.position() + last.length() - 1]
        finally:
            cur.endEditBlock()

    @staticmethod
    def _outdent(cur: QTextCursor, block: QTextBlock) -> int:
        text = block.text()
        n = 0
        while n < min(TAB, len(text)) and text[n] == " ":
            n += 1
        if n == 0 and text.startswith("\t"):
            n = 1
        if n:
            cur.setPosition(block.position())
            cur.setPosition(block.position() + n, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
        return n

    # ---- find and replace (the pure part is find.py)
    @Slot(str, str, bool, result="QVariantList")
    def matchStarts(self, text: str, query: str, matchCase: bool) -> list[int]:  # noqa: N802, N803
        """Where each match of query starts in text."""
        return [s for s, _ in find.find_all(text, query, case=matchCase)]

    @Slot(str, str, bool, result=int)
    def replaceAll(self, query: str, replacement: str, matchCase: bool) -> int:  # noqa: N802, N803
        """Replace every match in the document as ONE undo step; how many were replaced."""
        doc = self._document()
        spans = find.find_all(doc.toPlainText(), query, case=matchCase)
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        for start, end in reversed(spans):  # from the end, so earlier positions stay valid
            cur.setPosition(start)
            cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cur.insertText(replacement)
        cur.endEditBlock()
        return len(spans)

    @Slot(str, result=str)
    def languageFor(self, name: str) -> str:  # noqa: N802
        """The language for a file name (by extension)."""
        return code_syntax.language_for(name)


@QmlElement
class MarkdownSupport(QObject):
    """For Components/MarkdownView.qml: Qt's Markdown parser knows no theme, so after the text is set the links, inline
    code and code blocks of the document are coloured here (`restyle`) from the theme's roles."""

    @Slot(QQuickTextDocument, str, str, str, str)
    def restyle(self, quick_doc: QQuickTextDocument, link: str, code: str, code_bg: str, mono: str) -> None:
        doc = quick_doc.textDocument()
        if doc is None:
            return
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        block = doc.begin()
        while block.isValid():
            fragments = [it.fragment() for it in block]
            in_code = block.blockFormat().hasProperty(QTextFormat.Property.BlockCodeLanguage)
            if in_code:
                cursor.setPosition(block.position())
                bf = QTextBlockFormat()
                bf.setBackground(QColor(code_bg))
                cursor.mergeBlockFormat(bf)
            for frag in fragments:
                fmt = frag.charFormat()
                new = QTextCharFormat()
                if fmt.isAnchor():
                    new.setForeground(QColor(link))
                    new.setFontUnderline(True)
                elif in_code or fmt.fontFixedPitch():
                    new.setForeground(QColor(code))
                    new.setFontFamilies(mono.split(","))
                    if not in_code:
                        new.setBackground(QColor(code_bg))
                else:
                    continue
                cursor.setPosition(frag.position())
                cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(new)
            block = block.next()
        cursor.endEditBlock()
