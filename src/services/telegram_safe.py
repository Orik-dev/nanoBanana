# # services/telegram_safe.py
# from __future__ import annotations
# import asyncio
# import logging
# import tempfile
# import html  # ✅ ДОБАВЛЕНО
# from typing import Optional, Union
# from io import BytesIO
# import os
# from aiogram import Bot
# from aiogram.types import (
#     CallbackQuery,
#     FSInputFile,
#     InlineKeyboardMarkup,
#     Message,
# )
# from aiogram.exceptions import (
#     TelegramForbiddenError,
#     TelegramRetryAfter,
#     TelegramBadRequest,
#     TelegramNetworkError
# )

# from db.engine import SessionLocal
# from db.models import User
# from sqlalchemy import delete

# log = logging.getLogger("tg_safe")

# # ✅ НОВАЯ ФУНКЦИЯ: экранирование HTML
# def escape_html(text: str) -> str:
#     """Экранирует HTML-символы для безопасной вставки в HTML-разметку Telegram"""
#     if not text:
#         return ""
#     return html.escape(str(text))

# # ---------------------- внутренние утилиты ----------------------
# async def _maybe_delete_user(chat_id: int):
#     try:
#         async with SessionLocal() as s:
#             await s.execute(delete(User).where(User.chat_id == chat_id))
#             await s.commit()
#         log.info("user_deleted_due_block chat_id=%s", chat_id)
#     except Exception:
#         log.exception("failed to delete user on forbidden chat_id=%s", chat_id)

# def _is_not_modified(err: Exception) -> bool:
#     txt = str(err).lower()
#     return "message is not modified" in txt or "message can't be edited" in txt

# # ---------------------- публичные safe-обёртки ----------------------
# async def safe_answer(cb: CallbackQuery, text: Optional[str] = None, show_alert: bool = False):
#     """
#     ✅ УЛУЧШЕНО: с retry для сетевых ошибок
#     """
#     # from aiogram.exceptions import TelegramNetworkError
    
#     max_attempts = 3
    
#     for attempt in range(1, max_attempts + 1):
#         try:
#             await cb.answer(text=text, show_alert=show_alert, cache_time=60)
#             return
            
#         except TelegramBadRequest:
#             # Query too old - это нормально, игнорируем
#             return
            
#         except TelegramNetworkError as e:
#             if attempt < max_attempts:
#                 wait_time = 0.5 * attempt  # 0.5s, 1s, 1.5s
#                 log.warning(
#                     f"Network error in cb.answer, retry {attempt}/{max_attempts} "
#                     f"in {wait_time}s: {str(e)[:100]}"
#                 )
#                 await asyncio.sleep(wait_time)
#                 continue
#             else:
#                 # После всех попыток - просто логируем и продолжаем
#                 log.error(f"cb.answer failed after {max_attempts} attempts: {str(e)[:100]}")
#                 return
                
#         except TelegramRetryAfter as e:
#             if attempt < max_attempts:
#                 log.warning(f"Rate limit in cb.answer, waiting {e.retry_after}s")
#                 await asyncio.sleep(e.retry_after)
#                 continue
#             else:
#                 log.error(f"cb.answer rate limited after {max_attempts} attempts")
#                 return
                
#         except Exception as e:
#             # Любые другие ошибки - логируем и выходим
#             log.exception(f"cb.answer unexpected error: {str(e)[:100]}")
#             return

