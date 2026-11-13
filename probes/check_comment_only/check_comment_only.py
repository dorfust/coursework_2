#!/usr/bin/env python3
"""check_comment_only.py - are a pinned file and a staged file the same program, apart from comments?

Usage (Python 3.10 or newer, standard library only, nothing is written to disk):
    python check_comment_only.py PINNED STAGED [PINNED STAGED ...]
    python check_comment_only.py --pairs-from-folders PINNED_FOLDER STAGED_FOLDER
Paths with backslashes or forward slashes are both accepted. In folder mode only *.py files whose
name exists in both folders are compared.

For every pair the script
  1. reads both files as UTF-8 and parses both with ast (a syntax error is a FAIL, never a traceback);
  2. removes docstrings from both trees (module, class, def; an empty body gets a Pass) and requires
     ast.dump of the two trees to be identical; if not, it names the first differing top-level statement;
  3. compares the token streams of both files after removing COMMENT and NL tokens and the tokens of
     docstring statements (STRING and the NEWLINE that ends the statement);
  4. prints a line-level difflib report: every added or removed line is classified as COMMENT, BLANK,
     DOCSTRING, OTHER-TRAILING-COMMENT or OTHER (information only);
  5. prints size, sha256, final newline and line-ending style of both files (information only).
Verdict per pair: PASS only when the ASTs are equal AND the token streams are equal; otherwise FAIL.
Exit code: 0 when every pair passes, 1 when any pair fails, 2 on a usage error.

PASS means: the two files describe the same program apart from comments and docstring text.
PASS does NOT prove: that the comment texts are true, that the program is correct, or that the file has
no other kind of damage (a changed line ending or a lost final newline is only reported as information
lines; the reader compares them). This script was written without being executed by its author.
"""
import ast
import difflib
import hashlib
import io
import re
import sys
import tokenize
from pathlib import Path

_DOC_HOLDERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_USAGE = ("usage: python check_comment_only.py PINNED STAGED [PINNED STAGED ...]\n"
          "       python check_comment_only.py --pairs-from-folders PINNED_FOLDER STAGED_FOLDER")


def _a(value):
    """Return an ASCII-only string, so that the output never fails on a console."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _path(text):
    return Path(text.replace("\\", "/"))


def _is_doc(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def doc_ranges(tree):
    """Line ranges (first, last) of all docstring statements; call BEFORE strip_docstrings."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, _DOC_HOLDERS) and node.body and _is_doc(node.body[0]):
            stmt = node.body[0]
            found.append((stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno)))
    return found


def strip_docstrings(node):
    """Delete docstring statements in place; an emptied body gets one Pass (same rule on both sides)."""
    if isinstance(node, _DOC_HOLDERS):
        body = node.body
        if body and _is_doc(body[0]):
            del body[0]
            if not body:
                body.append(ast.Pass())
    for child in ast.iter_child_nodes(node):
        strip_docstrings(child)


def _dump(node):
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _describe(node):
    if node is None:
        return "(no statement)"
    name = getattr(node, "name", None)
    label = type(node).__name__ + (" " + name if name else "")
    return "%s at line %s" % (label, getattr(node, "lineno", "?"))


def first_difference(body_a, body_b):
    """Return (index, node_a, node_b) of the first differing statement in two statement lists."""
    for index in range(max(len(body_a), len(body_b))):
        node_a = body_a[index] if index < len(body_a) else None
        node_b = body_b[index] if index < len(body_b) else None
        if node_a is None or node_b is None or _dump(node_a) != _dump(node_b):
            return index, node_a, node_b
    return None


def _inner_location(node_a, node_b):
    """If both statements are the same kind of def/class, describe the first differing inner statement."""
    if (node_a is None or node_b is None or type(node_a) is not type(node_b)
            or getattr(node_a, "name", 1) != getattr(node_b, "name", 2)):
        return None
    body_a = getattr(node_a, "body", None)
    body_b = getattr(node_b, "body", None)
    if not isinstance(body_a, list) or not isinstance(body_b, list):
        return None
    inner = first_difference(body_a, body_b)
    if inner is None:
        return None
    deeper = _inner_location(inner[1], inner[2])
    return deeper if deeper is not None else (inner[1], inner[2])


