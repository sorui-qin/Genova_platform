from dataclasses import replace
from backend.agent.reasoning import request_settings

from openai import AsyncOpenAI, omit
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider


class ChatGPTResponsesModel(OpenAIResponsesModel):
    def __init__(self, model, api_key, http_client=None, reasoning=None):
        # shortcut: this endpoint rejects max_output_tokens; use server limits if OpenAI adds support.
        super().__init__(model, provider=OpenAIProvider(openai_client=AsyncOpenAI(
            api_key=api_key, base_url="https://api.openai.com/v1", http_client=http_client,
            max_retries=0)), settings=request_settings(reasoning), profile=OpenAIModelProfile(
                openai_responses_requires_streaming=True,
                openai_responses_requires_store_false=True,
                openai_system_prompt_role="developer",
                openai_unsupported_model_settings=("max_tokens", "temperature", "top_p", "openai_top_logprobs",
                    "openai_user", "openai_background", "openai_moderation", "openai_prompt_cache_retention",
                    "openai_truncation")))

    async def _build_responses_request_params(self, messages, model_settings, model_request_parameters, profile):
        model_settings = {**model_settings, "openai_previous_response_id": None, "openai_conversation_id": None}
        params = await super()._build_responses_request_params(
            messages, model_settings, model_request_parameters, profile)
        tools = [{"type": "namespace", "name": "genova", "description": "Genova agent tools",
                  "tools": params.tools}] if isinstance(params.tools, list) else params.tools
        for item in params.input:
            if isinstance(item, dict) and item.get("type") == "function_call":
                item["namespace"] = "genova"
        choice = params.tool_choice
        if isinstance(choice, dict):
            if choice.get("type") == "function":
                choice["namespace"] = "genova"
            elif choice.get("type") == "allowed_tools":
                for tool in choice["tools"]:
                    tool["namespace"] = "genova"
        return replace(params, tools=tools, previous_response_id=omit, conversation=omit)

    async def _responses_create(self, *args, **kwargs):
        try:
            return await super()._responses_create(*args, **kwargs)
        except ModelHTTPError as exc:
            if exc.status_code == 401:
                from backend.agent.user_settings import config_error
                raise config_error("AGENT_CHATGPT_AUTH_REQUIRED", "Authorize ChatGPT again in Settings", 503) from None
            raise

    async def _process_streamed_response(self, response, model_settings, model_request_parameters, **kwargs):
        async def checked_events():
            from backend.agent.user_settings import config_error
            from backend.agent.errors import provider_http_error
            from backend.agent.runner import RunFailure
            completed = False
            argument_items = set()
            async for event in response:
                if event.type == "response.output_item.added" and event.item.type == "function_call" and event.item.arguments:
                    argument_items.add(event.item.id)
                elif event.type == "response.function_call_arguments.delta" and event.delta:
                    argument_items.add(event.item_id)
                elif event.type == "response.function_call_arguments.done" and event.arguments and event.item_id not in argument_items:
                    from openai.types.responses import ResponseFunctionCallArgumentsDeltaEvent
                    argument_items.add(event.item_id)
                    yield ResponseFunctionCallArgumentsDeltaEvent(type="response.function_call_arguments.delta",
                        sequence_number=event.sequence_number, item_id=event.item_id,
                        output_index=event.output_index, delta=event.arguments)

                if event.type == "error":
                    code, message, upstream = provider_http_error(502, {"error": {"code": event.code}})
                    raise config_error(code, message, 402 if code == "AGENT_QUOTA_EXCEEDED" else 502,
                        upstream_error_code=upstream)
                if event.type == "response.failed":
                    body = {"error": event.response.error.model_dump()} if event.response.error else {}
                    code, message, upstream = provider_http_error(502, body)
                    raise config_error(code, message, 402 if code == "AGENT_QUOTA_EXCEEDED" else 502,
                        upstream_error_code=upstream)
                if event.type == "response.incomplete":
                    raise RunFailure("AGENT_OUTPUT_TRUNCATED")
                if event.type == "response.completed":
                    completed = True
                yield event
            if not completed:
                raise config_error("AGENT_CONNECTION_ERROR", "ChatGPT stream ended before response.completed", 502)
        return await super()._process_streamed_response(
            checked_events(), model_settings, model_request_parameters, **kwargs)
