"""Клиент для работы с GigaChat API через официальный SDK Сбера gigachat с поддержкой сертификатов и ключей."""

import logging
import os
from typing import Optional

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

logger = logging.getLogger(__name__)


class GigaChatClient:
    """Клиент GigaChat с поддержкой официального SDK для работы по сертификатам Минцифры / mTLS и по ключу."""

    def __init__(self):
        self._cached_client: Optional[GigaChat] = None
        self._client_key: str = ""

    def _get_or_create_client(
        self,
        auth_mode: str,
        auth_key: str,
        cert_file: str,
        key_file: str,
        ca_file: str,
        scope: str,
        model: str,
        temperature: float,
    ) -> GigaChat:
        # Уникальный ключ конфигурации для кэширования сессии
        config_key = f"{auth_mode}:{auth_key}:{cert_file}:{key_file}:{ca_file}:{scope}:{model}:{temperature}"
        if self._cached_client and self._client_key == config_key:
            return self._cached_client

        kwargs = {
            "model": model or "GigaChat",
            "scope": scope or "GIGACHAT_API_PERS",
            "timeout": 60.0,
        }

        if auth_mode == "cert":
            # Режим работы по сертификатам
            if ca_file and os.path.exists(ca_file):
                kwargs["ca_bundle_file"] = ca_file
                kwargs["verify_ssl_certs"] = True
            else:
                kwargs["verify_ssl_certs"] = False

            if cert_file and os.path.exists(cert_file):
                kwargs["cert_file"] = cert_file
            if key_file and os.path.exists(key_file):
                kwargs["key_file"] = key_file
            if auth_key:
                kwargs["credentials"] = auth_key
        else:
            # Режим работы по ключу (Basic Auth)
            kwargs["credentials"] = auth_key
            kwargs["verify_ssl_certs"] = False

        logger.info(f"Инициализация GigaChat SDK (auth_mode={auth_mode}, scope={scope}, model={model})")
        client = GigaChat(**kwargs)
        self._cached_client = client
        self._client_key = config_key
        return client

    async def generate(
        self,
        auth_mode: str = "key",
        auth_key: str = "",
        cert_file: str = "",
        key_file: str = "",
        ca_file: str = "",
        scope: str = "GIGACHAT_API_PERS",
        user_text: str = "",
        system_prompt: str = "",
        model: str = "GigaChat",
        temperature: float = 0.7,
    ) -> str:
        """Отправляет запрос в GigaChat через официальный SDK."""
        client = self._get_or_create_client(
            auth_mode=auth_mode,
            auth_key=auth_key,
            cert_file=cert_file,
            key_file=key_file,
            ca_file=ca_file,
            scope=scope,
            model=model,
            temperature=temperature,
        )

        messages = []
        if system_prompt:
            messages.append(Messages(role=MessagesRole.SYSTEM, content=system_prompt))
        messages.append(Messages(role=MessagesRole.USER, content=user_text))

        chat_payload = Chat(
            messages=messages,
            temperature=temperature,
            max_tokens=4096,
        )

        # Вызываем chat через SDK (выполняем в синхронном клиенте SDK)
        import anyio
        response = await anyio.to_thread.run_sync(client.chat, chat_payload)

        choices = response.choices
        if choices and len(choices) > 0:
            return choices[0].message.content
        return "Пустой ответ от GigaChat"

    def reset_token(self) -> None:
        """Сбрасывает кэшированный клиент при смене настроек."""
        self._cached_client = None
        self._client_key = ""


# Глобальный экземпляр клиента
gigachat_client = GigaChatClient()
