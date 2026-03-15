"""
Diff tools — compare execution artifacts (prompt text and model configuration).
"""
import difflib
import json
from typing import Any, Dict, List, Optional, Type
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class DiffPromptArtifactsInput(BaseModel):
    current_prompt_text: str
    previous_prompt_text: str
    context_lines: int = Field(default=3)


class DiffPromptArtifactsTool(BaseTool):
    name: str = "diff_prompt_artifacts"
    description: str = (
        "Compare current and previous prompt text. Returns a structured diff with: "
        "unified_diff (string), changed_sections (list), addition_count, deletion_count, "
        "change_magnitude (low/medium/high), and a plain-language summary."
    )
    args_schema: Type[BaseModel] = DiffPromptArtifactsInput

    def _run(self, current_prompt_text: str, previous_prompt_text: str, context_lines: int = 3) -> str:
        try:
            current_lines = current_prompt_text.splitlines(keepends=True)
            previous_lines = previous_prompt_text.splitlines(keepends=True)

            unified = list(difflib.unified_diff(
                previous_lines, current_lines,
                fromfile="previous", tofile="current",
                n=context_lines
            ))
            additions = sum(1 for l in unified if l.startswith("+") and not l.startswith("+++"))
            deletions = sum(1 for l in unified if l.startswith("-") and not l.startswith("---"))
            total_lines = max(len(current_lines), 1)

            change_pct = (additions + deletions) / (total_lines * 2)
            magnitude = "high" if change_pct > 0.2 else "medium" if change_pct > 0.05 else "low"

            # Extract changed sections (lines near @@ markers)
            changed_sections = []
            for line in unified:
                if line.startswith("@@"):
                    changed_sections.append(line.strip())

            summary_parts = []
            if additions > 0:
                summary_parts.append(f"{additions} line(s) added")
            if deletions > 0:
                summary_parts.append(f"{deletions} line(s) removed")
            summary = ", ".join(summary_parts) if summary_parts else "No changes detected"

            return json.dumps({
                "unified_diff": "".join(unified),
                "changed_sections": changed_sections,
                "addition_count": additions,
                "deletion_count": deletions,
                "change_magnitude": magnitude,
                "change_percentage": round(change_pct * 100, 2),
                "summary": summary,
                "prompts_identical": current_prompt_text == previous_prompt_text,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "diff_prompt_artifacts"})


class CompareModelChangeInput(BaseModel):
    current_model: str
    previous_model: str
    current_version: Optional[str] = None
    previous_version: Optional[str] = None


class CompareModelChangeTool(BaseTool):
    name: str = "compare_model_change"
    description: str = "Compare current and previous model names/versions. Returns JSON with model_changed flag and description."
    args_schema: Type[BaseModel] = CompareModelChangeInput

    def _run(
        self,
        current_model: str,
        previous_model: str,
        current_version: Optional[str] = None,
        previous_version: Optional[str] = None,
    ) -> str:
        model_changed = current_model != previous_model
        version_changed = current_version != previous_version if (current_version and previous_version) else False
        return json.dumps({
            "model_changed": model_changed,
            "version_changed": version_changed,
            "current_model": current_model,
            "previous_model": previous_model,
            "current_version": current_version,
            "previous_version": previous_version,
            "description": (
                f"Model changed from '{previous_model}' to '{current_model}'"
                if model_changed else "Same model, no model change"
            ),
        })


diff_prompt_artifacts = DiffPromptArtifactsTool()
compare_model_change = CompareModelChangeTool()
