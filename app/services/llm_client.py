"""Cliente LLM (Gemma) — interface assíncrona compatível com a API OpenAI.

Abstrai o provedor: por padrão aponta para um servidor Gemma local via Ollama
(`http://localhost:11434/v1`), mas funciona com qualquer gateway compatível com
o protocolo OpenAI (basta ajustar `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`
no `.env`). Trocar de provedor não exige mudança de código.
"""
from __future__ import annotations

import asyncio
import re

from openai import AsyncOpenAI

from app.core.config import settings

# Erros transitórios do provedor (sobrecarga/limite) → vale retentar / cair p/ fallback.
_STATUS_TRANSITORIO = {408, 409, 425, 429, 500, 502, 503, 504}
_MAX_TENTATIVAS = 3

# Modelos com raciocínio (ex.: Gemma 4) emitem blocos <thought>/<thinking> antes
# da resposta — removemos para não poluir o relatório/markdown final.
_RE_RACIOCINIO = re.compile(r"<(thought|thinking|think)>.*?</\1>", re.IGNORECASE | re.DOTALL)
_RE_RACIOCINIO_ABERTO = re.compile(r"^\s*<(thought|thinking|think)>.*?(?=\n#|\Z)",
                                   re.IGNORECASE | re.DOTALL)


def _limpar_raciocinio(texto: str) -> str:
    """Remove blocos de raciocínio (fechados ou truncados) da resposta do LLM."""
    texto = _RE_RACIOCINIO.sub("", texto)
    texto = _RE_RACIOCINIO_ABERTO.sub("", texto)  # bloco sem fechamento
    return texto.strip()


class LLMUnavailableError(RuntimeError):
    """O modelo LLM não pôde ser contatado (servidor offline ou erro de rede)."""


class LLMClient:
    """Wrapper assíncrono fino sobre o endpoint chat/completions."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self.model = model or settings.llm_model
        # Modelo alternativo p/ quando o principal está sobrecarregado (evita falso 503).
        self.fallback_model = (
            fallback_model if fallback_model is not None else settings.llm_fallback_model
        )
        self._client = AsyncOpenAI(
            base_url=base_url or settings.llm_base_url,
            api_key=api_key or settings.llm_api_key,
        )

    async def _uma_chamada(self, modelo, system, user, temperature, max_tokens) -> str:
        resp = await self._client.chat.completions.create(
            model=modelo,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        if not content:
            raise LLMUnavailableError("Resposta vazia do LLM.")
        return _limpar_raciocinio(content)

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> str:
        """Envia system+user; retenta em erros transitórios e cai para o modelo de fallback."""
        modelos = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            modelos.append(self.fallback_model)

        ultimo_erro: Exception | None = None
        for modelo in modelos:
            for tentativa in range(_MAX_TENTATIVAS):
                try:
                    return await self._uma_chamada(modelo, system, user, temperature, max_tokens)
                except LLMUnavailableError as exc:  # resposta vazia → tenta de novo
                    ultimo_erro = exc
                except Exception as exc:  # noqa: BLE001
                    ultimo_erro = exc
                    code = getattr(exc, "status_code", None)
                    if code in (401, 403):  # auth inválida → não adianta retentar
                        raise LLMUnavailableError(
                            f"Falha de autenticação no LLM ({code}). Verifique a LLM_API_KEY."
                        ) from exc
                    if code not in _STATUS_TRANSITORIO:
                        break  # erro permanente (ex.: 404 modelo) → tenta o próximo modelo
                if tentativa < _MAX_TENTATIVAS - 1:
                    await asyncio.sleep(1.5 * (tentativa + 1))  # backoff

        raise LLMUnavailableError(
            f"LLM indisponível após retentativas (modelos: {modelos}) em "
            f"{settings.llm_base_url}: {ultimo_erro}"
        )


# Singleton lazy.
_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
