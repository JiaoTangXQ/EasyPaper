"""Adapt pdf2zh's word wrapping and allow rendering after document-wide planning.

pdf2zh exposes neither a line-breaking hook nor separate parse/render stages.
Adapt those boundaries in memory without changing installed files or copying
the formula renderer. Check the structure and fail on an incompatible update.
"""

from __future__ import annotations

import ast
import copy
import inspect
import re
import textwrap


def wrap_before_word(text, offset, x, left, right, size, latin):
    if x <= left + 0.1 * size or offset and re.match(r"[A-Za-z0-9]", text[offset - 1]):
        return False
    word = re.match(r"[A-Za-z0-9]+(?:[-'’./][A-Za-z0-9]+)*", text[offset:])
    if not word:
        return False
    width = sum(latin.char_width(ord(c)) for c in word.group()) * size
    return width <= right - left + 0.1 * size and x + width > right + 0.1 * size


def word_wrapping_layout(receive_layout):
    tree = ast.parse(textwrap.dedent(inspect.getsource(receive_layout)))
    overflow = ast.dump(ast.parse("x + adv > x1 + 0.1 * size", mode="eval").body)
    checks = 0
    loops = 0

    class WordWrap(ast.NodeTransformer):
        def visit_Compare(self, node):
            nonlocal checks
            if ast.dump(node) == overflow:
                checks += 1
                return ast.BoolOp(op=ast.Or(), values=[node, ast.Name(id="_ep_word_break", ctx=ast.Load())])
            return self.generic_visit(node)

        def visit_While(self, node):
            nonlocal loops
            node = self.generic_visit(node)
            if ast.unparse(node.test) == "ptr < len(new)":
                loops += 1
                node.body.insert(
                    0,
                    ast.parse(
                        '_ep_word_break = brk and _ep_wrap_word(new, ptr, x, x0, x1, size, self.fontmap["tiro"])'
                    ).body[0],
                )
            return node

    tree = ast.fix_missing_locations(WordWrap().visit(tree))
    if (checks, loops) != (2, 1):
        raise RuntimeError("pdf2zh paragraph layout changed; its word-wrapping adapter needs an update")
    # Keep pdf2zh's parser and renderer, but allow a document to defer rendering
    # until all page-local paragraphs are available. The renderer closes over
    # this layout's formula glyphs and a snapshot of its font resources.
    function = tree.body[0]
    workers = [i for i, node in enumerate(function.body) if isinstance(node, ast.FunctionDef) and node.name == "worker"]
    renderers = [
        i for i, node in enumerate(function.body) if isinstance(node, ast.FunctionDef) and node.name == "raw_string"
    ]
    if len(workers) != 1 or len(renderers) != 1 or workers[0] >= renderers[0]:
        raise RuntimeError("pdf2zh paragraph stages changed; its document-flow adapter needs an update")
    worker_start, render_start = workers[0], renderers[0]
    renderer = ast.parse("def _ep_render(news, self=_ep_freeze_fonts(self)):\n    pass").body[0]
    renderer.body = function.body[render_start:]
    deferred = ast.parse(
        "if getattr(self.translator, '_easypaper_flow', None) is not None:\n"
        "    return self.translator._easypaper_flow.capture(ltpage, sstk, pstk, vlen, var, self, _ep_render)"
    ).body[0]
    function.body = (
        function.body[:worker_start]
        + [renderer, deferred]
        + function.body[worker_start:render_start]
        + ast.parse("return _ep_render(news)").body
    )
    tree = ast.fix_missing_locations(tree)
    namespace = {
        **receive_layout.__globals__,
        "_ep_wrap_word": wrap_before_word,
        "_ep_freeze_fonts": _freeze_fonts,
    }
    exec(compile(tree, inspect.getsourcefile(receive_layout) or "<pdf2zh-word-layout>", "exec"), namespace)
    return namespace[receive_layout.__name__]


def _freeze_fonts(converter):
    frozen = copy.copy(converter)
    frozen.fontmap = getattr(converter, "fontmap", {}).copy()
    frozen.fontid = getattr(converter, "fontid", {}).copy()
    return frozen
