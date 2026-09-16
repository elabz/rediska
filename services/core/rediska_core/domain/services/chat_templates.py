"""Chat template abstraction for different LLM model families.

This module provides configurable chat templates for different model types.
Each template knows how to:
1. Parse responses to extract content (e.g., removing thinking tags)
2. Provide recommended inference parameters
3. Validate output format

Usage:
    from rediska_core.domain.services.chat_templates import get_chat_template

    template = get_chat_template("llama3")
    extracted = template.extract_content(raw_response)
    defaults = template.get_default_params()
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


def _repair_json(json_str: str) -> str:
    """Attempt to repair common JSON issues from LLM output.

    Fixes, in order, each followed by a parse attempt:
    - Trailing commas before } or ]
    - A character-level pass that (a) escapes literal newlines/tabs inside
      strings, (b) escapes unescaped double quotes inside strings when the
      quote is not followed by a structural character, and (c) turns a bare
      string sitting where an object key is expected (``{"a": 1, "loose"}``)
      into ``"loose": true`` — models regularly emit a list of criteria inside
      ``{}`` instead of ``[]``, which used to fail the whole dimension.
    - Truncated output: close any open strings/containers so a cut-off
      response still yields the fields that were completed.

    Returns the original string when nothing parses, so the caller's error
    message points at the model output rather than at a half-repair.
    """
    candidates = []

    repaired = re.sub(r',\s*([\]}])', r'\1', json_str)
    candidates.append(repaired)

    walked = _walk_repair(repaired)
    walked = re.sub(r',\s*([\]}])', r'\1', walked)
    candidates.append(walked)

    # Truncated output: terminate the open string/containers *before* the
    # walk so a cut-off bare member still receives its ``: true`` value.
    closed = _walk_repair(_close_truncated(repaired))
    closed = re.sub(r',\s*([\]}])', r'\1', closed)
    candidates.append(closed)

    for candidate in candidates:
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return json_str


_STRUCTURAL_AFTER_STRING = set(',}]:')


def _walk_repair(text: str) -> str:
    """Character-level repair of strings and bare object members (see _repair_json)."""
    out: list[str] = []
    stack: list[str] = []  # '{' or '['
    # Per-object flag: are we currently expecting a key (True) or a value (False)?
    expect_key: list[bool] = []
    in_string = False
    escape = False
    string_start_out = -1
    i = 0
    n = len(text)

    def _next_significant(pos: int) -> str:
        while pos < n and text[pos] in ' \t\r\n':
            pos += 1
        return text[pos] if pos < n else ''

    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                out.append(ch)
                escape = False
            elif ch == '\\':
                out.append(ch)
                escape = True
            elif ch == '\n':
                out.append('\\n')
            elif ch == '\t':
                out.append('\\t')
            elif ch == '\r':
                out.append('\\r')
            elif ch == '"':
                following = _next_significant(i + 1)
                if following in _STRUCTURAL_AFTER_STRING or following == '':
                    # Closing quote. If this string is an object key position
                    # and no ':' follows, it is a bare member -> give it a value.
                    out.append(ch)
                    in_string = False
                    if stack and stack[-1] == '{' and expect_key[-1] and following != ':':
                        out.append(': true')
                        expect_key[-1] = False
                else:
                    out.append('\\"')
            else:
                out.append(ch)
            i += 1
            continue

        if ch == '"':
            in_string = True
            string_start_out = len(out)
            out.append(ch)
        elif ch == '{':
            stack.append('{')
            expect_key.append(True)
            out.append(ch)
        elif ch == '[':
            stack.append('[')
            expect_key.append(False)
            out.append(ch)
        elif ch in '}]':
            if stack:
                stack.pop()
                expect_key.pop()
            out.append(ch)
        elif ch == ':':
            if stack and stack[-1] == '{':
                expect_key[-1] = False
            out.append(ch)
        elif ch == ',':
            if stack and stack[-1] == '{':
                expect_key[-1] = True
            out.append(ch)
        else:
            out.append(ch)
        i += 1

    del string_start_out
    return ''.join(out)


def _close_truncated(text: str) -> str:
    """Close an unterminated string and any open containers."""
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in '{[':
            stack.append(ch)
        elif ch in '}]' and stack:
            stack.pop()
    result = text
    if in_string:
        result += '"'
    # Drop a dangling key/comma before closing (e.g. `"key":` or `,`)
    result = re.sub(r'(,|:\s*|"[^"]*"\s*:\s*)$', '', result.rstrip())
    result = re.sub(r',\s*$', '', result)
    for opener in reversed(stack):
        result += '}' if opener == '{' else ']'
    return result


@dataclass
class TemplateParams:
    """Default inference parameters for a chat template.

    Attributes:
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        top_p: Nucleus sampling probability
    """
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: Optional[float] = None


class BaseChatTemplate(ABC):
    """Abstract base class for chat templates.

    Each chat template implementation handles the specifics of
    a particular model family's output format and parsing needs.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the template identifier."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description."""
        pass

    @abstractmethod
    def get_default_params(self) -> TemplateParams:
        """Return recommended inference parameters for this template."""
        pass

    @abstractmethod
    def extract_content(self, raw_response: str) -> str:
        """Extract the actual content from the raw LLM response.

        This method handles any template-specific parsing, such as
        removing thinking tags, extracting from specific formats, etc.

        Args:
            raw_response: The raw text from the LLM

        Returns:
            Cleaned content ready for JSON parsing
        """
        pass

    def extract_json(self, raw_response: str) -> str:
        """Extract JSON from the response content.

        First applies template-specific content extraction,
        then looks for JSON object in the result, and repairs
        common JSON issues (trailing commas, etc.).

        Args:
            raw_response: The raw text from the LLM

        Returns:
            JSON string ready for parsing
        """
        content = self.extract_content(raw_response)

        # Look for JSON object in the content
        first_brace = content.find('{')
        last_brace = content.rfind('}')

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = content[first_brace:last_brace + 1].strip()
            logger.debug(
                f"[{self.name}] Extracted JSON: {len(json_str)} chars "
                f"from positions {first_brace}-{last_brace}"
            )

            # Try parsing raw first; if it fails, attempt repair
            try:
                json.loads(json_str)
                return json_str
            except json.JSONDecodeError:
                repaired = _repair_json(json_str)
                if repaired != json_str:
                    logger.info(
                        f"[{self.name}] Applied JSON repair "
                        f"({len(json_str)} -> {len(repaired)} chars)"
                    )
                return repaired

        logger.warning(
            f"[{self.name}] No JSON braces found in response. "
            f"Content preview: {content[:500]}..."
        )
        return content.strip()


