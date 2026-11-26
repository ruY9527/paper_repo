"""标准 BibTeX 生成器。"""

from __future__ import annotations

import json
import re

from ..db.models import PaperRecord


def _bib_key(paper: PaperRecord) -> str:
    """生成稳定引用 key：第一作者姓 + 年份 + 首个高价值词。"""
    authors = json.loads(paper.authors_json or "[]")
    surname = "paper"
    if authors:
        parts = str(authors[0]).split()
        surname = re.sub(r"[^a-zA-Z]", "", parts[-1]).lower() or "paper"
    first_word = re.sub(r"[^a-zA-Z]", "", paper.title.split()[0]).lower() if paper.title else ""
    return f"{surname}{paper.pub_year}{first_word}"


def _sanitize(text: str) -> str:
    """转义 BibTeX 特殊字符。"""
    return (text or "").replace("\\", "").replace("{", "").replace("}", "").replace("&", r"\&")


def to_bibtex(paper: PaperRecord) -> str:
    """把论文记录转为 BibTeX 条目。"""
    authors = json.loads(paper.authors_json or "[]")
    author_str = " and ".join(_sanitize(a) for a in authors)
    venue = paper.venue.upper()
    is_journal = venue in {"TPAMI", "TIP", "IJCV"}
    key = _bib_key(paper)

    if is_journal:
        lines = [
            f"@article{{{key},",
            f"  title={{{_sanitize(paper.title)}}},",
            f"  author={{{author_str}}},",
            f"  journal={{{_sanitize(venue)}}},",
            f"  year={{{paper.pub_year}}},",
        ]
    else:
        lines = [
            f"@inproceedings{{{key},",
            f"  title={{{_sanitize(paper.title)}}},",
            f"  author={{{author_str}}},",
            f"  booktitle={{{_sanitize(venue)} {paper.pub_year}}},",
            f"  year={{{paper.pub_year}}},",
        ]
    if paper.doi:
        lines.append(f"  doi={{{_sanitize(paper.doi)}}},")
    if paper.arxiv_id:
        lines.append(f"  eprint={{{_sanitize(paper.arxiv_id)}}},")
        lines.append("  archivePrefix={arXiv},")
    if paper.pub_date:
        lines.append(f"  month={{{paper.pub_date}}},")
    lines.append("}")
    return "\n".join(lines)


def git_clone_hint(paper: PaperRecord) -> str:
    if not paper.code_url:
        return ""
    return f"git clone {paper.code_url.rstrip('.git')}.git"
