import asyncio
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, AsyncIterator

from retriqs.utils import logger


def _normalize_codex_cli_command(command: str | None) -> str:
    normalized = (command or "").strip()
    return normalized or os.getenv("CODEX_CLI_PATH", "codex")


def _build_codex_cli_prompt(
    *,
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
) -> str:
    sections: list[str] = [
        "You are answering inside Retriqs as the configured LLM backend.",
        "Follow system instructions exactly. Keep output focused on final answer content.",
    ]

    if system_prompt:
        sections.append(f"System prompt:\n{system_prompt}")

    if history_messages:
        history_lines: list[str] = []
        for message in history_messages:
            role = str(message.get("role", "user")).strip() or "user"
            content = str(message.get("content", ""))
            history_lines.append(f"{role}: {content}")
        if history_lines:
            sections.append("Conversation history:\n" + "\n".join(history_lines))

    sections.append(f"User prompt:\n{prompt}")
    return "\n\n".join(sections)


def _response_format_to_schema_dict(response_format: Any) -> dict[str, Any] | None:
    if response_format is None:
        return None

    if isinstance(response_format, dict):
        return response_format

    model_json_schema = getattr(response_format, "model_json_schema", None)
    if callable(model_json_schema):
        return model_json_schema()

    return None


def _extract_agent_message(stdout_text: str) -> str:
    last_message = ""
    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") != "item.completed":
            continue

        item = event.get("item") or {}
        if item.get("type") == "agent_message":
            last_message = str(item.get("text") or "")

    return last_message


async def _run_codex_cli(
    *,
    cli_command: str,
    cwd: str | None,
    model: str | None,
    prompt: str,
    response_format: Any = None,
    timeout: int | None = None,
) -> str:
    schema_path: str | None = None
    output_path: str | None = None

    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        ) as output_file:
            output_path = output_file.name

        command = [
            cli_command,
            "exec",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--json",
            "--output-last-message",
            output_path,
        ]

        if cwd:
            command.extend(["--cd", cwd])
        if model:
            command.extend(["--model", model])

        schema_dict = _response_format_to_schema_dict(response_format)
        if schema_dict is not None:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", delete=False
            ) as schema_file:
                json.dump(schema_dict, schema_file)
                schema_file.flush()
                schema_path = schema_file.name
            command.extend(["--output-schema", schema_path])

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or None,
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(prompt.encode("utf-8")),
            timeout=timeout,
        )

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if process.returncode != 0:
            raise RuntimeError(
                "Codex CLI request failed"
                + (f": {stderr_text.strip()}" if stderr_text.strip() else "")
            )

        if stderr_text.strip():
            logger.debug("Codex CLI stderr: %s", stderr_text.strip())

        final_message = ""
        if output_path and Path(output_path).exists():
            final_message = Path(output_path).read_text(encoding="utf-8").strip()
        if not final_message:
            final_message = _extract_agent_message(stdout_text).strip()
        if not final_message:
            raise RuntimeError("Codex CLI returned no assistant message")

        return final_message
    except asyncio.TimeoutError as exc:
        raise RuntimeError("Codex CLI request timed out") from exc
    finally:
        for temp_path in (schema_path, output_path):
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


async def codex_cli_complete_if_cache(
    model: str,
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    stream: bool | None = None,
    timeout: int | None = None,
    **kwargs: Any,
) -> str | AsyncIterator[str]:
    del api_key
    kwargs.pop("hashing_kv", None)
    response_format = kwargs.pop("response_format", None)

    composed_prompt = _build_codex_cli_prompt(
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
    )

    async def _single_result_stream() -> AsyncIterator[str]:
        result = await _run_codex_cli(
            cli_command=_normalize_codex_cli_command(base_url),
            cwd=kwargs.get("working_dir"),
            model=model,
            prompt=composed_prompt,
            response_format=response_format,
            timeout=timeout,
        )
        yield result

    if stream:
        return _single_result_stream()

    return await _run_codex_cli(
        cli_command=_normalize_codex_cli_command(base_url),
        cwd=kwargs.get("working_dir"),
        model=model,
        prompt=composed_prompt,
        response_format=response_format,
        timeout=timeout,
    )