def token_stream(text, ranges):
    """Tokens without COMMENT, NL and docstring statements; NEWLINE text is normalised."""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        row = tok.start[0]
        if tok.type in (tokenize.COMMENT, tokenize.NL):
            continue
        in_doc = any(first <= row <= last for first, last in ranges)
        if in_doc and tok.type in (tokenize.STRING, tokenize.NEWLINE):
            continue
        out.append((tok.type, "" if tok.type == tokenize.NEWLINE else tok.string, row))
    return out


def first_token_difference(tokens_a, tokens_b):
    for index in range(min(len(tokens_a), len(tokens_b))):
        if tokens_a[index][:2] != tokens_b[index][:2]:
            return index
    if len(tokens_a) != len(tokens_b):
        return min(len(tokens_a), len(tokens_b))
    return None


def _split_lines(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _comment_cut(text, lines):
    """Map line number -> code text of lines that carry a trailing comment (comment removed)."""
    cut = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                line = lines[row - 1] if 0 < row <= len(lines) else ""
                if line[:col].strip():
                    cut[row] = line[:col].rstrip()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return cut


def _kind(line, number, ranges):
    if any(first <= number <= last for first, last in ranges):
        return "DOCSTRING"
    stripped = line.strip()
    if stripped == "":
        return "BLANK"
    if stripped.startswith("#"):
        return "COMMENT"
    return "OTHER"


def _diff_lines(lines_a, lines_b):
    added, removed = [], []
    a_no = b_no = 0
    for index, entry in enumerate(difflib.unified_diff(lines_a, lines_b, lineterm="", n=0)):
        if index < 2 and (entry.startswith("--- ") or entry.startswith("+++ ")):
            continue
        match = _HUNK.match(entry)
        if match:
            a_no, b_no = int(match.group(1)), int(match.group(3))
        elif entry.startswith("-"):
            removed.append((a_no, entry[1:]))
            a_no += 1
        elif entry.startswith("+"):
            added.append((b_no, entry[1:]))
            b_no += 1
    return added, removed


def line_report(text_a, text_b, ranges_a, ranges_b):
    lines_a, lines_b = _split_lines(text_a), _split_lines(text_b)
    cut_a, cut_b = _comment_cut(text_a, lines_a), _comment_cut(text_b, lines_b)
    added, removed = _diff_lines(lines_a, lines_b)
    removed_texts = {text.rstrip() for _, text in removed}
    added_cuts = {cut_b[number] for number, _ in added if number in cut_b}
    counts = {"added": {}, "removed": {}}
    others = []
    for side, items, ranges, cut, mark in (("added", added, ranges_b, cut_b, "+"),
                                           ("removed", removed, ranges_a, cut_a, "-")):
        for number, text in items:
            kind = _kind(text, number, ranges)
            if kind == "OTHER":
                if side == "added" and cut.get(number) in removed_texts:
                    kind = "OTHER-TRAILING-COMMENT"
                elif side == "removed" and text.rstrip() in added_cuts:
                    kind = "OTHER-TRAILING-COMMENT"
                else:
                    others.append((mark, number, text))
            counts[side][kind] = counts[side].get(kind, 0) + 1
    names = ("COMMENT", "BLANK", "DOCSTRING", "OTHER-TRAILING-COMMENT", "OTHER")
    for side, items in (("added", added), ("removed", removed)):
        detail = ", ".join("%s %d" % (name, counts[side].get(name, 0)) for name in names)
        print("LINES: %s %d (%s)" % (side, len(items), detail))
    if others:
        print("  OTHER lines (first 20 of %d; expected only where code was really changed):" % len(others))
        for mark, number, text in others[:20]:
            print("    %s line %d: %s" % (mark, number, _a(text.strip()[:100])))


def ending_info(raw):
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    cr = raw.count(b"\r") - crlf
    if crlf and not lf and not cr:
        style = "CRLF"
    elif lf and not crlf and not cr:
        style = "LF"
    elif not (crlf or lf or cr):
        style = "no line ending"
    else:
        style = "mixed"
    return raw.endswith(b"\n"), style, lf, crlf, cr


def check_pair(pinned_path, staged_path):
    print("=" * 72)
    print("PAIR: pinned=%s staged=%s" % (_a(pinned_path), _a(staged_path)))
    raws, texts, trees, ranges = {}, {}, {}, {}
    for label, path in (("pinned", pinned_path), ("staged", staged_path)):
        try:
            raws[label] = _path(path).read_bytes()
        except OSError as exc:
            print("FAIL: cannot read the %s file: %s" % (label, _a(exc)))
            return False
        final, style, lf, crlf, cr = ending_info(raws[label])
        print("  %s: %d bytes, sha256 %s" % (label, len(raws[label]), hashlib.sha256(raws[label]).hexdigest()))
        print("  %s: final newline: %s; line endings: %s (LF %d, CRLF %d, lone CR %d)"
              % (label, "yes" if final else "NO", style, lf, crlf, cr))
    info_a, info_b = ending_info(raws["pinned"]), ending_info(raws["staged"])
    if info_a[0] != info_b[0]:
        print("  NOTE: the final newline differs between the two files")
    if info_a[1] != info_b[1]:
        print("  NOTE: the line-ending style differs between the two files")
    for label in ("pinned", "staged"):
        try:
            texts[label] = raws[label].decode("utf-8")
        except UnicodeDecodeError as exc:
            print("FAIL: the %s file is not valid UTF-8: %s" % (label, _a(exc)))
            return False
        try:
            trees[label] = ast.parse(texts[label], filename=label)
        except (SyntaxError, ValueError) as exc:
            print("FAIL: the %s file cannot be parsed: %s" % (label, _a(exc)))
            return False
        ranges[label] = doc_ranges(trees[label])
        strip_docstrings(trees[label])
    ast_equal = _dump(trees["pinned"]) == _dump(trees["staged"])
    if ast_equal:
        print("AST: AST-EQUAL (trees identical after removing docstrings)")
    else:
        print("AST: FAIL (trees differ after removing docstrings)")
        found = first_difference(trees["pinned"].body, trees["staged"].body)
        if found is not None:
            index, node_a, node_b = found
            print("  first differing top-level statement: number %d (%s in pinned; %s in staged)"
                  % (index + 1, _describe(node_a), _describe(node_b)))
            inner = _inner_location(node_a, node_b)
            if inner is not None:
                print("  inside it: %s in pinned; %s in staged" % (_describe(inner[0]), _describe(inner[1])))
    tokens_equal = False
    try:
        tokens_a = token_stream(texts["pinned"], ranges["pinned"])
        tokens_b = token_stream(texts["staged"], ranges["staged"])
        spot = first_token_difference(tokens_a, tokens_b)
        if spot is None:
            tokens_equal = True
            print("TOKENS: EQUAL (%d tokens compared)" % len(tokens_a))
        else:
            side_a = tokens_a[spot] if spot < len(tokens_a) else None
            side_b = tokens_b[spot] if spot < len(tokens_b) else None
            show = lambda tok: ("end of file" if tok is None else "%s %s on line %d"
                                % (tokenize.tok_name.get(tok[0], str(tok[0])), _a(repr(tok[1])), tok[2]))
            print("TOKENS: FAIL (first difference at token %d: pinned %s; staged %s)"
                  % (spot + 1, show(side_a), show(side_b)))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        print("TOKENS: FAIL (tokenizer error: %s)" % _a(exc))
    line_report(texts["pinned"], texts["staged"], ranges["pinned"], ranges["staged"])
    passed = ast_equal and tokens_equal
    print("RESULT: %s" % ("PASS" if passed else "FAIL"))
    return passed


def main(argv):
    args = argv[1:]
    if not args:
        print(_USAGE)
        return 2
    if args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    if args[0] == "--pairs-from-folders":
        if len(args) != 3:
            print(_USAGE)
            return 2
        pinned_dir, staged_dir = _path(args[1]), _path(args[2])
        if not pinned_dir.is_dir() or not staged_dir.is_dir():
            print("usage error: both arguments of --pairs-from-folders must be existing folders")
            return 2
        pinned_names = {item.name for item in pinned_dir.glob("*.py")}
        staged_names = {item.name for item in staged_dir.glob("*.py")}
        common = sorted(pinned_names & staged_names)
        for name in sorted(pinned_names ^ staged_names):
            print("INFO: %s exists in only one of the two folders and is not compared" % _a(name))
        if not common:
            print("usage error: no *.py file name exists in both folders")
            return 2
        pairs = [(str(pinned_dir / name), str(staged_dir / name)) for name in common]
    else:
        if len(args) % 2 != 0:
            print(_USAGE)
            return 2
        pairs = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    results = [check_pair(pinned, staged) for pinned, staged in pairs]
    print("=" * 72)
    print("SUMMARY: %d pair(s), %d PASS, %d FAIL" % (len(results), sum(results), len(results) - sum(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
