from __future__ import annotations

from dataclasses import dataclass
import heapq
from pathlib import Path
import re


# 第一版只扫描常见源码文件，避免把依赖包、构建产物和二进制文件送给 LLM。
SUPPORTED_EXTENSIONS = {
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".cs",
    ".php",
}

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
    "third_party",
}

KEYWORD_ALIASES = {
    "登录": ("login", "signin", "authenticate", "auth", "token", "session"),
    "认证": ("auth", "authenticate", "credential", "token", "session"),
    "注册": ("register", "signup", "create_user", "account"),
    "报告": ("report", "export", "generate", "download"),
    "导出": ("export", "download", "serialize"),
    "权限": ("permission", "role", "rbac", "authorize"),
    "搜索": ("search", "query", "filter"),
    "通知": ("notification", "notify", "message", "email"),
    "上传": ("upload", "file", "multipart"),
    "数据库": ("database", "db", "repository", "sql", "query"),
}


@dataclass(slots=True)
class CodeFile:
    """源码文件的轻量元数据，不在索引阶段保存完整文件内容。"""

    path: str
    absolute_path: Path
    size_bytes: int


@dataclass(slots=True)
class CodeMatch:
    path: str
    start_line: int
    end_line: int
    snippet: str
    score: int

    @property
    def reference(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


def expand_keywords(statement: str) -> list[str]:
    """从中文需求提取搜索词，并补充常见的英文代码命名。"""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}", statement)
    keywords = {token.lower() for token in tokens if len(token) >= 2}
    for chinese, aliases in KEYWORD_ALIASES.items():
        if chinese in statement:
            keywords.update(aliases)
    return sorted(keywords)


class RepositoryScanner:
    """扫描仓库并只保存源码文件元数据，避免大文件整体进入内存。"""

    def scan(self, repository_path: str) -> list[CodeFile]:
        root = Path(repository_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"代码仓库目录不存在：{repository_path}")

        files: list[CodeFile] = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            try:
                size_bytes = path.stat().st_size
                # 只读取少量内容判断是否为 UTF-8 文本，不加载整个文件。
                with path.open("r", encoding="utf-8", errors="strict") as handle:
                    handle.read(4096)
            except (OSError, UnicodeDecodeError):
                # 非文本文件或无法访问的文件不参与源码检索。
                continue
            files.append(
                CodeFile(
                    path=str(path.relative_to(root)),
                    absolute_path=path,
                    size_bytes=size_bytes,
                )
            )
        return files


class RepositorySearcher:
    """在源码文件中流式检索候选代码片段，不把完整文件读入内存。"""

    def search(
        self,
        files: list[CodeFile],
        keywords: list[str],
        *,
        max_matches: int = 8,
        context_lines: int = 5,
    ) -> list[CodeMatch]:
        if not keywords:
            return []

        matches: list[CodeMatch] = []
        lowered_keywords = [keyword.lower() for keyword in keywords]
        for code_file in files:
            # 第一遍只统计命中行和分数，最多为每个文件保留三个候选行。
            line_candidates: list[tuple[int, int]] = []
            file_score = 0
            try:
                with code_file.absolute_path.open(
                    "r", encoding="utf-8", errors="strict"
                ) as handle:
                    for index, line in enumerate(handle):
                        lowered_line = line.lower()
                        line_score = sum(
                            lowered_line.count(keyword) for keyword in lowered_keywords
                        )
                        if line_score == 0:
                            continue
                        file_score += line_score
                        candidate = (line_score, index)
                        if len(line_candidates) < 3:
                            heapq.heappush(line_candidates, candidate)
                        elif candidate > line_candidates[0]:
                            heapq.heapreplace(line_candidates, candidate)
            except (OSError, UnicodeDecodeError):
                continue

            if not line_candidates:
                continue

            # 第二遍只读取候选行附近的上下文，内存复杂度与文件大小无关。
            target_lines = sorted(index for _, index in line_candidates)
            try:
                snippets = self._read_contexts(
                    code_file, target_lines, context_lines
                )
            except (OSError, UnicodeDecodeError):
                continue

            for line_score, index in line_candidates:
                snippet, start_line = snippets[index]
                matches.append(
                    CodeMatch(
                        path=code_file.path,
                        start_line=start_line,
                        end_line=start_line + len(snippet.splitlines()) - 1,
                        snippet=snippet,
                        score=file_score + line_score,
                    )
                )

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:max_matches]

    def _read_contexts(
        self,
        code_file: CodeFile,
        target_lines: list[int],
        context_lines: int,
    ) -> dict[int, tuple[str, int]]:
        """按行读取少量上下文，避免使用 read_text() 和 splitlines()。"""
        ranges = {
            target: (
                max(0, target - context_lines),
                target + context_lines,
            )
            for target in target_lines
        }
        collected = {target: [] for target in target_lines}
        line_number = 0
        with code_file.absolute_path.open(
            "r", encoding="utf-8", errors="strict"
        ) as handle:
            for line_number, line in enumerate(handle):
                for target, (start, end) in ranges.items():
                    if start <= line_number <= end:
                        collected[target].append(line.rstrip("\n"))

        return {
            target: (
                "\n".join(lines),
                ranges[target][0] + 1,
            )
            for target, lines in collected.items()
        }
