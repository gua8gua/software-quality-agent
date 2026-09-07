import { useEffect, useState, type FormEvent } from "react";
import { type Artifact, type Dataset, type Project, type Run, get, post, errorText, runDisplayStatus, statusLabel } from "./api";
import { Alert, Loading, Modal } from "./common";
import { AnalysisDialog as ManualAnalysis } from "./Dialogs";

export interface Layer { id: string; label: string; artifact_ids: string[]; count: number }
interface LayerInventory { layers: Layer[]; default_pairs: string[][]; excluded_ids: string[]; default_policy: string }
const modes = [ ["auto", "按类型自动选择"], ["artifact", "整份制品（None）"], ["chunk", "定长块（Chunk）"], ["sentence", "句子（自然语言）"], ["sections", "章节 / 段落"], ["method", "方法（Java / Python）"], ["class", "类（Java / Python）"], ["model_features", "模型特征（组件 JSON）"], ["llm_structure", "LLM 文档结构抽取（扩展）"]];

export function LayerAnalysis({tenant,project,dataset,artifacts,kinds,close,created}: {tenant:string;project:Project;dataset:Dataset;artifacts:Artifact[];kinds:Map<string,string>;close:()=>void;created:(runs:Run[])=>void}) {
  const [inventory,setInventory]=useState<LayerInventory|null>(null), [pairs,setPairs]=useState<string[]>([]);
  const [error,setError]=useState(""),[busy,setBusy]=useState(false),[manual,setManual]=useState(false);
  const [codeLanguage,setCodeLanguage]=useState("auto"),[topK,setTopK]=useState(3),[chunkSize,setChunkSize]=useState(2000),[overrides,setOverrides]=useState<Record<string,string>>({});
  useEffect(()=>{let active=true;get<LayerInventory>(`/datasets/${dataset.id}/layers`,tenant,project.id).then(data=>{if(active){setInventory(data);setPairs(data.default_pairs.map(p=>p.join("|")));}}).catch(e=>{if(active)setError(errorText(e));});return()=>{active=false};},[dataset.id,tenant,project.id]);
  if(manual) return <ManualAnalysis tenant={tenant} project={project} dataset={dataset} artifacts={artifacts.filter(a=>a.structure?.content_status!=="reference_only" && a.kind!=="package")} kinds={kinds} close={close} created={r=>created([r])}/>;
  function toggle(key:string){setPairs(old=>old.includes(key)?old.filter(p=>p!==key):[...old,key]);}
  async function submit(event:FormEvent){event.preventDefault();setBusy(true);setError("");try{const result=await post<{runs:Run[]}>("/plans",tenant,project.id,{tenant_id:tenant,project_id:project.id,dataset_id:dataset.id,pairs:pairs.map(p=>{const [source,target]=p.split("|");return{source,target}}),options:{source_preprocessor:"auto",target_preprocessor:"auto",kind_preprocessors:overrides,code_language:codeLanguage,top_k:topK,chunk_size:chunkSize,retrieval_backend:"python"}});created(result.runs);}catch(e){setError(errorText(e));}finally{setBusy(false);}}
  return <Modal title="选择 TLR 层间比较" wide close={()=>!busy&&close()}><form onSubmit={submit}>
    <p><strong>{project.name}</strong> / {dataset.version}</p><p className="qm-muted">行是源层，列是目标层；可多选方向。默认连接有正文的相邻非空层，空层跳过；层次顺序是本项目的工作流约定，不代表金标准。</p>
    {error&&<Alert>{error}</Alert>}{!inventory?<Loading/>:<>
      <div className="qm-toolbar"><button type="button" onClick={()=>setPairs(inventory.default_pairs.map(p=>p.join("|")))}>恢复相邻层默认</button><button type="button" onClick={()=>setPairs([])}>清空选择</button><button type="button" onClick={()=>setManual(true)}>手工选择源与目标制品</button></div>
      <div className="qm-table-wrap qm-layer-selection"><table><thead><tr><th>源 ↓ / 目标 →</th>{inventory.layers.map(l=><th key={l.id}>{l.label}<small>{l.count} 份正文</small></th>)}</tr></thead><tbody>{inventory.layers.map(s=><tr key={s.id}><th>{s.label}<small>{s.count} 份正文</small></th>{inventory.layers.map(t=><td key={t.id}><input type="checkbox" aria-label={s.label+" → "+t.label} disabled={busy||s.id===t.id||!s.count||!t.count} checked={pairs.includes(s.id+"|"+t.id)} onChange={()=>toggle(s.id+"|"+t.id)}/></td>)}</tr>)}</tbody></table></div>
      <p className="qm-muted">{inventory.excluded_ids.length} 个包或仅有引用的节点已排除。每个单元格产生独立运行，保留分割配置、候选与最终链接；当前页面依次执行，关闭页面会中断后续排队，已创建的待执行运行仍可从历史进入继续。</p>
      <details className="qm-run-info"><summary>按制品类型配置分割粒度</summary><label>代码语言（如源码以 .txt 保存，可手工指定）<select value={codeLanguage} onChange={e=>setCodeLanguage(e.target.value)}><option value="auto">使用制品元数据或文件扩展名</option><option value="java">Java</option><option value="python">Python</option></select></label><div className="qm-form-grid">{[...new Set(artifacts.filter(a=>a.structure?.content_status!=="reference_only"&&a.kind!=="package").map(a=>a.kind))].map(kind=><label key={kind}>{kinds.get(kind)||kind}<select aria-label={(kinds.get(kind)||kind)+" 分割策略"} value={overrides[kind]||"auto"} onChange={e=>setOverrides(old=>({...old,[kind]:e.target.value}))}>{modes.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>)}</div><p>自动：Java/Python 代码按方法，其它代码按块；需求与自然语言按句；测试用例保持完整；设计按章节；组件模型 JSON 提取特征。自动代码策略在语法错误或单元超长时使用 Chunk 并记录降级；手工选择 Method/Class 保持严格。LLM 文档抽取需显式选择，抽取引文必须来自原文。</p></details>
      <div className="qm-form-grid"><label>每个源单元的候选数（Top-k）<input type="number" min={1} max={100} required value={topK} onChange={e=>setTopK(Number(e.target.value))}/></label><label>Chunk 字符数<input type="number" min={100} max={20000} required value={chunkSize} onChange={e=>setChunkSize(Number(e.target.value))}/></label></div>
      <footer><span>已选 {pairs.length} 个层间任务</span><button type="button" onClick={close} disabled={busy}>取消</button><button className="qm-primary" disabled={busy||!pairs.length}>{busy?"创建任务…":"创建并依次检测"}</button></footer>
    </>}
  </form></Modal>;
}

const resumableRun = (run: Run) => run.status === "pending" || (
  (run.status === "failed" || (run.status === "completed" && run.stage === "completed_with_errors")) &&
  (run.counts.candidates || 0) > (run.counts.classified || 0)
);

export function LayerRunMatrix({runs,project,datasetId,resume,fixedPlanId,currentRunId}:{runs:Run[];project:string;datasetId:string;resume:(runs:Run[])=>void;fixedPlanId?:string;currentRunId?:string}){
  const available=runs.filter(r=>r.dataset_id===datasetId&&r.config.plan_id);
  const ids=[...new Set(available.map(r=>r.config.plan_id!))];
  const [selected,setSelected]=useState("");const current=fixedPlanId&&ids.includes(fixedPlanId)?fixedPlanId:ids.includes(selected)?selected:ids[0];
  const rows=available.filter(r=>r.config.plan_id===current);
  const resumable=rows.filter(resumableRun);
  const label=rows[0]?.config.batch_label||`批次 ${current?.slice(0,8)||""}`;
  const names:Record<string,string>={context:"背景/风险",requirements:"需求",architecture:"架构/接口",design:"设计",implementation:"代码",verification:"测试",assurance:"评审/其它",operation:"发布/运维"};
  const layers=Object.keys(names).filter(k=>rows.some(r=>r.config.layer_pair?.includes(k)));
  if(!rows.length)return null;
  return <section className="qm-inset"><div className="qm-toolbar"><h3>{label} · {rows.length} 个任务</h3>{!fixedPlanId&&<select aria-label="选择比较批次" value={current} onChange={e=>setSelected(e.target.value)}>{ids.map(id=>{const row=available.find(run=>run.config.plan_id===id);return <option key={id} value={id}>{row?.config.batch_label||`批次 ${id.slice(0,8)}`}</option>})}</select>}<button className="qm-primary" disabled={!resumable.length} onClick={()=>resume(resumable)}>恢复整个批次（{resumable.length}）</button></div><div className="qm-table-wrap"><table><thead><tr><th>源 ↓ / 目标 →</th>{layers.map(l=><th key={l}>{names[l]}</th>)}</tr></thead><tbody>{layers.map(s=><tr key={s}><th>{names[s]}</th>{layers.map(t=>{const r=rows.find(r=>r.config.layer_pair?.[0]===s&&r.config.layer_pair?.[1]===t);if(!r)return <td key={t}>—</td>;const display=runDisplayStatus(r);return <td key={t} className={r.id===currentRunId?"current":""}><a href={"#/projects/"+encodeURIComponent(project)+"/runs/"+r.id}><span className={"qm-badge "+display}>{statusLabel[display]}</span><small>{r.status==="completed"?(r.counts.links||0)+" 条链接":r.status==="pending"?"等待执行":r.status==="running"?"正在执行":"可从断点恢复"}</small></a></td>})}</tr>)}</tbody></table></div></section>
}
