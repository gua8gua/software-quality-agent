import { useEffect, useState } from "react";
import { Button } from "antd";
import { ArrowUpRight } from "lucide-react";
import { navigate } from "../../navigation";
import { part } from "../api";
import type { resultsApi } from "./api";
import { Busy, ErrorNotice, useRead } from "./shared";

export function NodeReader({access, node, project}: {access: ReturnType<typeof resultsApi>; node: string; project: string}) {
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [node]);
  const result = useRead(signal => access.node(node, offset, signal), [access, node, offset]);
  const data = result.data;
  return <div className="node-reader"><ErrorNotice error={result.error} />{result.loading ? <Busy /> : data && <>
    <div className="node-path">{data.heading_path.join(" / ") || "文档根级"}</div><code className="node-id" title={node}>{node}</code>
    <div className="node-body">{data.text || "此节点无独立正文"}</div>
    <div className="node-provenance">{data.node_type} · 原始页：{[...new Set(data.provenance.map(p => p.page_no).filter(p => p !== undefined))].join("、") || "Docling 未提供页码"}</div>
    {(offset > 0 || data.has_more_text) && <div className="reader-pages"><Button size="small" disabled={offset === 0} onClick={() => setOffset(v => Math.max(0, v - 8000))}>上一段</Button><span>{offset + 1}–{offset + data.text.length} / {data.text_total_chars} 字符</span><Button size="small" disabled={!data.has_more_text} onClick={() => setOffset(v => v + 8000)}>继续读取</Button></div>}
    <Button type="link" size="small" icon={<ArrowUpRight size={13} />} onClick={() => navigate(`/projects/${part(project)}/files/${part(data.artifact_id)}`)}>打开原始文件</Button>
  </>}</div>;
}