# async def safe_send_text(
#     bot: Bot,
#     chat_id: int,
#     text: str,
#     reply_markup: Optional[InlineKeyboardMarkup] = None,
#     parse_mode: str = "HTML",
#     disable_web_page_preview: bool = False,
# ):
#     try:
#         return await bot.send_message(
#             chat_id, 
#             text, 
#             reply_markup=reply_markup, 
#             parse_mode=parse_mode,
#             disable_web_page_preview=disable_web_page_preview,
#         )
#     except TelegramRetryAfter as e:
#         await asyncio.sleep(e.retry_after)
#         try:
#             return await bot.send_message(
#                 chat_id, 
#                 text, 
#                 reply_markup=reply_markup, 
#                 parse_mode=parse_mode,
#                 disable_web_page_preview=disable_web_page_preview,
#             )
#         except TelegramForbiddenError:
#             await _maybe_delete_user(chat_id)
#         except Exception:
#             log.exception("send_message failed after retry chat_id=%s", chat_id)
#     except TelegramForbiddenError:
#         await _maybe_delete_user(chat_id)
#     # ✅ ДОБАВЛЕНО: обработка Bad Request (некорректный HTML)
#     except TelegramBadRequest as e:
#         error_msg = str(e).lower()
#         if "can't parse entities" in error_msg or "unsupported start tag" in error_msg:
#             log.error(f"HTML parse error for chat {chat_id}, text preview: {text[:100]}")
#             # Пробуем отправить без HTML
#             try:
#                 return await bot.send_message(
#                     chat_id,
#                     text,
#                     reply_markup=reply_markup,
#                     parse_mode=None,  # Без разметки
#                     disable_web_page_preview=disable_web_page_preview,
#                 )
#             except Exception:
#                 log.exception("send_message failed without HTML chat_id=%s", chat_id)
#         else:
#             log.exception("send_message TelegramBadRequest chat_id=%s", chat_id)
#     except Exception:
#         log.exception("send_message failed chat_id=%s", chat_id)
#     return None

# # Остальной код остается без изменений...
# async def safe_send_photo(
#     bot: Bot,
#     chat_id: int,
#     photo: Union[FSInputFile, bytes],
#     caption: Optional[str] = None,
#     reply_markup: Optional[InlineKeyboardMarkup] = None,
#     parse_mode: str = "HTML",
# ) -> Optional[Message]:
#     if isinstance(photo, FSInputFile):
#         try:
#             file_size = os.path.getsize(photo.path)
#             file_size_mb = file_size / (1024 * 1024)
#             if file_size_mb > 10:
#                 log.warning(f"Photo too large ({file_size_mb:.2f} MB), sending as document")
#                 return await safe_send_document(bot, chat_id, photo.path, caption=caption)
#         except Exception:
#             pass
    
#     for attempt in range(1, 4):
#         try:
#             return await bot.send_photo(
#                 chat_id, 
#                 photo=photo, 
#                 caption=caption, 
#                 reply_markup=reply_markup, 
#                 parse_mode=parse_mode
#             )
#         except TelegramBadRequest as e:
#             error_msg = str(e).lower()
#             if "internal" in error_msg and attempt < 3:
#                 wait_time = 3 * attempt
#                 log.warning(f"Telegram internal error, retry {attempt}/3 in {wait_time}s for chat {chat_id}")
#                 await asyncio.sleep(wait_time)
#                 continue
#             if attempt == 3:
#                 log.error(f"Failed to send photo after 3 attempts, trying as document: {error_msg[:100]}")
#                 if isinstance(photo, FSInputFile):
#                     try:
#                         return await safe_send_document(bot, chat_id, photo.path, caption=caption)
#                     except Exception as doc_err:
#                         log.error(f"Failed to send as document too: {doc_err}")
#                 log.exception(f"send_photo failed chat_id={chat_id}")
#                 return None
#         except TelegramRetryAfter as e:
#             if attempt < 3:
#                 await asyncio.sleep(e.retry_after)
#                 continue
#             else:
#                 log.exception(f"send_photo failed after retry chat_id={chat_id}")
#                 return None
#         except TelegramForbiddenError:
#             await _maybe_delete_user(chat_id)
#             return None
#         except Exception as e:
#             if "timeout" in str(e).lower() and attempt < 3:
#                 wait_time = 5 * attempt
#                 log.warning(f"Timeout, retry {attempt}/3 in {wait_time}s for chat {chat_id}")
#                 await asyncio.sleep(wait_time)
#                 continue
#             log.exception(f"send_photo failed chat_id={chat_id}")
#             return None
#     return None

