import { useMemo, useState, useEffect } from "react";
import { all, errorText, request, url, type Artifact, type HierarchyNode } from "./api";
import { HierarchyTree, type TreeItem } from "./HierarchyTree";
import { Alert, Loading } from "./common";
const href=(project:string,id:string)=>"#/projects/"+encodeURIComponent(project)+"/artifacts/"+id;
const title=(a:Artifact)=>a.structure?.title||a.structure?.original_id||a.external_id;

interface OriginalStructure { layer: string; layers: { id: string; label: string; count: number }[]; nodes: HierarchyNode[]; artifact_count: number; unstructured_count: number; warnings: string[]; semantics: string[] }
export function StructureTree({datasetId,tenant,project}:{artifacts:Artifact[];datasetId:string;tenant:string;project:string}){
  const [data,setData]=useState<OriginalStructure|null>(null),[layer,setLayer]=useState("requirements"),[error,setError]=useState(""),[loading,setLoading]=useState(true);
  useEffect(()=>{let active=true;setData(null);setError("");setLoading(true);
    if(!datasetId){setLoading(false);return;}
    request<OriginalStructure>(url(`/datasets/${datasetId}/original-structure`,tenant,project)+`&layer=${encodeURIComponent(layer)}`)
      .then(value=>{if(active)setData(value)}).catch(e=>{if(active)setError(errorText(e))}).finally(()=>{if(active)setLoading(false)});
    return()=>{active=false};
  },[datasetId,tenant,project,layer]);
  const nodes=useMemo<TreeItem[]>(()=>data?.nodes.map(n=>({id:n.id,parent_id:n.parent_id,title:n.title,type:n.node_type,href:n.artifact_id?href(project,n.artifact_id):undefined,
    note:[n.metadata_json.container?"原始容器":"", n.metadata_json.source==="no_original_parent"?"原数据未提供父子关系":"", Array.isArray(n.metadata_json.omitted_ancestors)&&n.metadata_json.omitted_ancestors.length?"跨层祖先已省略":"",n.metadata_json.content_status==="reference_only"?"仅有引用":""].filter(Boolean).join(" · ")}))||[],[data,project]);
  return <div className="qm-inset"><p className="qm-muted">仅展示所选层的原始层级：优先使用原数据的树路径和全部父节点，其次使用显式导入层级。保留原始容器和多处出现，不使用 TLR 匹配或模型生成关系。</p>
    <label>数据层级<select aria-label="结构关系数据层级" value={layer} onChange={e=>setLayer(e.target.value)}>{(data?.layers||[{id:layer,label:layer,count:0}]).map(l=><option key={l.id} value={l.id}>{l.label} · {l.count} 份工件</option>)}</select></label>
    {error?<Alert>{error}</Alert>:loading?<Loading/>:data&&<><p className="qm-muted">本层 {data.artifact_count} 份工件；{data.unstructured_count} 份未提供原始父子关系。其他业务层的节点不展开，跨层祖先省略处已标注。</p>{data.warnings.map(w=><Alert key={w}>{w}</Alert>)}<HierarchyTree key={datasetId+layer} nodes={nodes} label="原始结构节点" empty="此层没有原始工件" />{data.semantics.length>0&&<details><summary>原始关系语义</summary>{data.semantics.map(s=><p key={s}>{s}</p>)}</details>}</>}
  </div>;
}

export function StructureDetail({artifact,tenant,project}:{artifact:Artifact;tenant:string;project:string}){
  const [lookup,setLookup]=useState(new Map<string,Artifact>()),[error,setError]=useState("");
  useEffect(()=>{let active=true;Promise.resolve().then(async ()=>{
    // Resolve via containing snapshot supplied by detail API, never a different version.
    const datasetId=(artifact as Artifact & {dataset_id?:string}).dataset_id;
    if(!datasetId)return;
    const rows=await all<Artifact>("/datasets/"+datasetId+"/inventory",tenant,project);if(active)setLookup(new Map(rows.map(a=>[a.external_id,a])));
  }).catch(e=>{if(active)setError(errorText(e));});return()=>{active=false};},[artifact.id,tenant,project]);
  const s=artifact.structure;if(!s||!Object.keys(s).length)return <p className="qm-muted">此记录未提供结构元数据。</p>;
  const link=(id:string)=>{const a=lookup.get(id);return a?<a href={href(project,a.id)}>{title(a)}</a>:<code>{id}</code>};
  return <section className="qm-panel qm-inset"><h2>原始结构关系</h2>{error&&<Alert>{error}</Alert>}<p>原始类型：{s.original_type||artifact.kind} · 正文状态：{s.content_status==="reference_only"?"仅有引用，不能当作源码正文":"有正文"}</p><p>原始标识：{s.original_id||artifact.external_id}</p><h3>父节点</h3><ul>{(s.parent_ids||[]).map(id=><li key={id}>{link(id)}</li>)}</ul><h3>数据集原有关系</h3><ul>{(s.relations||[]).map((r,i)=><li key={i}>{r.relation} / {r.source_relation_type} → {link(r.target_id)}</li>)}</ul><details><summary>完整结构元数据与来源</summary><pre className="qm-document">{JSON.stringify(s,null,2)}</pre></details></section>
}
