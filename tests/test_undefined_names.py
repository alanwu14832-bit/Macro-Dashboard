"""靜態檢查：函式裡有沒有讀到從來沒有被綁定的名字。

2026-09-14 的總覽改版刪掉了 `_related_reading()`，卻留下一行
`... if reading else ""`。Python 不會在匯入時抱怨，測試也全綠——
它只在建置真的走到那一行時炸開 NameError，結果整站的自動更新停了一天多，
而首頁看起來完全正常（它只是停在前一天）。

CI 的順序是「先跑測試、再建置」，所以這種錯要在這裡擋下來，不能等建置。
沒有第三方套件可用（見 CLAUDE.md 的硬約束一），所以用標準庫的 ast 走一遍：
對每個函式收集「被綁定的名字」與「被讀取的名字」，相減。
"""
from __future__ import annotations

import ast
import builtins
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGES = ["macro", "tools"]
EXTRA_FILES = ["build.py"]
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def _python_files() -> list[str]:
    found = [os.path.join(ROOT, name) for name in EXTRA_FILES]
    for package in PACKAGES:
        for folder, _dirs, files in os.walk(os.path.join(ROOT, package)):
            if "__pycache__" in folder:
                continue
            found += [os.path.join(folder, f) for f in files if f.endswith(".py")]
    return sorted(p for p in found if os.path.exists(p))


class _Scope:
    """一個函式的名字帳本。巢狀函式與推導式沿用外層可見的綁定。"""

    def __init__(self, parent: set[str]):
        self.visible = set(parent)
        self.read: list[tuple[str, int]] = []


class _Checker(ast.NodeVisitor):
    def __init__(self, module: ast.Module):
        self.problems: list[tuple[str, int]] = []
        self.module_names = BUILTINS | self._module_level(module)
        self.stack: list[_Scope] = []

    @staticmethod
    def _module_level(module: ast.Module) -> set[str]:
        """模組層級的所有綁定：import、賦值、def、class。

        走整棵樹而不是只走頂層，因為函式裡的 `global X` 與 `import` 也會
        讓名字在該模組可見；寧可寬鬆也不要誤報——這個檢查的價值在於
        零誤報，一有誤報就會被關掉。
        """
        names: set[str] = set()
        for node in ast.walk(module):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.Global):
                names.update(node.names)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
        return names

    # ---- 綁定 ----
    def _bind_target(self, node) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                self.stack[-1].visible.add(child.id)

    def _bind_arguments(self, args: ast.arguments) -> None:
        every = (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
                 + [a for a in (args.vararg, args.kwarg) if a])
        for arg in every:
            self.stack[-1].visible.add(arg.arg)

    # ---- 走訪 ----
    def visit_FunctionDef(self, node) -> None:
        self._enter_function(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _enter_function(self, node) -> None:
        # 預設值與裝飾器是在外層求值的
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(default)
        for decorator in node.decorator_list:
            self.visit(decorator)

        parent = self.stack[-1].visible if self.stack else self.module_names
        self.stack.append(_Scope(parent))
        self._bind_arguments(node.args)
        # 先收齊這個函式裡所有會被綁定的名字，再檢查讀取——Python 的
        # 區域變數在整個函式內都是區域的，不分行號先後。
        for child in ast.walk(node):
            if child is node:
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                self.stack[-1].visible.add(child.id)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef)):
                self.stack[-1].visible.add(child.name)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    self.stack[-1].visible.add(alias.asname
                                               or alias.name.split(".")[0])
            elif isinstance(child, ast.ExceptHandler) and child.name:
                self.stack[-1].visible.add(child.name)
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                self.stack[-1].visible.update(child.names)
            elif isinstance(child, ast.Lambda):
                # lambda 的參數併進外層帳本，而不是給它自己的作用域。
                # 這會放過「同名變數在 lambda 外也被誤用」那種情況，但
                # 這個檢查只有在零誤報時才留得下來——誤報一次就會被關掉，
                # 而它要擋的是刪掉賦值卻留下用法，不是名字遮蔽。
                self._bind_arguments(child.args)

        for statement in node.body:
            self.visit(statement)

        scope = self.stack.pop()
        for name, line in scope.read:
            if name not in scope.visible:
                self.problems.append((name, line))

    def visit_ClassDef(self, node) -> None:
        if self.stack:
            self.stack[-1].visible.add(node.name)
        self.generic_visit(node)

    def visit_Name(self, node) -> None:
        if self.stack and isinstance(node.ctx, ast.Load):
            self.stack[-1].read.append((node.id, node.lineno))


class NoUndefinedNames(unittest.TestCase):
    def test_every_function_only_reads_names_it_can_see(self):
        failures = []
        for path in _python_files():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            checker = _Checker(tree)
            checker.visit(tree)
            for name, line in checker.problems:
                failures.append(f"{os.path.relpath(path, ROOT)}:{line} "
                                f"讀取了從未綁定的名字 {name!r}")
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_the_checker_catches_the_bug_that_motivated_it(self):
        """刪掉 `reading = ...` 卻留下 `if reading` 的那一種。"""
        source = ("def brief(items):\n"
                  "    out = []\n"
                  "    for title in items:\n"
                  "        out.append(title + ('x' if reading else ''))\n"
                  "    return out\n")
        tree = ast.parse(source)
        checker = _Checker(tree)
        checker.visit(tree)
        self.assertEqual([n for n, _line in checker.problems], ["reading"])

    def test_the_checker_does_not_flag_ordinary_code(self):
        source = ("import os\n"
                  "TOP = 1\n"
                  "def f(a, *rest, b=TOP, **kw):\n"
                  "    total = a + b\n"
                  "    try:\n"
                  "        total += len(rest) + len(kw) + len(os.sep)\n"
                  "    except Exception as exc:\n"
                  "        print(exc)\n"
                  "    inner = [x * total for x in range(3)]\n"
                  "    def nested():\n"
                  "        return inner\n"
                  "    return nested()\n")
        tree = ast.parse(source)
        checker = _Checker(tree)
        checker.visit(tree)
        self.assertEqual(checker.problems, [])


if __name__ == "__main__":
    unittest.main()
