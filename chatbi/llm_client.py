from __future__ import annotations

import json
import re
from collections.abc import Generator
from typing import Any

from openai import OpenAI

from config import AppConfig, settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, config: AppConfig = settings):
        if not config.llm.api_key:
            raise LLMError("缺少 DASHSCOPE_API_KEY")
        self.config = config
        self.model = config.llm.model
        self.client = OpenAI(api_key=config.llm.api_key, base_url=config.llm.base_url, timeout=config.llm.timeout)

    def generate_text(self, system_msg: str, prompt: str, max_tokens: int = 2000) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.config.llm.temperature,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            raise LLMError(f"千问调用失败：{exc}") from exc

    def generate_sql(self, system_msg: str, prompt: str) -> str:
        return self.extract_sql(self.generate_text(system_msg, prompt, self.config.llm.max_tokens))

    def generate_sql_stream(self, system_msg: str, prompt: str) -> Generator[str, None, None]:
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
                stream=True,
                messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content if chunk.choices else None
                if content:
                    yield content
        except Exception as exc:
            raise LLMError(f"千问流式调用失败：{exc}") from exc

    def generate_json(self, system_msg: str, prompt: str, max_tokens: int = 2200) -> dict[str, Any]:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.config.llm.temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            raise LLMError(f"千问 JSON 调用失败：{exc}") from exc
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise LLMError("模型未返回 JSON 对象")
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError("模型 JSON 解析失败") from exc

    @staticmethod
    def extract_sql(raw: str) -> str:
        cleaned = re.sub(r"```(?:sql)?|```", "", raw, flags=re.I).strip()
        match = re.search(r"\b(select|with)\b", cleaned, re.I)
        if not match:
            raise LLMError("模型未生成 SELECT/CTE SQL")
        return cleaned[match.start() :].rstrip(";").strip()

    def repair_sql(self, question: str, sql: str, error: str, prompt_context: str) -> str:
        prompt = (
            f"原问题：{question}\n错误 SQL：\n{sql}\n错误类型/信息：{error}\n\n"
            f"原始 Schema、指标与规则上下文：\n{prompt_context}\n\n"
            "修复 SQL。必须保持原业务含义，使用 MySQL 8.0，禁止 FULL OUTER JOIN，只输出 SQL。"
        )
        return self.generate_sql("你是 Text2SQL 错误修复器。", prompt)