# async def safe_send_document(
#     bot: Bot,
#     chat_id: int,
#     file_path: str,
#     caption: Optional[str] = None,
# ):
#     if not os.path.exists(file_path):
#         log.error(f"File not found: {file_path}")
#         return None
    
#     for attempt in range(1, 4):
#         try:
#             return await bot.send_document(
#                 chat_id, 
#                 document=FSInputFile(file_path), 
#                 caption=caption,
#                 request_timeout=120
#             )
#         except TelegramBadRequest as e:
#             error_msg = str(e).lower()
#             if "internal" in error_msg and attempt < 3:
#                 wait_time = 3 * attempt
#                 log.warning(f"Telegram internal error, retry {attempt}/3 in {wait_time}s")
#                 await asyncio.sleep(wait_time)
#                 continue
#             if attempt == 3:
#                 log.exception(f"send_document failed chat_id={chat_id}")
#                 return None
#         except TelegramRetryAfter as e:
#             if attempt < 3:
#                 await asyncio.sleep(e.retry_after)
#                 continue
#             else:
#                 log.exception(f"send_document failed after retry chat_id={chat_id}")
#                 return None
#         except TelegramForbiddenError:
#             await _maybe_delete_user(chat_id)
#             return None
#         except Exception as e:
#             if "timeout" in str(e).lower() and attempt < 3:
#                 wait_time = 5 * attempt
#                 log.warning(f"Timeout, retry {attempt}/3 in {wait_time}s")
#                 await asyncio.sleep(wait_time)
#                 continue
#             log.exception(f"send_document failed chat_id={chat_id}")
#             return None
#     return None

# # async def safe_edit_text(
# #     message: Message,
# #     text: str,
# #     *,
# #     reply_markup: Optional[InlineKeyboardMarkup] = None,
# #     parse_mode: str = "HTML",
# #     disable_web_page_preview: bool = False,
# # ):
# #     try:
# #         return await message.edit_text(
# #             text, 
# #             reply_markup=reply_markup, 
# #             parse_mode=parse_mode, 
# #             disable_web_page_preview=disable_web_page_preview
# #         )
# #     except TelegramBadRequest as e:
# #         if _is_not_modified(e):
# #             if reply_markup is not None:
# #                 try:
# #                     return await message.edit_reply_markup(reply_markup=reply_markup)
# #                 except TelegramBadRequest as e2:
# #                     if _is_not_modified(e2):
# #                         return message
# #                     log.exception("edit_reply_markup bad request (not 'modified')")
# #                 except Exception:
# #                     log.exception("edit_reply_markup failed")
# #             return message
# #         log.exception("edit_text bad request")
# #     except TelegramRetryAfter as e:
# #         await asyncio.sleep(e.retry_after)
# #         try:
# #             return await message.edit_text(
# #                 text, 
# #                 reply_markup=reply_markup, 
# #                 parse_mode=parse_mode,
# #                 disable_web_page_preview=disable_web_page_preview
# #             )
# #         except Exception:
# #             log.exception("edit_text failed after retry")
# #     except TelegramForbiddenError:
# #         return None
# #     except Exception:
# #         log.exception("edit_text failed")
# #     return None

# # Только ИСПРАВЛЕННАЯ функция safe_edit_text

# async def safe_edit_text(
#     message: Message,
#     text: str,
#     *,
#     reply_markup: Optional[InlineKeyboardMarkup] = None,
#     parse_mode: str = "HTML",
#     disable_web_page_preview: bool = False,
# ):
#     try:
#         return await message.edit_text(
#             text, 
#             reply_markup=reply_markup, 
#             parse_mode=parse_mode, 
#             disable_web_page_preview=disable_web_page_preview
#         )
#     except TelegramBadRequest as e:
#         error_msg = str(e).lower()
        
#         # ✅ НОВОЕ: message not found - молча игнорируем
#         if "message to edit not found" in error_msg or "message can't be edited" in error_msg:
#             log.debug(f"Message not found or can't be edited: {e}")
#             return message
        
