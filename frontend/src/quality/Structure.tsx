import { useMemo, useState, useEffect } from "react";
import { all, errorText, get, type Artifact, type HierarchyNode } from "./api";
import { Alert, Empty } from "./common";
const href=(project:string,id:string)=>"#/projects/"+encodeURIComponent(project)+"/artifacts/"+id;
const title=(a:Artifact)=>a.structure?.title||a.structure?.original_id||a.external_id;

function Branch({node,children,artifacts,project}:{node:HierarchyNode;children:Map<string,HierarchyNode[]>;artifacts:Map<string,Artifact>;project:string}){
  const [open,setOpen]=useState(false), descendants=children.get(node.id)||[], artifact=node.artifact_id?artifacts.get(node.artifact_id):undefined;
  return <li><div className={`qm-structure-node ${node.artifact_id?"":"pure"}`}>{descendants.length?<button aria-label={`${open?"折叠":"展开"} ${node.title}`} onClick={()=>setOpen(v=>!v)}>{open?"−":"+"}</button>:<span>·</span>}{artifact?<a href={href(project,artifact.id)}>{node.title}</a>:<strong>{node.title}</strong>}<span className="qm-type">{node.node_type}</span>{!node.artifact_id&&<small>结构节点</small>}{!!descendants.length&&<small>{descendants.length} 个直接子节点</small>}</div>{open&&<ul>{descendants.map(child=><Branch key={child.id} node={child} children={children} artifacts={artifacts} project={project}/>)}</ul>}</li>
}
export function StructureTree({artifacts,datasetId,tenant,project}:{artifacts:Artifact[];datasetId:string;tenant:string;project:string}){
  const [nodes,setNodes]=useState<HierarchyNode[]>([]),[search,setSearch]=useState(""),[error,setError]=useState("");
  useEffect(()=>{let active=true;if(!datasetId){setNodes([]);return}get<HierarchyNode[]>(`/datasets/${datasetId}/hierarchy`,tenant,project).then(value=>{if(active)setNodes(value)}).catch(e=>{if(active)setError(errorText(e))});return()=>{active=false}},[datasetId,tenant,project]);
  const artifactMap=useMemo(()=>new Map(artifacts.map(a=>[a.id,a])),[artifacts]);
  const nodeMap=useMemo(()=>new Map(nodes.map(node=>[node.id,node])),[nodes]);
  const children=useMemo(()=>{const value=new Map<string,HierarchyNode[]>();for(const node of nodes){if(!node.parent_id)continue;const rows=value.get(node.parent_id)||[];rows.push(node);value.set(node.parent_id,rows)}return value},[nodes]);
  const matches=nodes.filter(node=>`${node.title} ${node.node_key} ${node.node_type}`.toLowerCase().includes(search.toLowerCase()));
  const shown=search?matches.slice(0,100):nodes.filter(node=>!node.parent_id||!nodeMap.has(node.parent_id));
  return <div className="qm-inset"><p className="qm-muted">这里展示数据集持久化的层级。结构节点可以没有正文，也可以关联有正文的 Artifact；只有后者能进入 TLR。</p>{error&&<Alert>{error}</Alert>}<div className="qm-toolbar qm-structure-tools"><input aria-label="搜索结构节点" placeholder="搜索名称、标识或类型…" value={search} onChange={e=>setSearch(e.target.value)}/></div>{!shown.length&&<Empty title="该快照没有层级节点" />}<ul className="qm-structure-tree">{shown.map(node=><Branch key={node.id} node={node} children={children} artifacts={artifactMap} project={project}/>)}</ul>{search&&matches.length>100&&<p>搜索仅显示前 100 个结果。</p>}</div>
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
