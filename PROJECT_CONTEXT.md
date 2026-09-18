# Agentic Tender Assistant — Project Context

## Business goal

Build an agent that searches public tenders, analyzes their requirements,
compares them with HPE capabilities, and produces a qualification briefing.

## Service provider

HPE.

## Main workflow

User query
→ SIMAP/Tavily search
→ Research Agent
→ document retrieval
→ requirement extraction
→ HPE capability matching
→ qualification score
→ GO/MAYBE/NO-GO
→ structured briefing
→ human approval

## Intended technologies

- SIMAP MCP
- Tavily MCP
- NeMo Agent Toolkit
- AIQ Blueprint
- NemoClaw / Hermes if available
- Pydantic structured outputs
- Streamlit demo interface

## Safety rules

- Work only in this repository.
- Never modify ~/agentic-tender-assistant.
- Never run kubectl apply/delete.
- Never run git push without explicit approval.
- Never commit secrets.

## MVP priority

The end-to-end qualification briefing is more important than
advanced integrations that are unavailable in the environment.
Use local sample data as a fallback.