#         if _is_not_modified(e):
#             if reply_markup is not None:
#                 try:
#                     return await message.edit_reply_markup(reply_markup=reply_markup)
#                 except TelegramBadRequest as e2:
#                     if _is_not_modified(e2):
#                         return message
#                     log.exception("edit_reply_markup bad request (not 'modified')")
#                 except Exception:
#                     log.exception("edit_reply_markup failed")
#             return message
#         log.exception("edit_text bad request")
#     except TelegramRetryAfter as e:
#         await asyncio.sleep(e.retry_after)
#         try:
#             return await message.edit_text(
#                 text, 
#                 reply_markup=reply_markup, 
#                 parse_mode=parse_mode,
#                 disable_web_page_preview=disable_web_page_preview
#             )
#         except Exception:
#             log.exception("edit_text failed after retry")
#     except TelegramForbiddenError:
#         return None
#     except Exception:
#         log.exception("edit_text failed")
#     return None

# async def safe_edit_reply_markup(
#     message: Message,
#     reply_markup: Optional[InlineKeyboardMarkup] = None,
# ):
#     try:
#         return await message.edit_reply_markup(reply_markup=reply_markup)
#     except TelegramBadRequest as e:
#         if _is_not_modified(e):
#             return message
#         log.exception("edit_reply_markup bad request")
#     except TelegramRetryAfter as e:
#         await asyncio.sleep(e.retry_after)
#         try:
#             return await message.edit_reply_markup(reply_markup=reply_markup)
#         except Exception:
#             log.exception("edit_reply_markup failed after retry")
#     except TelegramForbiddenError:
#         return None
#     except Exception:
#         log.exception("edit_reply_markup failed")
#     return None

# async def safe_delete_message(bot: Bot, chat_id: int, message_id: int):
#     try:
#         await bot.delete_message(chat_id, message_id)
#     except TelegramBadRequest:
#         pass
#     except TelegramForbiddenError:
#         await _maybe_delete_user(chat_id)
#     except Exception:
#         log.exception("delete_message failed chat_id=%s", chat_id)

# async def safe_send_video(
#     bot: Bot,
#     chat_id: int,
#     video: Union[FSInputFile, bytes],
#     caption: Optional[str] = None,
#     reply_markup: Optional[InlineKeyboardMarkup] = None,
#     parse_mode: str = "HTML",
# ) -> Optional[Message]:
#     try:
#         if isinstance(video, BytesIO):
#             with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
#                 temp_file.write(video.getvalue())
#                 video_file = FSInputFile(temp_file.name)
#         else:
#             video_file = video
#         return await bot.send_video(chat_id, video=video_file, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
#     except TelegramRetryAfter as e:
#         await asyncio.sleep(e.retry_after)
#         try:
#             return await bot.send_video(chat_id, video=video_file, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
#         except TelegramForbiddenError:
#             await _maybe_delete_user(chat_id)
#         except Exception:
#             log.exception("send_video failed after retry chat_id=%s", chat_id)
#     except TelegramForbiddenError:
#         await _maybe_delete_user(chat_id)
#     except Exception as e:
#         log.exception("send_video failed chat_id=%s: %s", chat_id, str(e))
#     finally:
#         if isinstance(video, BytesIO) and 'temp_file' in locals():
#             os.unlink(temp_file.name)
#     return None

# services/telegram_safe.py
from __future__ import annotations
import asyncio
import logging
import tempfile
import html
from typing import Optional, Union
from io import BytesIO
import os
from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    Message,
    InaccessibleMessage,  # ✅ ДОБАВЛЕНО
)
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramBadRequest,
    TelegramNetworkError
)

from db.engine import SessionLocal
from db.models import User
from sqlalchemy import delete

log = logging.getLogger("tg_safe")

def escape_html(text: str) -> str:
    """Экранирует HTML-символы для безопасной вставки в HTML-разметку Telegram"""
    if not text:
        return ""
    return html.escape(str(text))

