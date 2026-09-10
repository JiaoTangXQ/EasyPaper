"""Add Latin word boundaries to pdf2zh's character-based paragraph layout.

pdf2zh exposes no line-breaking hook. Adapt the two overflow checks in memory,
without changing installed files or copying its translation/formula renderer.
The adapter checks the function structure and fails on an incompatible update.
"""

from __future__ import annotations

import ast
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
    namespace = {**receive_layout.__globals__, "_ep_wrap_word": wrap_before_word}
    exec(compile(tree, inspect.getsourcefile(receive_layout) or "<pdf2zh-word-layout>", "exec"), namespace)
    return namespace[receive_layout.__name__]
