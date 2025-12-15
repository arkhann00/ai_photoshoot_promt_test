from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from src.config import settings
from src.services.photoshoot import generate_photoshoot_image


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

HELP_TEXT = (
    "Этот бот превращает твоё селфи в картинку из ИИ.\n\n"
    "Как пользоваться:\n"
    "1️⃣ Отправь мне 1–3 фото (лучше селфи).\n"
    "2️⃣ В подписи к сообщению напиши промт — стиль, атмосферу, окружение.\n\n"
    "Примеры промтов:\n"
    "• «Кинематографичный портрет, неоновый свет, ночной город на фоне»\n"
    "• «Фэнтези-портрет мага, магический огонь в руках, тёмный лес»\n"
    "• «Деловой портрет в стиле LinkedIn, светлая студия, мягкий свет»\n\n"
    "Я возьму фото, промт и сгенерирую новую картинку ✨"
)


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer("Привет!\n\nПришли мне 1–3 фото с подписью-промтом")


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@dp.message(F.photo)
async def handle_photo(message: Message, bot: Bot) -> None:
    """
    Пользователь присылает фото. В подписи к фото — промт.
    Поддерживаем 1–3 фото в одном сообщении: message.photo — это размеры одного и того же фото,
    поэтому реально 1 фото на сообщение. Но на всякий случай поддержим альбомы:
    если пользователь шлёт медиа-группу (альбом), aiogram обычно отдаёт отдельно.
    В этом минимальном файле оставляем работу с 1 фото на сообщение.
    """

    if not message.caption:
        await message.answer(
            "Пожалуйста, добавь текст-промт в подпись к фото 🙏\n"
            "Например: «Портрет в стиле кино, неоновый свет, тёмный фон»."
        )
        return

    prompt_text = message.caption.strip()

    # Самое большое фото (последнее) — это один file_id
    file_id = message.photo[-1].file_id

    waiting_msg = await message.answer("Генерирую картинку, это может занять немного времени...")

    try:
        # ✅ фикс: используем правильный аргумент user_photo_file_ids
        result_file = await generate_photoshoot_image(
            style_title="Пользовательский стиль",
            style_prompt=prompt_text,
            user_photo_file_ids=[file_id],
            bot=bot,
        )
    except RuntimeError as e:
        logger.exception("Ошибка генерации изображения (RuntimeError)")
        await waiting_msg.edit_text(
            "Не получилось сгенерировать картинку 👀\n"
            f"Причина: {e}"
        )
        return
    except Exception:
        logger.exception("Неизвестная ошибка генерации изображения")
        await waiting_msg.edit_text(
            "Произошла неизвестная ошибка при генерации картинки. "
            "Попробуй ещё раз чуть позже."
        )
        return

    await waiting_msg.delete()
    await message.answer_photo(result_file, caption="Готово!")
    await message.answer_document(result_file)

@dp.message()
async def handle_just_text(message: Message) -> None:
    await message.answer("Чтобы получить картинку, пришли, пожалуйста, фото с подписью-промтом.")


async def main() -> None:
    logger.info("Запуск бота")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