# ---------------------- внутренние утилиты ----------------------
async def _maybe_delete_user(chat_id: int):
    try:
        async with SessionLocal() as s:
            await s.execute(delete(User).where(User.chat_id == chat_id))
            await s.commit()
        log.info("user_deleted_due_block chat_id=%s", chat_id)
    except Exception:
        log.exception("failed to delete user on forbidden chat_id=%s", chat_id)

def _is_not_modified(err: Exception) -> bool:
    txt = str(err).lower()
    return "message is not modified" in txt or "message can't be edited" in txt

# ---------------------- публичные safe-обёртки ----------------------
async def safe_answer(cb: CallbackQuery, text: Optional[str] = None, show_alert: bool = False):
    """✅ УЛУЧШЕНО: с retry для сетевых ошибок"""
    max_attempts = 3
    
    for attempt in range(1, max_attempts + 1):
        try:
            await cb.answer(text=text, show_alert=show_alert, cache_time=60)
            return
            
        except TelegramBadRequest:
            return
            
        except TelegramNetworkError as e:
            if attempt < max_attempts:
                wait_time = 0.5 * attempt
                log.warning(
                    f"Network error in cb.answer, retry {attempt}/{max_attempts} "
                    f"in {wait_time}s: {str(e)[:100]}"
                )
                await asyncio.sleep(wait_time)
                continue
            else:
                log.error(f"cb.answer failed after {max_attempts} attempts: {str(e)[:100]}")
                return
                
        except TelegramRetryAfter as e:
            if attempt < max_attempts:
                log.warning(f"Rate limit in cb.answer, waiting {e.retry_after}s")
                await asyncio.sleep(e.retry_after)
                continue
            else:
                log.error(f"cb.answer rate limited after {max_attempts} attempts")
                return
                
        except Exception as e:
            log.exception(f"cb.answer unexpected error: {str(e)[:100]}")
            return

