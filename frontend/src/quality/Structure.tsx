import { useMemo, useState, useEffect } from "react";
import { all, errorText, type Artifact } from "./api";
import { Alert, Empty } from "./common";
const href=(project:string,id:string)=>"#/projects/"+encodeURIComponent(project)+"/artifacts/"+id;
const title=(a:Artifact)=>a.structure?.title||a.structure?.original_id||a.external_id;

function Branch({artifact,children,lookup,path,project}:{artifact:Artifact;children:Map<string,Artifact[]>;lookup:Map<string,Artifact>;path:string[];project:string}){
  const [open,setOpen]=useState(false); const descendants=children.get(artifact.external_id)||[];
  if(path.includes(artifact.external_id))return <li>循环引用：<a href={href(project,artifact.id)}>{title(artifact)}</a></li>;
  return <li><div className="qm-structure-node">{descendants.length?<button aria-label={"展开 "+title(artifact)} onClick={()=>setOpen(v=>!v)}>{open?"−":"+"}</button>:<span>·</span>}<a href={href(project,artifact.id)}>{title(artifact)}</a><span className="qm-type">{artifact.structure?.original_type||artifact.kind}</span>{artifact.structure?.content_status==="reference_only"&&<small>仅有引用</small>}{!!descendants.length&&<small>{descendants.length} 个直接关联</small>}</div>{open&&path.length<20&&<ul>{descendants.map(a=><Branch key={a.id} artifact={a} children={children} lookup={lookup} path={[...path,artifact.external_id]} project={project}/>)}</ul>}{open&&path.length>=20&&<small>层级过深，请进入制品详情继续浏览。</small>}</li>
}
export function StructureTree({artifacts,project}:{artifacts:Artifact[];project:string}){
  const [search,setSearch]=useState("");
  const lookup=useMemo(()=>new Map(artifacts.map(a=>[a.external_id,a])),[artifacts]);
  const children=useMemo(()=>{const m=new Map<string,Artifact[]>();for(const a of artifacts)for(const p of a.structure?.parent_ids||[]){const rows=m.get(p)||[];rows.push(a);m.set(p,rows);}return m;},[artifacts]);
  const roots=artifacts.filter(a=>!(a.structure?.parent_ids||[]).some(p=>lookup.has(p)));
  const matches=artifacts.filter(a=>(title(a)+" "+a.external_id).toLowerCase().includes(search.toLowerCase()));
  return <div className="qm-inset"><p className="qm-muted">展示数据集提供的关系树。SAFA 的父子边表示原始追踪关系，不表示文件夹包含，也不等于本次模型生成的 TLR。一个制品可出现在多个父节点下。</p><input aria-label="搜索结构节点" placeholder="搜索节点名称或标识…" value={search} onChange={e=>setSearch(e.target.value)}/>{!artifacts.some(a=>a.structure?.parent_ids?.length)&&<Empty title="该快照没有提供父子关系"><p>仍可查看资料；不会根据相似度伪造目录结构。</p></Empty>}<ul className="qm-structure-tree">{(search?matches.slice(0,100):roots).map(a=><Branch key={a.id} artifact={a} children={children} lookup={lookup} path={[]} project={project}/>)}</ul>{search&&matches.length>100&&<p>搜索只显示前 100 个节点，请缩小关键词。</p>}</div>
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
