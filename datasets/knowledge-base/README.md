# 软件质量 Agent 第一版知识库数据

本目录依据 `资料/软件质量部分/论文池/软件质量基础/推荐数据集.md` 整理，并在 2026-09-05 复核来源、版本和可下载性。按用户要求只设四个一级分类；领域数据不另建第五类，SAFA/Dronology 的 UAV/安全数据以 `Project KB` 的第二用途保留。

已有数据集采用复制方式归档，原目录未移动、未删除。下载原件尽量保留，能够安全解压的压缩包同时保留在 `raw/` 中。完整机器清单见 `manifest.json`，可重复下载脚本见 `../../scripts/download_knowledge_base.ps1`。

## 目录与任务覆盖

| 分类 | 当前内容 | 主要用途 |
| --- | --- | --- |
| `Project KB` | SAFA/Dronology、EasyClinic、CM1-NASA Trace、EBT、LiSSA/SMOS、CoDocBench、ArDoCo Architecture Benchmark | 需求—设计—代码—测试追踪、版本变化、架构—代码一致性、文档—代码同步 |
| `Standards KB` | NIST SSDF 1.1、NASA NPR 7150.2D、NASA-STD-8739.8B、ISO/IEEE 元数据目录 | 给出质量判定依据、生命周期要求和安全开发要求 |
| `Defect Cases KB` | Defects4J、需求歧义标注集、Irrelevant Requirements、NASA CM1 代码缺陷度量 | 真实代码缺陷、需求缺陷/反例、缺陷预测 |
| `Quality Rules KB` | NASA 需求检查表、NIST SSDF 表格、ARTA 需求可测试性/Smell 数据 | 形成可执行检查项、规则词典和需求质量基线 |

## 关键数据规模

- `CM1-NASA Trace`：22 个高层需求、53 个低层需求/设计条目、45 条金标准追踪链接。
- `EBT`：40 个需求、50 个 Java 类、25 个测试用例，并含需求—代码与需求—测试链接。
- `LiSSA/SMOS`：67 个源用例、100 个目标代码制品、1,044 条金标准链接。
- `CoDocBench`：4,573 个代码—文档对，来自 200 个 Python 项目；本地划分为 2,300 条训练、2,273 条测试。
- `Requirements Ambiguity`：6,725 条 PURE 派生需求和 1,680 条 User Story，共 8,405 条二分类样本。
- `Irrelevant Requirements`：621 条样本，其中 557 条 relevant、64 条 irrelevant。
- `ARTA`：四个需求数据表分别为 985、1,092、1,522、1,153 条，另有 1,000 词的 smell 词典。
- `Defects4J`：本地保存固定提交的框架及项目元数据；854 个 active bug 的实际 buggy/fixed 工作副本需按实验项目另行 checkout。

## 使用顺序建议

1. 用 `Project KB` 建立 Artifact 与 Trace Link 基线，优先使用已有金标准。
2. 用 `Standards KB` 和 `Quality Rules KB` 为检查结果补充规则 ID、依据、严重度与修复建议。
3. 用 `Defect Cases KB` 做检索增强、少样本示例和独立评测；不要把测试集案例放进训练/RAG 语料。
4. 跨制品冲突评测应在 SAFA、EasyClinic、CM1、EBT 或 ArDoCo 金标准上做受控 mutation，并保留原始制品、变异操作、冲突类型和审核记录。

## 许可和使用边界

- ISO/IEC/IEEE 正文通常受版权和机器学习用途条款限制，因此本目录只保存官方元数据与链接，不保存来源不明的标准全文。版本状态见 `Standards KB/standards-catalog.json`。
- NASA 与 NIST 文件来自官方公开站点；引用或再分发时仍应保留来源、版本和发布日期。
- GitHub/复制包以其中随附许可证为准。ArDoCo 的模型和 gold standard 为 MIT，但外部项目文本、图和代码可能采用各自许可证。
- CoEST 的 EasyClinic、CM1-NASA 和 EBT 下载包未统一附带明确许可证；当前按研究复现资料管理，公开再分发或商业使用前需向数据维护方确认授权。
- Requirements Ambiguity 复制包附 MIT License，但 PURE/User Story 原始语料的再分发边界仍应按上游来源复核。
- NASA CM1 defect metrics 的 Zenodo 包未发现清晰的统一许可声明，只用于研究复现候选数据。

## 尚未伪装成“已补齐”的缺口

- 推荐文档提到的 8,120 条 Requirements Smell 数据未找到可核验、可下载且许可清晰的原始发布件，故没有抓取论文正文或第三方镜像冒充数据集。当前由 ARTA、Requirements Ambiguity 和 Irrelevant Requirements 覆盖需求反例类型。
- “Requirement Inconsistency Dataset”在推荐文档中没有唯一论文、DOI 或仓库标识，无法可靠确定具体数据。ArDoCo/SAFA/CM1/EBT 提供追踪金标准，但不是已标注的冲突对；真正的跨制品冲突标签仍需通过受控 mutation 与人工复核建设。
- PURE 原始全量 SRS 没有重复下载；当前 ambiguity 包已包含 6,725 条 PURE 派生标注。若后续做文档级结构分析，再单独确认 PURE 原始发布许可与下载地址。

## 校验

运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\projects\0_\software-quality-agent\scripts\validate_knowledge_base.ps1
```

校验包括四个一级目录、清单 JSON、资产 SHA-256、ZIP 路径穿越、PDF/Office 文件签名及关键样本数。