async def safe_send_text(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
):
    try:
        return await bot.send_message(
            chat_id, 
            text, 
            reply_markup=reply_markup, 
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await bot.send_message(
                chat_id, 
                text, 
                reply_markup=reply_markup, 
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        except TelegramForbiddenError:
            await _maybe_delete_user(chat_id)
        except Exception:
            log.exception("send_message failed after retry chat_id=%s", chat_id)
    except TelegramForbiddenError:
        await _maybe_delete_user(chat_id)
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        if "can't parse entities" in error_msg or "unsupported start tag" in error_msg:
            log.error(f"HTML parse error for chat {chat_id}, text preview: {text[:100]}")
            try:
                return await bot.send_message(
                    chat_id,
                    text,
                    reply_markup=reply_markup,
                    parse_mode=None,
                    disable_web_page_preview=disable_web_page_preview,
                )
            except Exception:
                log.exception("send_message failed without HTML chat_id=%s", chat_id)
        else:
            log.exception("send_message TelegramBadRequest chat_id=%s", chat_id)
    except Exception:
        log.exception("send_message failed chat_id=%s", chat_id)
    return None

async def safe_send_photo(
    bot: Bot,
    chat_id: int,
    photo: Union[FSInputFile, bytes],
    caption: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
) -> Optional[Message]:
    # ✅ ДОБАВЛЕНО: проверка существования файла
    if isinstance(photo, FSInputFile):
        if not os.path.exists(photo.path):
            log.error(f"Photo file does not exist: {photo.path}")
            return None
        
        try:
            file_size = os.path.getsize(photo.path)
            # ✅ ДОБАВЛЕНО: проверка на пустой файл
            if file_size == 0:
                log.error(f"Photo file is empty: {photo.path}")
                return None
            
            file_size_mb = file_size / (1024 * 1024)
            if file_size_mb > 10:
                log.warning(f"Photo too large ({file_size_mb:.2f} MB), sending as document")
                return await safe_send_document(bot, chat_id, photo.path, caption=caption)
        except Exception as e:
            log.error(f"Error checking photo file: {e}")
            return None
    
    for attempt in range(1, 4):
        try:
            return await bot.send_photo(
                chat_id, 
                photo=photo, 
                caption=caption, 
                reply_markup=reply_markup, 
                parse_mode=parse_mode
            )
        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            
            # ✅ ДОБАВЛЕНО: обработка пустого файла
            if "file must be non-empty" in error_msg:
                log.error(f"Telegram rejected empty file for chat {chat_id}")
                return None
            
            if "internal" in error_msg and attempt < 3:
                wait_time = 3 * attempt
                log.warning(f"Telegram internal error, retry {attempt}/3 in {wait_time}s for chat {chat_id}")
                await asyncio.sleep(wait_time)
                continue
            if attempt == 3:
                log.error(f"Failed to send photo after 3 attempts, trying as document: {error_msg[:100]}")
                if isinstance(photo, FSInputFile):
                    try:
                        return await safe_send_document(bot, chat_id, photo.path, caption=caption)
                    except Exception as doc_err:
                        log.error(f"Failed to send as document too: {doc_err}")
                log.exception(f"send_photo failed chat_id={chat_id}")
                return None
        except TelegramRetryAfter as e:
            if attempt < 3:
                await asyncio.sleep(e.retry_after)
                continue
            else:
                log.exception(f"send_photo failed after retry chat_id={chat_id}")
                return None
        except TelegramForbiddenError:
            await _maybe_delete_user(chat_id)
            return None
        except Exception as e:
            if "timeout" in str(e).lower() and attempt < 3:
                wait_time = 5 * attempt
                log.warning(f"Timeout, retry {attempt}/3 in {wait_time}s for chat {chat_id}")
                await asyncio.sleep(wait_time)
                continue
            log.exception(f"send_photo failed chat_id={chat_id}")
            return None
    return None

async def safe_send_document(
    bot: Bot,
    chat_id: int,
    file_path: str,
    caption: Optional[str] = None,
):
    # ✅ ДОБАВЛЕНО: проверка существования и размера файла
    if not os.path.exists(file_path):
        log.error(f"Document file not found: {file_path}")
        return None
    
    try:
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            log.error(f"Document file is empty: {file_path}")
            return None
    except Exception as e:
        log.error(f"Error checking document file: {e}")
        return None
    
    for attempt in range(1, 4):
        try:
            return await bot.send_document(
                chat_id, 
                document=FSInputFile(file_path), 
                caption=caption,
                request_timeout=120
            )
        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            
            # ✅ ДОБАВЛЕНО: обработка пустого файла
            if "file must be non-empty" in error_msg:
                log.error(f"Telegram rejected empty document: {file_path}")
                return None
            
            if "internal" in error_msg and attempt < 3:
                wait_time = 3 * attempt
                log.warning(f"Telegram internal error, retry {attempt}/3 in {wait_time}s")
                await asyncio.sleep(wait_time)
                continue
            if attempt == 3:
                log.exception(f"send_document failed chat_id={chat_id}")
                return None
        except TelegramRetryAfter as e:
            if attempt < 3:
                await asyncio.sleep(e.retry_after)
                continue
            else:
                log.exception(f"send_document failed after retry chat_id={chat_id}")
                return None
        except TelegramForbiddenError:
            await _maybe_delete_user(chat_id)
            return None
        except Exception as e:
            if "timeout" in str(e).lower() and attempt < 3:
                wait_time = 5 * attempt
                log.warning(f"Timeout, retry {attempt}/3 in {wait_time}s")
                await asyncio.sleep(wait_time)
                continue
            log.exception(f"send_document failed chat_id={chat_id}")
            return None
    return None

async def safe_edit_text(
    message: Message,
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    disable_web_page_preview: bool = True,
) -> Optional[Message]:
    """
    ✅ УЛУЧШЕНО: обработка всех типов ошибок редактирования
    """
    if not text or not text.strip():
        log.warning("safe_edit_text: empty text provided")
        return None

    try:
        return await message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        
        # ✅ Сообщение не найдено - молча игнорируем
        if "message to edit not found" in error_msg:
            log.debug(
                "safe_edit_text: message not found (deleted or too old), "
                f"chat_id={message.chat.id}, message_id={message.message_id}"
            )
            return None
        
        # ✅ Сообщение не изменилось - молча игнорируем
        if "message is not modified" in error_msg:
            log.debug(
                "safe_edit_text: message not modified, "
                f"chat_id={message.chat.id}, message_id={message.message_id}"
            )
            return None
        
        # ✅ Сообщение слишком старое
        if "message can't be edited" in error_msg:
            log.debug(
                "safe_edit_text: message too old to edit, "
                f"chat_id={message.chat.id}, message_id={message.message_id}"
            )
            return None
        
        # ✅ Слишком длинное сообщение
        if "message is too long" in error_msg:
            log.warning(
                "safe_edit_text: message too long, truncating, "
                f"chat_id={message.chat.id}, length={len(text)}"
            )
            # Пробуем отправить урезанную версию
            try:
                truncated = text[:4000] + "\n\n... (обрезано)"
                return await message.edit_text(
                    text=truncated,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview,
                )
            except Exception:
                return None
        
        # ✅ Проблемы с parse_mode
        if "can't parse" in error_msg or "parse entities" in error_msg:
            log.warning(
                "safe_edit_text: parse error, retrying without parse_mode, "
                f"chat_id={message.chat.id}, error={e}"
            )
            try:
                return await message.edit_text(
                    text=text,
                    parse_mode=None,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview,
                )
            except Exception:
                return None
        
        # ✅ Другие ошибки - логируем
        log.error(
            "edit_text bad request: %s, chat_id=%s, message_id=%s",
            e,
            message.chat.id,
            message.message_id,
            exc_info=False  # ✅ Без полного traceback
        )
        return None
        
    except TelegramRetryAfter as e:
        log.warning(
            f"safe_edit_text: rate limit hit, retry_after={e.retry_after}s, "
            f"chat_id={message.chat.id}"
        )
        await asyncio.sleep(e.retry_after)
        try:
            return await message.edit_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
        except Exception:
            return None
            
    except TelegramNetworkError as e:
        log.warning(
            f"safe_edit_text: network error, chat_id={message.chat.id}, error={e}"
        )
        return None
        
    except Exception as e:
        log.exception(
            "safe_edit_text: unexpected error, "
            f"chat_id={message.chat.id}, message_id={message.message_id}"
        )
        return None

async def safe_edit_reply_markup(
    message: Message,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
):
    if isinstance(message, InaccessibleMessage):
        log.warning("Attempted to edit inaccessible message markup")
        return None
    
    try:
        return await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if _is_not_modified(e):
            return message
        log.exception("edit_reply_markup bad request")
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await message.edit_reply_markup(reply_markup=reply_markup)
        except Exception:
            log.exception("edit_reply_markup failed after retry")
    except TelegramForbiddenError:
        return None
    except Exception:
        log.exception("edit_reply_markup failed")
    return None

async def safe_delete_message(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass
    except TelegramForbiddenError:
        await _maybe_delete_user(chat_id)
    except Exception:
        log.exception("delete_message failed chat_id=%s", chat_id)

async def safe_send_video(
    bot: Bot,
    chat_id: int,
    video: Union[FSInputFile, bytes],
    caption: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
) -> Optional[Message]:
    try:
        if isinstance(video, BytesIO):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
                temp_file.write(video.getvalue())
                video_file = FSInputFile(temp_file.name)
        else:
            video_file = video
        return await bot.send_video(chat_id, video=video_file, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await bot.send_video(chat_id, video=video_file, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramForbiddenError:
            await _maybe_delete_user(chat_id)
        except Exception:
            log.exception("send_video failed after retry chat_id=%s", chat_id)
    except TelegramForbiddenError:
        await _maybe_delete_user(chat_id)
    except Exception as e:
        log.exception("send_video failed chat_id=%s: %s", chat_id, str(e))
    finally:
        if isinstance(video, BytesIO) and 'temp_file' in locals():
            os.unlink(temp_file.name)
    return None