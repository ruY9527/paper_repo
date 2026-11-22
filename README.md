# PaperFlow 2026 — 顶会顶刊论文精读库

<div align="center">

**自动化论文采集 · AI 精读解析 · 知识聚合 · 博客发布**

[在线站点](https://ruy9527.github.io/paper_repo/) · [GitHub 仓库](https://github.com/ruY9527/paper_repo)

</div>

---

## 这个仓库是做什么的？

这是 **PaperFlow 2026** 项目的公开博客仓库，由本地流水线自动生成与维护。它把“论文从哪来、读出了什么、怎么找得到”整理成一个可持续更新的知识站，主要包含：

- **每日论文追踪**：自动采集 CVPR / ECCV / ICCV / NeurIPS / ICLR / AAAI / TPAMI / TIP / IJCV 等顶会顶刊的最新论文，按兴趣画像做 S/A/B 分级。
- **精读笔记**：为 S 级论文下载 PDF、抽取架构图，并由 AI 按 13 个环节（研究问题、方法直觉、数学推导、实验设计、局限与复现等）生成深度笔记。
- **聚合视图**：首页看板、各 Venue 年度总表、跨论文能力对照、开源代码精选、周报与按研究方向的专题页。
- **网站导航**：个人常用的科研 / AI / 工具网址收藏，公开部分自动生成导航页。
- **自动发布**：以上页面由本地工具链（`paperflow publish` / `paperflow site-sync`）幂等生成并通过 GitHub Pages 呈现。

本仓库由程序自动生成提交，请勿在 GitHub 网页端直接手工编辑生成目录下的文件，以免下次同步被覆盖；需要调整内容请修改本地流水线与其配置。

---

## 目录结构

```text
docs/
  index.md                 首页看板与总览
  papers/<年份>/<Venue>/    单篇论文精读笔记（按年份与会议/期刊归档）
  venues/                   9 大顶会顶刊年度总表
  matrix/                   跨论文能力对照、开源代码精选
  weekly/                   周报
  topics/                   按研究方向聚合的专题页
  sites/                    网站导航页（仅公开收藏）
  assets/<paper_uid>/       论文架构图（WebP）
mkdocs.yml                  MkDocs-Material 站点配置
```

---

## 内容声明：由 AI 生成，请审慎甄别

> **本站的论文解读、摘要速览、能力对照、网站点评等正文内容，主要由人工智能（AI）自动整理生成**，用于个人学习、快速检索与知识沉淀。
>
> AI 输出可能存在**事实偏差、理解误差、指标误读或信息滞后**。涉及关键结论、实验数字、公式推导与学术观点时，请务必：
>
> 1. 以**论文原文 / 官方出处**为准；
> 2. 核对原始 PDF、arXiv 页面或项目主页；
> 3. 自行判断信息的准确性与适用性。
>
> 本站内容不构成任何学术结论或投资 / 决策建议。若发现错误，欢迎提 Issue 反馈，以便修正生成规则。

所有由流水线生成的页面底部也带有同样的声明标记（`<!-- AI-GENERATED-NOTICE -->`），便于逐页识别。

---

## 技术栈

Python · Typer · FastAPI · SQLite · httpx · PyMuPDF · MkDocs-Material · Alpine.js · GitHub Pages

生成与管理工具在 PaperFlow 本地项目中运行，本仓库只保存生成后的公开站点内容。
