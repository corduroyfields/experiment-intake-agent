"""The Opal tools service: three tools on one FastAPI app.

ToolsService adds GET /discovery (the tool menu Opal reads) and one POST endpoint per @tool.
"""

import os
from typing import Optional

from fastapi import FastAPI
from opal_tools_sdk import ToolsService, tool
from pydantic import BaseModel, Field

import github_client

app = FastAPI(title="Experiment Intake Tools")
service = ToolsService(
    app,
    instructions=(
        "Tools for triaging experiment ideas against a team's experiment backlog, "
        "which lives in GitHub Issues. Check the backlog before filing anything new."
    ),
)


@app.get("/")
def health():
    return {"status": "ok", "discovery": "/discovery"}


# ---------- list_experiment_backlog ----------

class ListBacklogParams(BaseModel):
    search_terms: Optional[str] = Field(
        None, description="Keywords to narrow the list. Omit to return all open items."
    )


@tool(
    "list_experiment_backlog",
    "List open experiment tickets in the team backlog so a new idea can be checked for "
    "duplicates or overlap before anything is filed. Returns up to 25 items.",
)
async def list_experiment_backlog(parameters: ListBacklogParams):
    return {"items": github_client.list_open_issues(parameters.search_terms)}


# ---------- create_experiment_ticket ----------

class CreateTicketParams(BaseModel):
    hypothesis: str = Field(..., description='The hypothesis in "changing X will cause Y" form')
    target_page: str = Field(..., description="URL or page name the test runs on")
    primary_metric: str = Field(..., description="The single metric that decides the test")
    rationale: str = Field(..., description="Why this is worth running")
    effort: Optional[str] = Field("medium", description="low, medium, or high. Defaults to medium.")
    inferred_fields: Optional[list[str]] = Field(
        None, description="Names of fields the agent inferred rather than received"
    )


def _render_body(p: CreateTicketParams) -> str:
    sections = [
        ("Hypothesis", p.hypothesis),
        ("Target page", p.target_page),
        ("Primary metric", p.primary_metric),
        ("Rationale", p.rationale),
        ("Effort", p.effort or "medium"),
    ]
    body = "\n\n".join(f"## {name}\n{value}" for name, value in sections)
    if p.inferred_fields:
        body = (
            "> [!NOTE]\n> **Inferred by the intake agent, please confirm:** "
            + ", ".join(p.inferred_fields)
            + "\n\n"
            + body
        )
    return body + "\n\n---\n_Filed by the Experiment Intake Agent._"


@tool(
    "create_experiment_ticket",
    "File a new, structured experiment brief in the backlog. Only use this after checking "
    "the backlog and confirming the idea is not already covered.",
)
async def create_experiment_ticket(parameters: CreateTicketParams):
    title = parameters.hypothesis.strip().rstrip(".")
    if len(title) > 90:
        title = title[:87] + "..."
    return github_client.create_issue(
        title=f"[Experiment] {title}",
        body=_render_body(parameters),
        labels=["experiment", "agent-filed"],
    )


# ---------- comment_on_experiment ----------

class CommentParams(BaseModel):
    issue_number: int = Field(..., description="The existing ticket")
    comment: str = Field(..., description="The new angle or supporting detail")


@tool(
    "comment_on_experiment",
    "Add a new angle or supporting detail to an existing experiment ticket instead of "
    "filing a duplicate.",
)
async def comment_on_experiment(parameters: CommentParams):
    return github_client.comment_on_issue(parameters.issue_number, parameters.comment)


if __name__ == "__main__":
    import uvicorn

    # Cloud Run tells us which port to listen on via PORT. Default to 8080 locally.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
