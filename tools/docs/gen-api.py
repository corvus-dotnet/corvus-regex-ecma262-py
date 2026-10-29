"""Writes docs/api.md, the API reference the documentation site publishes, from the package's typed stub
(python/corvus_regex_ecma262/_native.pyi) and its __init__.py: every public name in the order of __all__, with its
signatures and its docstring. Standard library only.

    python3 tools/docs/gen-api.py           # write docs/api.md
    python3 tools/docs/gen-api.py --check   # fail when docs/api.md is not what the stubs make (CI)
"""

import ast
import pathlib
import re
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PACKAGE = ROOT / "python" / "corvus_regex_ecma262"
OUT = ROOT / "docs" / "api.md"


def read(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def doc_of(node):
    text = ast.get_docstring(node)
    return textwrap.dedent(text).strip() if text else ""


def signature(fn, owner=None):
    args = fn.args
    if owner and args.posonlyargs and args.posonlyargs[0].arg in ("self", "cls"):
        args = ast.arguments(posonlyargs=args.posonlyargs[1:], args=args.args, vararg=args.vararg,
                             kwonlyargs=args.kwonlyargs, kw_defaults=args.kw_defaults, kwarg=args.kwarg,
                             defaults=args.defaults)
    elif owner and args.args and args.args[0].arg in ("self", "cls"):
        args = ast.arguments(posonlyargs=args.posonlyargs, args=args.args[1:], vararg=args.vararg,
                             kwonlyargs=args.kwonlyargs, kw_defaults=args.kw_defaults, kwarg=args.kwarg,
                             defaults=args.defaults)
    returns = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
    name = f"{owner}.{fn.name}" if owner else fn.name
    # ast.unparse writes an annotated default without spaces (flags: str=''); PEP 8 spaces it.
    text = re.sub(r"(:\s[^,=()]+?)=(?!=)", r"\1 = ", ast.unparse(args))
    return f"{name}({text}){returns}"


def is_property(fn):
    return any(isinstance(d, ast.Name) and d.id == "property" for d in fn.decorator_list)


def is_static(fn):
    return any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in fn.decorator_list)


def functions(body):
    """The functions of a body by name, in order: each a list of its definitions (overloads), and its docstring."""
    found = {}
    for node in body:
        if isinstance(node, ast.FunctionDef):
            entry = found.setdefault(node.name, {"defs": [], "doc": ""})
            entry["defs"].append(node)
            entry["doc"] = entry["doc"] or doc_of(node)
    return found


def constants(body):
    """Annotated module-level names, each with the string literal that follows it as its docstring."""
    found = {}
    for n, node in enumerate(body):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            after = body[n + 1] if n + 1 < len(body) else None
            doc = str(after.value.value) if isinstance(after, ast.Expr) and isinstance(after.value, ast.Constant) else ""
            found[node.target.id] = (ast.unparse(node.annotation), doc)
    return found


def code(lines):
    return "```python\n" + "\n".join(lines) + "\n```\n"


def main():
    init = read(PACKAGE / "__init__.py")
    stub = read(PACKAGE / "_native.pyi")
    names = next(ast.literal_eval(n.value) for n in init.body
                 if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "__all__" for t in n.targets))
    funcs = {**functions(stub.body), **functions(init.body)}
    consts = constants(stub.body)
    classes = {n.name: n for n in stub.body if isinstance(n, ast.ClassDef)}

    out = ["# API reference", "",
           "The public names of `corvus_regex_ecma262`, generated from the package's typed stubs by "
           "`tools/docs/gen-api.py`. [Getting started](getting-started.md) shows them at work.", ""]

    out += ["## Functions", ""]
    for name in names:
        if name in funcs:
            out += [f"### {name}", "", code([signature(d) for d in funcs[name]["defs"]]), funcs[name]["doc"], ""]

    out += ["## Constants", "", "| Name | Type | |", "|---|---|---|"]
    for name in names:
        if name in consts:
            kind, doc = consts[name]
            out.append(f"| `{name}` | `{kind}` | {' '.join(doc.split())} |")
    out.append("")

    for name in names:
        cls = classes.get(name)
        if not cls:
            continue
        bases = ", ".join(ast.unparse(b) for b in cls.bases)
        out += [f"## {name}" + (f" ({bases})" if bases else ""), "", doc_of(cls), ""]
        members = functions(cls.body)
        props = [(m, e) for m, e in members.items() if is_property(e["defs"][0])]
        if props:
            out += ["| Property | Type | |", "|---|---|---|"]
            for m, e in props:
                out.append(f"| `{m}` | `{ast.unparse(e['defs'][0].returns)}` | {' '.join(e['doc'].split())} |")
            out.append("")
        for m, e in members.items():
            if is_property(e["defs"][0]) or (m.startswith("__") and m not in ("__init__", "__getitem__")):
                continue
            static = " (static)" if is_static(e["defs"][0]) else ""
            sigs = [signature(d, name).replace(f"{name}.__init__", name) for d in e["defs"]]
            out += [f"### {name}.{m}{static}" if m != "__init__" else f"### {name}(...)", "", code(sigs), e["doc"], ""]
        for node in cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                n = cls.body.index(node)
                after = cls.body[n + 1] if n + 1 < len(cls.body) else None
                doc = str(after.value.value) if isinstance(after, ast.Expr) and isinstance(after.value, ast.Constant) else ""
                out += [f"### {name}.{node.target.id}", "", code([f"{node.target.id}: {ast.unparse(node.annotation)}"]),
                        " ".join(doc.split()), ""]

    text = "\n".join(out).rstrip() + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            sys.exit(f"{OUT.relative_to(ROOT)} is not what the stubs make: run python3 tools/docs/gen-api.py")
        print(f"{OUT.relative_to(ROOT)} is current")
        return
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
