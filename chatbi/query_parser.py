from __future__ import annotations


class QueryParser:
    def parse(self, user_input: str) -> dict:
        question = user_input.strip()
        return {"original_question": question, "is_valid": bool(question)}

    @staticmethod
    def validate(parsed_query: dict) -> bool:
        return bool(parsed_query.get("is_valid"))
