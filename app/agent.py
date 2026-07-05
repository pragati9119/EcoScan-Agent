import json
import os
import re
from pydantic import BaseModel, Field
from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.workflow import Workflow, node
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.apps import App, ResumabilityConfig
from google.adk.models import Gemini
from google.adk.tools import AgentTool
from google.genai import types

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from .config import config

# Set VertexAI to False explicitly so it uses Gemini API Key
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

class EcoScanInput(BaseModel):
    item_description: str = Field(description="The description of the waste item to analyze.")
    user_location: str = Field(default="generic", description="The city or region for local disposal guidelines.")

# Define MCP Toolset using stdio connection parameters to spawn our server.py
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp_server"],
        ),
    ),
)

# Specialized Sub-Agent 1: Classification Agent
classification_agent = Agent(
    name="classification_agent",
    model=Gemini(model=config.model),
    instruction="""You are a waste classification expert.
Analyze the waste item description. Determine:
1. Material type (e.g., plastic, glass, organic, electronic, metal, paper, hazardous).
2. Recyclability (Is it recyclable, compostable, or landfill?).
3. Hazard level (low, medium, high - e.g., batteries, chemicals, electronics, paint are high).
Use the identify_hazardous_materials tool to check if the item is hazardous.
Provide a clear analysis and categorization.""",
    tools=[mcp_toolset],
    description="Classifies waste items by material type, recyclability, and hazard level."
)

# Specialized Sub-Agent 2: Guidance Agent
guidance_agent = Agent(
    name="guidance_agent",
    model=Gemini(model=config.model),
    instruction="""You are a local waste disposal guide.
Based on the waste classification, hazard level, and the user's location, provide localized recycling rules, safety instructions, and disposal recommendations.
Use the get_local_recycling_rules and lookup_dropoff_locations tools to fetch rules and facility addresses for the location and material.
If the item is hazardous, prioritize safe drop-off location info.""",
    tools=[mcp_toolset],
    description="Provides localized recycling and disposal instructions based on waste classification and location."
)

# Orchestrator Agent
orchestrator = Agent(
    name="orchestrator",
    model=Gemini(model=config.model),
    instruction="""You are the EcoScan Orchestrator.
Your goal is to coordinate the classification and local disposal guidance for a waste item.
Use classification_agent to classify the item.
Then use guidance_agent to get recycling rules and safety instructions.
After receiving the results, summarize the findings and determine if this item needs human review.
An item needs human review if:
- It is classified as high hazard (e.g., hazardous waste, chemicals, batteries, medical waste).
- The description is ambiguous or you are unsure about the classification.
If it needs human review, clearly state "NEEDS_REVIEW" in your final summary. Otherwise, state "AUTO_APPROVED".""",
    tools=[AgentTool(classification_agent), AgentTool(guidance_agent)],
    description="Orchestrates waste analysis by delegating to classification and guidance agents."
)

def input_processor(ctx: Context, node_input: str) -> Event:
    # Parse free-text input to extract item and location
    text = node_input.strip()
    item_description = text
    user_location = "generic"

    # Try to extract "Item:" and "Location:" fields from the text
    lines = text.split("\n")
    for line in lines:
        line_stripped = line.strip()
        if line_stripped.lower().startswith("item:"):
            item_description = line_stripped[len("item:"):].strip()
        elif line_stripped.lower().startswith("location:"):
            user_location = line_stripped[len("location:"):].strip()

    return Event(
        output=item_description,
        state={
            "item_description": item_description,
            "user_location": user_location,
        }
    )

