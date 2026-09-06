"""Read-only stdio MCP server exposing selected OpenAI REST operations."""

from __future__ import annotations

from enum import Enum

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from openai_mcp import formatting
from openai_mcp.client import OpenAIAPIError, openai_request

mcp = FastMCP("openai_mcp")


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


def _error(error: OpenAIAPIError) -> str:
    return str(error)


class ListModelsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_format: ResponseFormat = ResponseFormat.MARKDOWN


@mcp.tool(name="openai_list_models", annotations={"readOnlyHint": True, "destructiveHint": False})
async def openai_list_models(params: ListModelsInput) -> str:
    """List models available to the configured API key."""
    try:
        response = await openai_request("GET", "/models")
    except OpenAIAPIError as error:
        return _error(error)
    return formatting.to_json(response) if params.response_format is ResponseFormat.JSON else formatting.format_models(response.get("data", []))


class GetModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=100)
    response_format: ResponseFormat = ResponseFormat.MARKDOWN


@mcp.tool(name="openai_get_model", annotations={"readOnlyHint": True, "destructiveHint": False})
async def openai_get_model(params: GetModelInput) -> str:
    """Return metadata for a specific accessible model."""
    try:
        response = await openai_request("GET", f"/models/{params.model}")
    except OpenAIAPIError as error:
        return _error(error)
    if params.response_format is ResponseFormat.JSON:
        return formatting.to_json(response)
    return f"**{response.get('id', 'unknown')}**\n- Owned by: {response.get('owned_by', 'unknown')}"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1)


class ChatCompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32000)
    response_format: ResponseFormat = ResponseFormat.MARKDOWN


@mcp.tool(name="openai_chat_completion", annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False})
async def openai_chat_completion(params: ChatCompletionInput) -> str:
    """Send a chat-completions request and return the generated reply."""
    body = {"model": params.model, "messages": [message.model_dump() for message in params.messages]}
    if params.temperature is not None:
        body["temperature"] = params.temperature
    if params.max_tokens is not None:
        body["max_tokens"] = params.max_tokens
    try:
        response = await openai_request("POST", "/chat/completions", json_body=body)
    except OpenAIAPIError as error:
        return _error(error)
    return formatting.to_json(response) if params.response_format is ResponseFormat.JSON else formatting.format_chat(response)


class CreateEmbeddingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_texts: list[str] = Field(min_length=1, max_length=100)
    model: str = "text-embedding-3-small"
    response_format: ResponseFormat = ResponseFormat.MARKDOWN


@mcp.tool(name="openai_create_embedding", annotations={"readOnlyHint": True, "destructiveHint": False})
async def openai_create_embedding(params: CreateEmbeddingInput) -> str:
    """Generate embeddings without returning full vectors by default."""
    try:
        response = await openai_request("POST", "/embeddings", json_body={"model": params.model, "input": params.input_texts})
    except OpenAIAPIError as error:
        return _error(error)
    return formatting.to_json(response) if params.response_format is ResponseFormat.JSON else formatting.format_embeddings(response)


class CreateModerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_texts: list[str] = Field(min_length=1, max_length=50)
    response_format: ResponseFormat = ResponseFormat.MARKDOWN


@mcp.tool(name="openai_create_moderation", annotations={"readOnlyHint": True, "destructiveHint": False})
async def openai_create_moderation(params: CreateModerationInput) -> str:
    """Check text against OpenAI moderation categories."""
    try:
        response = await openai_request("POST", "/moderations", json_body={"input": params.input_texts})
    except OpenAIAPIError as error:
        return _error(error)
    return formatting.to_json(response) if params.response_format is ResponseFormat.JSON else formatting.format_moderation(response)


class ListFineTuningJobsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=20, ge=1, le=100)
    after: str | None = None
    response_format: ResponseFormat = ResponseFormat.MARKDOWN


@mcp.tool(name="openai_list_fine_tuning_jobs", annotations={"readOnlyHint": True, "destructiveHint": False})
async def openai_list_fine_tuning_jobs(params: ListFineTuningJobsInput) -> str:
    """List fine-tuning jobs without creating or changing any job."""
    query = {"limit": params.limit}
    if params.after:
        query["after"] = params.after
    try:
        response = await openai_request("GET", "/fine_tuning/jobs", params=query)
    except OpenAIAPIError as error:
        return _error(error)
    return formatting.to_json(response) if params.response_format is ResponseFormat.JSON else formatting.to_json(response.get("data", []))


class GetFineTuningJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1)
    response_format: ResponseFormat = ResponseFormat.MARKDOWN


@mcp.tool(name="openai_get_fine_tuning_job", annotations={"readOnlyHint": True, "destructiveHint": False})
async def openai_get_fine_tuning_job(params: GetFineTuningJobInput) -> str:
    """Inspect one fine-tuning job without modifying it."""
    try:
        response = await openai_request("GET", f"/fine_tuning/jobs/{params.job_id}")
    except OpenAIAPIError as error:
        return _error(error)
    return formatting.to_json(response)


def main() -> None:
    """Run the server over stdio for an MCP client."""
    mcp.run()


if __name__ == "__main__":
    main()

