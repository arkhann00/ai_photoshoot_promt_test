from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from src.config import settings
from src.services.photoshoot import generate_photoshoot_image


# ----------------- ЛОГИРОВАНИЕ -----------------

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ----------------- ИНИЦИАЛИЗАЦИЯ БОТА -----------------

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

HELP_TEXT = (
    "Этот бот превращает твоё селфи в картинку из ИИ.\n\n"
    "Как пользоваться:\n"
    "1️⃣ Отправь мне фото (лучше селфи).\n"
    "2️⃣ В подписи к фото напиши промт — стиль, атмосферу, окружение.\n\n"
    "Примеры промтов:\n"
    "• «Кинематографичный портрет, неоновый свет, ночной город на фоне»\n"
    "• «Фэнтези-портрет мага, магический огонь в руках, тёмный лес»\n"
    "• «Деловой портрет в стиле LinkedIn, светлая студия, мягкий свет»\n\n"
    "Я возьму твоё фото, промт и сгенерирую новую картинку ✨"
)


# ----------------- ХЕНДЛЕРЫ КОМАНД -----------------

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет!\n\n"
        "Пришли мне селфи с подписью-промтом"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


# ----------------- ОСНОВНОЙ ХЕНДЛЕР С ФОТО -----------------

@dp.message(F.photo)
async def handle_photo(message: Message, bot: Bot) -> None:
    """
    Пользователь присылает фото. В подписи к фото — промт.
    Мы используем промт как style_prompt, а style_title ставим фиксированный.
    """

    if not message.caption:
        await message.answer(
            "Пожалуйста, добавь текст-промт в подпись к фото 🙏\n"
            "Например: «Портрет в стиле кино, неоновый свет, тёмный фон»."
        )
        return

    prompt_text = message.caption.strip()
    user_photo = message.photo[-1]  # самое большое фото
    file_id = user_photo.file_id

    waiting_msg = await message.answer(
        "Генерирую картинку, это может занять немного времени..."
    )

    try:
        # style_title можно использовать как «человеческое» название стиля,
        # а сам промт полностью отдаём в style_prompt
        result_file = await generate_photoshoot_image(
            style_title="Пользовательский стиль",
            style_prompt=prompt_text,
            user_photo_file_id=file_id,
            bot=bot,
        )
    except RuntimeError as e:
        logger.exception("Ошибка генерации изображения (RuntimeError)")
        await waiting_msg.edit_text(
            "Не получилось сгенерировать картинку 👀\n"
            f"Причина: {e}"
        )
        return
    except Exception as e:
        logger.exception("Неизвестная ошибка генерации изображения")
        await waiting_msg.edit_text(
            "Произошла неизвестная ошибка при генерации картинки. "
            "Попробуй ещё раз чуть позже."
        )
        return

    # Успешно: удаляем сообщение «Генерирую...» и отправляем фото
    await waiting_msg.delete()
    await message.answer_photo(
        result_file,
        caption="Готово!",
    )


# ----------------- ТЕКСТ БЕЗ ФОТО -----------------

@dp.message()
async def handle_just_text(message: Message) -> None:
    """
    Если пользователь отправил только текст — подсказываем, что нужно фото.
    """
    await message.answer(
        "Чтобы получить картинку, пришли, пожалуйста, фото с подписью-промтом."
    )


# ----------------- ТОЧКА ВХОДА -----------------

async def main() -> None:
    logger.info("Запуск бота")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
