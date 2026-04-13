"""
MCP HTTP Streamable Server using FastMCP.

This server exposes tools that the Azure AI Foundry agent can call via the
Model Context Protocol (MCP) over HTTP Streamable transport.

Run with:
    uv run python -m src.mcp_server.server

Or via the project script:
    uv run mcp-server
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------------------
# Logging — verbose to console regardless of development stage
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed input schemas (structured input to MCP)
# ---------------------------------------------------------------------------


class CustomerInquiry(BaseModel):
    """Structured input for a customer inquiry."""

    customer_id: str = Field(..., description="Unique customer identifier")
    inquiry_type: str = Field(
        ...,
        description="Type of inquiry: billing, support, product, general",
    )
    message: str = Field(..., description="The customer's message or question")
    priority: str = Field(
        default="normal",
        description="Priority level: low, normal, high, urgent",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Optional key-value metadata attached to the inquiry",
    )


class DataAnalysisRequest(BaseModel):
    """Structured input for a data analysis task."""

    dataset_id: str = Field(..., description="Identifier of the dataset to analyze")
    analysis_type: str = Field(
        ...,
        description="Type of analysis: summary, trend, anomaly, correlation",
    )
    parameters: dict[str, str | int | float] = Field(
        default_factory=dict,
        description="Analysis parameters (e.g. time range, columns to include)",
    )


# ---------------------------------------------------------------------------
# FastMCP server definition
# ---------------------------------------------------------------------------
MCP_HOST = os.environ.get("MCP_SERVER_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_SERVER_PORT", "8000"))

mcp = FastMCP(
    name="structured-input-mcp",
    instructions=(
        "MCP server that processes structured customer inquiries and data analysis "
        "requests on behalf of the Azure AI Foundry agent."
    ),
)

logger.info("FastMCP server instance created: %s", mcp.name)


# ---------------------------------------------------------------------------
# Tool: process_customer_inquiry
# ---------------------------------------------------------------------------
@mcp.tool
def process_customer_inquiry(
    customer_id: str,
    inquiry_type: str,
    message: str,
    priority: str = "normal",
    metadata: str = "{}",
) -> str:
    """
    Process a structured customer inquiry.

    Args:
        customer_id: Unique customer identifier.
        inquiry_type: Type of inquiry (billing, support, product, general).
        message: The customer's message or question.
        priority: Priority level (low, normal, high, urgent).
        metadata: JSON string of additional key-value metadata.

    Returns:
        JSON string containing the processed inquiry result.
    """
    logger.info(
        "[MCP tool] process_customer_inquiry called | customer_id=%s inquiry_type=%s priority=%s",
        customer_id,
        inquiry_type,
        priority,
    )
    logger.debug("[MCP tool] message=%r metadata_raw=%r", message, metadata)

    try:
        meta = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError as exc:
        logger.warning("[MCP tool] Could not parse metadata JSON: %s", exc)
        meta = {}

    inquiry = CustomerInquiry(
        customer_id=customer_id,
        inquiry_type=inquiry_type,
        message=message,
        priority=priority,
        metadata=meta,
    )

    # Simulate inquiry routing logic
    routing_map = {
        "billing": "billing-team@company.com",
        "support": "support-team@company.com",
        "product": "product-team@company.com",
        "general": "info@company.com",
    }
    routed_to = routing_map.get(inquiry.inquiry_type, "info@company.com")
    ticket_id = f"TKT-{inquiry.customer_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    result = {
        "ticket_id": ticket_id,
        "customer_id": inquiry.customer_id,
        "inquiry_type": inquiry.inquiry_type,
        "priority": inquiry.priority,
        "routed_to": routed_to,
        "status": "received",
        "timestamp": datetime.now(UTC).isoformat(),
        "message_preview": inquiry.message[:100],
    }

    logger.info(
        "[MCP tool] Inquiry processed | ticket_id=%s routed_to=%s",
        ticket_id,
        routed_to,
    )
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Tool: run_data_analysis
# ---------------------------------------------------------------------------
@mcp.tool
def run_data_analysis(
    dataset_id: str,
    analysis_type: str,
    parameters: str = "{}",
) -> str:
    """
    Run a data analysis task on the specified dataset.

    Args:
        dataset_id: Identifier of the dataset to analyze.
        analysis_type: Type of analysis (summary, trend, anomaly, correlation).
        parameters: JSON string of analysis parameters.

    Returns:
        JSON string containing the analysis result.
    """
    logger.info(
        "[MCP tool] run_data_analysis called | dataset_id=%s analysis_type=%s",
        dataset_id,
        analysis_type,
    )
    logger.debug("[MCP tool] parameters_raw=%r", parameters)

    try:
        params = json.loads(parameters) if parameters else {}
    except json.JSONDecodeError as exc:
        logger.warning("[MCP tool] Could not parse parameters JSON: %s", exc)
        params = {}

    request = DataAnalysisRequest(
        dataset_id=dataset_id,
        analysis_type=analysis_type,
        parameters=params,
    )

    # Simulate analysis result
    result = {
        "dataset_id": request.dataset_id,
        "analysis_type": request.analysis_type,
        "parameters_received": request.parameters,
        "status": "completed",
        "timestamp": datetime.now(UTC).isoformat(),
        "result_summary": (
            f"Analysis '{request.analysis_type}' on dataset '{request.dataset_id}' "
            f"completed successfully with {len(request.parameters)} parameter(s)."
        ),
        "insights": [
            "Data quality score: 98%",
            "Records processed: 42,000",
            "Anomalies detected: 3",
        ],
    }

    logger.info(
        "[MCP tool] Analysis completed | dataset_id=%s analysis_type=%s",
        dataset_id,
        analysis_type,
    )
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Tool: get_server_status
# ---------------------------------------------------------------------------
@mcp.tool
def get_server_status() -> str:
    """Return the current MCP server status and available tools."""
    logger.info("[MCP tool] get_server_status called")

    status = {
        "server_name": mcp.name,
        "status": "running",
        "timestamp": datetime.now(UTC).isoformat(),
        "available_tools": [
            "process_customer_inquiry",
            "run_data_analysis",
            "get_server_status",
        ],
        "transport": "streamable-http",
    }
    return json.dumps(status, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info(
        "Starting MCP HTTP Streamable server on http://%s:%d/mcp",
        MCP_HOST,
        MCP_PORT,
    )
    logger.info("Transport: streamable-http")
    logger.info("Log level: %s", LOG_LEVEL)
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)


if __name__ == "__main__":
    main()