def security_checkpoint(ctx: Context, node_input: str) -> Event:
    # 1. PII Scrubbing (Email and Phone numbers)
    cleaned_input = node_input
    
    # Email regex
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    if re.search(email_pattern, cleaned_input):
        cleaned_input = re.sub(email_pattern, "[REDACTED_EMAIL]", cleaned_input)
        
    # Phone number regex
    phone_pattern = r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
    if re.search(phone_pattern, cleaned_input):
        cleaned_input = re.sub(phone_pattern, "[REDACTED_PHONE]", cleaned_input)

    # Update input description in state with scrubbed version
    ctx.state["item_description"] = cleaned_input

    # 2. Prompt Injection Detection
    injection_keywords = ["ignore instructions", "ignore previous instructions", "system prompt", "you are now a", "override", "bypass safety", "jailbreak"]
    detected_injection = any(kw in cleaned_input.lower() for kw in injection_keywords)

    # 3. Domain-Specific Rule (Illegal dumping check)
    illegal_dump_keywords = ["pour down drain", "dump in river", "dump in lake", "bury in backyard", "illegal dump"]
    detected_illegal_dump = any(kw in cleaned_input.lower() for kw in illegal_dump_keywords)

    # 4. Structured JSON Audit Log
    audit_log = {
        "event": "security_check",
        "session_id": ctx.session.id,
        "input_len": len(node_input),
        "pii_redacted": cleaned_input != node_input,
        "injection_detected": detected_injection,
        "illegal_dumping_detected": detected_illegal_dump,
    }

    if detected_injection or detected_illegal_dump:
        audit_log["severity"] = "CRITICAL"
        audit_log["action"] = "blocked"
        print(json.dumps(audit_log))
        
        ctx.state["security_violation_reason"] = "Prompt injection attempt detected." if detected_injection else "Intent to perform illegal disposal detected."
        return Event(output=cleaned_input, route="SECURITY_EVENT")
    
    if cleaned_input != node_input:
        audit_log["severity"] = "WARNING"
        audit_log["action"] = "scrubbed_and_allowed"
    else:
        audit_log["severity"] = "INFO"
        audit_log["action"] = "allowed"
        
    print(json.dumps(audit_log))
    return Event(output=cleaned_input, route="safe")

def security_violation_output(ctx: Context, node_input: str):
    reason = ctx.state.get("security_violation_reason", "Security policy violation detected.")
    response_text = f"""### 🛡️ EcoScan Security Alert
**Request Blocked:** The system detected a safety policy violation.

**Reason:** {reason}
If you believe this is an error, please rephrase your request.
"""
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=response_text)]))
    yield Event(output=response_text)

def router_node(ctx: Context, node_input: types.Content) -> Event:
    # Extract the text content from types.Content
    text = ""
    if node_input.parts:
        text = "".join(part.text for part in node_input.parts if part.text)
    
    # Save the orchestrator's summary to state
    ctx.state["orchestrator_summary"] = text
    
    # Simple routing logic
    if "NEEDS_REVIEW" in text or "needs review" in text.lower():
        ctx.state["needs_review"] = True
        return Event(output=text, route="needs_review")
    else:
        ctx.state["needs_review"] = False
        return Event(output=text, route="auto_approved")

@node(rerun_on_resume=True)
async def human_review(ctx: Context, node_input: str):
    if not ctx.resume_inputs or "human_approval" not in ctx.resume_inputs:
        yield RequestInput(
            interrupt_id="human_approval",
            message=f"⚠️ Alert: Hazardous or ambiguous item detected. Please review the summary below:\n\n{node_input}\n\nDo you approve these disposal instructions? (yes/no)"
        )
        return
    
    user_decision = ctx.resume_inputs["human_approval"]
    ctx.state["review_status"] = "approved" if "yes" in user_decision.lower() else "rejected"
    ctx.state["review_comments"] = user_decision
    yield Event(output=f"Human review status: {ctx.state['review_status'].upper()}.\nComments: {user_decision}")

def final_output(ctx: Context, node_input: str):
    needs_review = ctx.state.get("needs_review", False)
    item = ctx.state.get("item_description", "Unknown item")
    loc = ctx.state.get("user_location", "Unknown location")
    summary = ctx.state.get("orchestrator_summary", "")
    
    if needs_review:
        review_status = ctx.state.get("review_status", "pending")
        review_comments = ctx.state.get("review_comments", "")
        final_text = f"""### EcoScan Report for {item} (Location: {loc})
**Status:** Reviewed by Human Expert ({review_status.upper()})

**Original Analysis:**
{summary}

**Human Review Log:**
- Decision: {review_status.upper()}
- Comments: {review_comments}
"""
    else:
        final_text = f"""### EcoScan Report for {item} (Location: {loc})
**Status:** AUTO APPROVED (Low Hazard)

**Analysis & Guidance:**
{summary}
"""
    
    # Yield content for Web UI rendering
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=final_text)]))
    # Yield output for the workflow runner
    yield Event(output=final_text)

ecoscan_workflow = Workflow(
    name="ecoscan_workflow",
    edges=[
        ('START', input_processor),
        (input_processor, security_checkpoint),
        (security_checkpoint, {"safe": orchestrator, "SECURITY_EVENT": security_violation_output}),
        (orchestrator, router_node),
        (router_node, {"needs_review": human_review, "auto_approved": final_output}),
        (human_review, final_output),
    ],
)

app = App(
    root_agent=ecoscan_workflow,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
