import type { AssessmentStatus, BatchDetail, Canonical, Visualization } from "./api";
export type BatchReview = BatchDetail["reviews"][number];
export function distribution(reviews: BatchReview[]) {
  const counts: Record<AssessmentStatus, number> = {implemented: 0, uncovered: 0, issues: 0, analysis_error: 0, not_analyzed: 0};
  for (const review of reviews) counts[review.assessment?.status || "not_analyzed"]++;
  return counts;
}
// Read-only rollup, not a new semantic verdict about a section.
export function hierarchyScope(graph: Visualization, reviews: BatchReview[], side: "source" | "target", targetArtifactIds: string[]) {
  const nodes = new Map(graph.nodes.map(node => [node.node_id, node]));
  const byNode = new Map<string, Map<string, BatchReview>>();
  const add = (id: string, review: BatchReview) => {
    const seen = new Set<string>(); let current = nodes.get(id);
    while (current && !seen.has(current.node_id)) {
      seen.add(current.node_id);
      if (!byNode.has(current.node_id)) byNode.set(current.node_id, new Map());
      byNode.get(current.node_id)!.set(review.review_id, review);
      current = nodes.get(current.parent_id || "");
    }
  };
  if (side === "source") for (const review of reviews) add(review.requirement_node_id, review);
  else {
    const source = new Map(reviews.map(review => [review.requirement_node_id, review]));
    const targets = new Set(targetArtifactIds);
    for (const link of graph.links) {
      const review = source.get(link.source_node_id), target = nodes.get(link.target_node_id);
      if (review && target && targets.has(target.artifact_id)) add(link.target_node_id, review);
    }
  }
  const children = new Map<string, Canonical[]>();
  for (const node of graph.nodes) if (byNode.has(node.node_id)) {
    const parent = byNode.has(node.parent_id || "") ? node.parent_id! : "";
    children.set(parent, [...(children.get(parent) || []), node]);
  }
  for (const list of children.values()) list.sort((a, b) => a.reading_order - b.reading_order);
  return {nodes, children, reviews: (id: string) => [...(byNode.get(id)?.values() || [])]};
}
