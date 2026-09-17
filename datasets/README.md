# 数据集清单

下载日期：2026-09-05

本目录保留未经本项目修改的上游数据。后续清洗、统一字段和训练切分应写入 `data/` 或 `artifacts/`，不要覆盖这里的原始文件。

## 1. ARTA Requirement Testability

- 目录：`arta-requirement-testability/`
- 来源：[m-zakeri/ARTA](https://github.com/m-zakeri/ARTA)
- 固定提交：`493297655cd653f8ebc797ef5c3c7ee2f736ab4c`
- 许可：仓库附带 MIT License
- 内容：4 组需求数据、smelly words 词典、DS1 的人工/工具评价结果。
- 核心规模：DS1 985 条，DS2 1,092 条，DS3 1,522 条，DS4 1,153 条；词典 1,000 条。
- 主要用途：需求 smell 检测、需求可测试性和规则基线。
- 注意：标签单元格保存命中的词或 `-`，不是统一的 0/1 标签；四个文件的列名也不完全一致，导入前需要字段映射。

`ARTADataset_release1.zip` 是下载原件，`release1/` 是通过路径安全检查后得到的解压副本。

## 2. SAFA / Dronology V0—V1

- 目录：`safa-dronology-v0-v1/`
- 来源：[SAREC-Lab/SAFA-Artifacts](https://github.com/SAREC-Lab/SAFA-Artifacts)
- 固定提交：`ac201a4a7364cf91110c33a9f5b41df9ffbfe709`
- 许可：MIT License
- 内容：两个版本的 hazard、requirement、design definition、source code、acceptance test 和 environmental assumption 追踪树。
- 核心规模：每版 16 棵树；递归出现的节点记录分别为 263 和 382 个。节点会在多棵树中重复，不能用出现次数代替唯一制品数。
- 主要用途：多版本制品图、变更影响和陈旧链接检测。
- 注意：两份 JSON 的顶层 `version` 都为 `001`，文件名 V0/V1 和来源提交必须一并保存，不能只依赖顶层版本字段。

## 3. LiSSA SMOS Requirement-to-Code

- 目录：`lissa-smos-req2code/`
- 来源：[LiSSA ICSE 2025 replication package](https://github.com/ArDoCo/Replication-Package-ICSE25_LiSSA-Toward-Generic-Traceability-Link-Recovery-through-RAG)
- 固定提交：`a8e652f29bbdcc4bdcd3d98cd85aa4a37cb65480`
- 许可：复制包附带 MIT License
- 内容：67 个 use case、100 个 class artifact、1,044 条 requirement-to-code 金标准链接。
- 主要用途：候选追踪召回、链接验证和 TLR 评价。
- 注意：`answer.csv` 没有表头，包含 1,044 行数据；不要用普通带表头 CSV 导入器丢掉第一条链接。XML 文件是本目录的规范聚合输入。

这里只下载 SMOS 的聚合 XML、CSV 金标准、README、许可和引用文件，没有下载 227 MB 的整个复制包，也没有复制重复的逐文件文本。

## 4. Irrelevant Requirements

- 目录：`irrelevant-requirements/`
- 来源：[Figshare 记录 19380545](https://figshare.com/articles/dataset/Irrelevant_Requirements/19380545)
- DOI：[10.6084/m9.figshare.19380545.v1](https://doi.org/10.6084/m9.figshare.19380545.v1)
- 许可：CC BY 4.0
- 内容：14 个项目的 ARFF 文件，共 621 条需求；字段为 `reqs_statement`、`action_part`、`actor_part`、`label`。
- 标签分布：557 条 `relevant`，64 条 `irrelevant`。
- 主要用途：文件/需求与项目范围的相关性检测、主体—动作抽取和类别不平衡评价。

## 完整性

文件来源、记录量、版本、许可和哈希见 [`manifest.json`](manifest.json)。本次已完成：

- ARTA ZIP 路径安全检查与解压验证；
- SAFA JSON 解析验证；
- LiSSA XML 解析与 CSV 行数验证；
- Figshare 14 个文件与上游 MD5 的逐文件核对。

