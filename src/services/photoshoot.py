from __future__ import annotations

import base64
import logging
import os
import ssl
import tempfile
from typing import Optional, Sequence

import aiohttp
import certifi
from aiogram import Bot
from aiogram.types import FSInputFile

from src.config import settings


logger = logging.getLogger(__name__)

COMET_BASE_URL = "https://api.cometapi.com"
COMET_MODEL_NAME = "gemini-3-pro-image"
COMET_ENDPOINT = f"{COMET_BASE_URL}/v1beta/models/{COMET_MODEL_NAME}:generateContent"


async def _download_telegram_photo(bot: Bot, file_id: str) -> bytes:
    """
    Скачивает фото из Telegram по file_id и возвращает байты.
    """
    tg_file = await bot.get_file(file_id)
    stream = await bot.download_file(tg_file.file_path)

    if hasattr(stream, "read"):
        return stream.read()

    return stream


def _build_prompt(style_title: str, style_prompt: Optional[str]) -> str:
    """
    Формируем итоговый текст промпта для CometAI.
    Если есть кастомный prompt для стиля — используем его,
    иначе собираем базовый вариант по названию стиля.
    """
    if style_prompt:
        return style_prompt

    return (
        "Преврати это селфи в профессиональную фотосессию.\n"
        f"Стиль: «{style_title}».\n"
        "Сохрани черты лица пользователя, сделай свет, фон и обработку в указанном стиле, "
        "без надписей и логотипов, качественное реалистичное изображение."
    )


async def generate_photoshoot_image(
    style_title: str,
    style_prompt: Optional[str],
    user_photo_file_ids: Sequence[str] | str | None = None,
    bot: Bot | None = None,
    # ✅ поддержка старого имени аргумента, чтобы не падало в других местах кода
    user_photo_file_id: str | None = None,
) -> FSInputFile:
    """
    Основная функция генерации фотосессии через CometAI.

    Поддерживает 1, 2 или 3 входных фото из Telegram.

    Принимает:
      - user_photo_file_ids: Sequence[str] | str
      - user_photo_file_id: str (алиас для обратной совместимости)
    """

    if bot is None:
        raise RuntimeError("Не передан bot в generate_photoshoot_image(...)")

    api_key = settings.COMET_API_KEY
    if not api_key:
        raise RuntimeError("COMET_API_KEY не задан в конфиге (settings.COMET_API_KEY).")

    # ✅ если передали старый аргумент — конвертим в новый
    if user_photo_file_ids is None and user_photo_file_id:
        user_photo_file_ids = user_photo_file_id

    # Приводим параметр к списку file_id
    if isinstance(user_photo_file_ids, str):
        file_ids_list = [user_photo_file_ids]
    else:
        file_ids_list = list(user_photo_file_ids or [])

    if not file_ids_list:
        raise RuntimeError("Не передано ни одного фото для генерации фотосессии.")

    if len(file_ids_list) > 3:
        raise RuntimeError("Можно использовать не более трёх фотографий для фотосессии.")

    # 1. Скачиваем все фото из Telegram
    photo_bytes_list: list[bytes] = []
    for file_id in file_ids_list:
        try:
            original_photo_bytes = await _download_telegram_photo(bot, file_id)
        except Exception as e:
            logger.exception("Ошибка при скачивании фото из Telegram (file_id=%s): %s", file_id, e)
            raise RuntimeError("Не удалось скачать одно из фото из Telegram") from e
        photo_bytes_list.append(original_photo_bytes)

    # 2. Кодируем каждое фото в Base64 (без префикса data:image/jpeg;base64,)
    image_b64_list: list[str] = [
        base64.b64encode(photo_bytes).decode("utf-8") for photo_bytes in photo_bytes_list
    ]

    prompt_text = _build_prompt(style_title=style_title, style_prompt=style_prompt)

    # Формируем parts: сначала текст, затем 1–3 inline_data
    parts: list[dict] = [{"text": prompt_text}]
    for image_b64 in image_b64_list:
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_b64,
                }
            }
        )

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
        },
    }

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "*/*",
    }

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    # 3. Запрос к CometAI
    data = None
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                COMET_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=120,
            ) as resp:
                resp_text = await resp.text()
                try:
                    data = await resp.json()
                except Exception:
                    data = None

                if resp.status != 200:
                    error_code = None
                    if isinstance(data, dict):
                        err = data.get("error") or {}
                        error_code = err.get("code")

                    logger.error("CometAI вернул ошибку: status=%s, body=%s", resp.status, resp_text)

                    if resp.status == 403 and error_code == "insufficient_user_quota":
                        raise RuntimeError(
                            "На стороне сервиса генерации закончился оплаченный лимит. "
                            "Скоро всё починим — попробуй зайти позже 🙏"
                        )

                    raise RuntimeError("Сервис генерации фото сейчас недоступен. Попробуй позже.")
    except Exception as e:
        logger.exception("Ошибка при запросе к CometAI: %s", e)
        raise RuntimeError(str(e)) from e

    # 4. Разбираем ответ и достаём картинку
    image_bytes: Optional[bytes] = None
    mime_type: str = "image/jpeg"

    try:
        if not isinstance(data, dict):
            raise RuntimeError("Ответ сервиса не в формате JSON")

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Сервис не вернул кандидатов изображения")

        parts_response = candidates[0].get("content", {}).get("parts", []) or []

        for part in parts_response:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not inline_data:
                continue

            mime = inline_data.get("mimeType") or inline_data.get("mime_type")
            b64_data = inline_data.get("data")
            if not b64_data:
                continue

            mime_type = mime or mime_type
            image_bytes = base64.b64decode(b64_data)
            break

        if not image_bytes:
            raise RuntimeError("Не удалось получить изображение из ответа CometAI")
    except Exception as e:
        logger.exception("Ошибка при разборе ответа CometAI: %s", e)
        raise RuntimeError("Ошибка при обработке ответа сервиса генерации") from e

    # 5. Сохраняем картинку во временный файл
    try:
        tmp_dir = tempfile.gettempdir()
        ext = ".jpg"
        if "png" in mime_type:
            ext = ".png"
        elif "webp" in mime_type:
            ext = ".webp"

        file_id_for_name = file_ids_list[0]
        file_path = os.path.join(tmp_dir, f"photoshoot_{file_id_for_name}{ext}")

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return FSInputFile(file_path)
    except Exception as e:
        logger.exception("Ошибка при сохранении сгенерированного фото: %s", e)
        raise RuntimeError("Не удалось сохранить сгенерированное фото") from e
