"""
Phase 4 — dummy tool: calculator.

Exists to prove the tool-calling loop end-to-end (per the plan: "define
one dummy tool to prove the loop"), not because a calculator is hard for
an LLM — it's a simple, safe, no-OS-access example every future tool can
be modeled after.

Deliberately NOT `eval()` on the raw string: this walks a parsed AST and
only allows a small, fixed set of arithmetic node types, so nothing but
numbers and +-*/%** can ever run here, no matter what the LLM sends in
`expression`. That's the same spirit as the plan's Security Considerations
rule for OS-touching tools ("fixed functions, fixed safe arguments, never
a generic run_command") applied to this tool's own inputs.
"""

import ast
import operator

from .base import ToolSpec
from .registry import register_tool

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval(node: ast.AST):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        return _BINARY_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression element: {type(node).__name__}")


def calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression and return the result as a string."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
    except Exception as e:
        raise RuntimeError(f"Could not evaluate '{expression}': {e}") from e
    return str(result)


register_tool(
    ToolSpec(
        name="calculator",
        description=(
            "Evaluate a basic arithmetic expression: +, -, *, /, %, ** and "
            "parentheses. Use this for any calculation instead of computing "
            "it yourself, so the user gets an exact result."
        ),
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The arithmetic expression to evaluate, e.g. '(3 + 4) * 2'.",
                }
            },
            "required": ["expression"],
        },
        func=calculate,
    )
)
