/// <reference lib="webworker" />
import { projectWorkflow, type JsonRecord, type WorkflowStep } from "./workflowRecords";

let checkpoint: JsonRecord | null = null;
let details = new Map<string, WorkflowStep>();
let latestLoad = 0;
self.onmessage = async (event: MessageEvent) => {
  const {id, action, url, attempt, stepId} = event.data;
  try {
    if (action === "load") {
      latestLoad = id;
      const response = await fetch(url, {cache: "no-store"});
      if (id !== latestLoad) throw new Error("读取已取消");
      if (response.status === 404) {checkpoint = null; details.clear(); self.postMessage({id, result: null}); return;}
      if (!response.ok) throw new Error(`读取工作记录失败（HTTP ${response.status}）`);
      const next = await response.json();
      if (id !== latestLoad) throw new Error("读取已取消");
      checkpoint = next;
    }
    if (action === "detail") {self.postMessage({id, result: details.get(stepId) || null}); return;}
    if (!checkpoint) throw new Error("尚未读取运行记录");
    const projection = projectWorkflow(checkpoint, attempt);
    details = projection.details;
    self.postMessage({id, result: projection.view});
  } catch (error) {self.postMessage({id, error: error instanceof Error ? error.message : String(error)});}
};