class QwenThinkingTemplate(BaseChatTemplate):
    """Chat template for Qwen reasoning models with <think> tags.

    These models output their reasoning process in <think>...</think> tags
    before the actual response. This template strips those tags to get
    the final JSON output.

    Example model: Qwen-QwQ, Qwen2.5-Instruct with thinking enabled
    """

    @property
    def name(self) -> str:
        return "qwen_thinking"

    @property
    def description(self) -> str:
        return "Qwen reasoning models with <think> tags"

    def get_default_params(self) -> TemplateParams:
        return TemplateParams(
            temperature=0.7,
            max_tokens=8192,  # High for thinking + output
            top_p=0.95,
        )

    def extract_content(self, raw_response: str) -> str:
        """Remove <think>...</think> blocks from response.

        Handles:
        - Complete <think>...</think> blocks
        - Unclosed <think> tags (truncated responses)
        - Case variations
        """
        original_len = len(raw_response)
        content = raw_response

        # Remove <think>...</think> blocks (including multiline)
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)

        # Handle unclosed <think> tag (truncated response)
        if '<think>' in content:
            think_start = content.find('<think>')
            logger.warning(
                f"[{self.name}] Found unclosed <think> tag at position {think_start}. "
                f"Content length: {original_len}. Removing from <think> to end."
            )
            content = content[:think_start]

        # Handle case variations
        content = re.sub(
            r'<Think>.*?</Think>', '', content,
            flags=re.DOTALL | re.IGNORECASE
        )

        # Remove partial/orphan tags
        content = re.sub(r'<think>.*$', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<\/think>', '', content, flags=re.IGNORECASE)

        logger.debug(
            f"[{self.name}] After removing think tags: "
            f"{len(content)} chars (was {original_len})"
        )

        return content.strip()


class Llama3InstructTemplate(BaseChatTemplate):
    """Chat template for Llama 3 Instruct and compatible models.

    Uses the standard Llama 3 instruct format:
    <|begin_of_text|><|start_header_id|>system<|end_header_id|>
    {system}<|eot_id|><|start_header_id|>user<|end_header_id|>
    {user}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

    Compatible models:
    - Meta Llama 3 Instruct
    - Lumimaid v0.2 (based on Llama 3.1)
    - Other Llama 3 finetunes
    """

    @property
    def name(self) -> str:
        return "llama3"

    @property
    def description(self) -> str:
        return "Llama 3 Instruct format (Lumimaid, etc.)"

    def get_default_params(self) -> TemplateParams:
        return TemplateParams(
            temperature=0.6,  # Lower temp recommended
            max_tokens=2048,  # No thinking overhead
            top_p=0.9,
        )

    def extract_content(self, raw_response: str) -> str:
        """Clean up Llama 3 response.

        Llama 3 responses are generally clean, but may have:
        - Leading/trailing whitespace
        - Markdown code blocks around JSON
        """
        content = raw_response.strip()

        # Remove markdown code blocks if present
        # ```json ... ``` or ``` ... ```
        if content.startswith('```'):
            # Find the end of the opening fence
            first_newline = content.find('\n')
            if first_newline != -1:
                # Check if it ends with closing fence
                if content.rstrip().endswith('```'):
                    content = content[first_newline + 1:].rstrip()
                    if content.endswith('```'):
                        content = content[:-3].rstrip()

        return content


class MistralInstructTemplate(BaseChatTemplate):
    """Chat template for Mistral Instruct models.

    Uses the Mistral instruct format:
    [INST] {user_message} [/INST] {assistant_response}

    Compatible models:
    - Mistral 7B Instruct
    - Mixtral Instruct
    """

    @property
    def name(self) -> str:
        return "mistral"

    @property
    def description(self) -> str:
        return "Mistral/Mixtral Instruct format"

    def get_default_params(self) -> TemplateParams:
        return TemplateParams(
            temperature=0.7,
            max_tokens=2048,
            top_p=0.95,
        )

    def extract_content(self, raw_response: str) -> str:
        """Clean up Mistral response."""
        content = raw_response.strip()

        # Remove markdown code blocks if present
        if content.startswith('```'):
            first_newline = content.find('\n')
            if first_newline != -1:
                if content.rstrip().endswith('```'):
                    content = content[first_newline + 1:].rstrip()
                    if content.endswith('```'):
                        content = content[:-3].rstrip()

        return content


class ChatMLTemplate(BaseChatTemplate):
    """Chat template for ChatML format models.

    Uses the ChatML format:
    <|im_start|>system
    {system}<|im_end|>
    <|im_start|>user
    {user}<|im_end|>
    <|im_start|>assistant
    {assistant}<|im_end|>

    Compatible models:
    - Many OpenHermes finetunes
    - Some Qwen models (non-thinking)
    """

    @property
    def name(self) -> str:
        return "chatml"

    @property
    def description(self) -> str:
        return "ChatML format (<|im_start|>/<|im_end|>)"

    def get_default_params(self) -> TemplateParams:
        return TemplateParams(
            temperature=0.7,
            max_tokens=2048,
            top_p=0.95,
        )

    def extract_content(self, raw_response: str) -> str:
        """Clean up ChatML response."""
        content = raw_response.strip()

        # Remove any trailing <|im_end|> if present
        if content.endswith('<|im_end|>'):
            content = content[:-10].strip()

        # Remove markdown code blocks
        if content.startswith('```'):
            first_newline = content.find('\n')
            if first_newline != -1:
                if content.rstrip().endswith('```'):
                    content = content[first_newline + 1:].rstrip()
                    if content.endswith('```'):
                        content = content[:-3].rstrip()

        return content


# =============================================================================
# TEMPLATE REGISTRY
# =============================================================================


# Map of template names to implementations
CHAT_TEMPLATES: dict[str, type[BaseChatTemplate]] = {
    "qwen_thinking": QwenThinkingTemplate,
    "llama3": Llama3InstructTemplate,
    "mistral": MistralInstructTemplate,
    "chatml": ChatMLTemplate,
}

# Default template for backward compatibility
DEFAULT_TEMPLATE = "llama3"


def get_chat_template(name: Optional[str] = None) -> BaseChatTemplate:
    """Get a chat template by name.

    Args:
        name: Template identifier. If None, returns the default template.

    Returns:
        Instantiated chat template

    Raises:
        ValueError: If template name is not recognized
    """
    template_name = name or DEFAULT_TEMPLATE

    if template_name not in CHAT_TEMPLATES:
        available = ", ".join(CHAT_TEMPLATES.keys())
        raise ValueError(
            f"Unknown chat template: {template_name}. "
            f"Available templates: {available}"
        )

    return CHAT_TEMPLATES[template_name]()


def list_chat_templates() -> list[dict]:
    """List all available chat templates.

    Returns:
        List of dicts with name, description, and default params
    """
    result = []
    for name, template_cls in CHAT_TEMPLATES.items():
        template = template_cls()
        params = template.get_default_params()
        result.append({
            "name": name,
            "description": template.description,
            "default_params": {
                "temperature": params.temperature,
                "max_tokens": params.max_tokens,
                "top_p": params.top_p,
            },
        })
    return result


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    "BaseChatTemplate",
    "ChatMLTemplate",
    "DEFAULT_TEMPLATE",
    "Llama3InstructTemplate",
    "MistralInstructTemplate",
    "QwenThinkingTemplate",
    "TemplateParams",
    "get_chat_template",
    "list_chat_templates",
    "CHAT_TEMPLATES",
]
