"""Check that generated answers and troubleshooting paths have usable supporting
evidence.

Citations must refer to the supplied manual, and a diagnostic branch must lead to
an existing step. Invalid proposals are retained as rejected rather than patched
into plausible instructions. These checks do not certify a repair's safety."""

from workbench.manual_analysis.check_source_quotations import anchored


def cite(record, sources):
    """Attach actual pages to citations, refusing unsupported source quotations.

    Args:
        record: JSON-compatible FAQ, tree, node or branch; traversed recursively.
        sources: Source records from the supplied batch, keyed by original item ID.
    Returns:
        Copied structure with page fields on citations. Raises ValueError for an
        unmatched citation; never modifies manufacturer text or the input record.
    """
    if isinstance(record, list):
        return [cite(item, sources) for item in record]
    if not isinstance(record, dict):
        return record
    result = {key: cite(value, sources) for key, value in record.items()}
    if "evidence_id" in record and "quote" in record:
        if not anchored(record["evidence_id"], record["quote"], sources):
            raise ValueError("A guidance quotation does not match its supplied source")
        result["page"] = sources[record["evidence_id"]]["page"]
    return result


def check_tree(tree):
    """Require an acyclic, reachable diagnostic path with explicit terminal nodes.

    Args:
        tree: Validated-schema tree dictionary with root and named nodes.
    Returns:
        None for a well-formed tree; raises ValueError for duplicate IDs, dangling
        branches, cycles, unreachable nodes, or terminal nodes that continue.
    """
    nodes = {node["id"]: node for node in tree["nodes"]}
    if len(nodes) != len(tree["nodes"]) or tree["root"] not in nodes:
        raise ValueError("Tree root or node identifiers are invalid")
    visiting, visited = set(), set()

    def visit(node_id):
        """Walk one path to detect cycles and ensure every branch has a target.

        Args:
            node_id: Identifier reached from the root or a validated branch.
        Returns:
            None; updates traversal sets and raises ValueError on invalid topology.
        """
        if node_id not in nodes or node_id in visiting:
            raise ValueError("Tree has a dangling branch or a cycle")
        if node_id in visited:
            return
        node = nodes[node_id]
        if node["kind"] != "unresolved" and not node.get("citations"):
            raise ValueError("Diagnostic instructions require source citations")
        if any(not branch.get("citations") for branch in node["branches"]):
            raise ValueError("Diagnostic branch conditions require source citations")
        if (node["kind"] == "check") != bool(node["branches"]):
            raise ValueError(
                "Checks need branches; actions, stops and gaps must terminate"
            )
        visiting.add(node_id)
        for branch in node["branches"]:
            visit(branch["next_node"])
        visiting.remove(node_id)
        visited.add(node_id)

    visit(tree["root"])
    if visited != set(nodes):
        raise ValueError("Tree contains unreachable instructions")
