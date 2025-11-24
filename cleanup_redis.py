import asyncio
import os
import time
import logging
import shutil
from pathlib import Path

import redis.asyncio as aioredis
from core.config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cleanup")


async def cleanup_fsm_old_states():
    """Очистка FSM с защитой от бесконечного цикла"""
    r = aioredis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB_FSM)
    
    try:
        cursor = 0
        deleted = 0
        checked = 0
        max_iterations = 1000
        iteration = 0
        
        while True:
            cursor, keys = await r.scan(cursor, match="fsm:*", count=100)
            iteration += 1
            
            for key in keys:
                checked += 1
                try:
                    ttl = await r.ttl(key)
                    if ttl == -1:
                        await r.expire(key, 86400)
                        deleted += 1
                except Exception:
                    pass
            
            if cursor == 0 or iteration >= max_iterations:
                if iteration >= max_iterations:
                    log.warning(f"⚠️ FSM cleanup stopped at {max_iterations} iterations")
                break
        
        log.info(f"✅ FSM cleanup: checked={checked}, set_ttl={deleted}")
    
    except Exception as e:
        log.error(f"❌ FSM cleanup error: {e}")
    finally:
        await r.aclose()


async def _cleanup_directory(directory: Path, max_age_hours: float, pattern: str = "*"):
    """Универсальная функция очистки директории"""
    if not directory.exists():
        log.info(f"📁 Directory {directory} doesn't exist")
        return
    
    now = time.time()
    max_age = max_age_hours * 3600
    deleted = 0
    errors = 0
    freed_mb = 0
    
    try:
        for file_path in directory.glob(pattern):
            if not file_path.is_file():
                continue
            
            try:
                file_age = now - file_path.stat().st_mtime
                
                if file_age > max_age:
                    size_mb = file_path.stat().st_size / (1024 * 1024)
                    file_path.unlink()
                    deleted += 1
                    freed_mb += size_mb
            except Exception as e:
                errors += 1
                if errors < 5:
                    log.warning(f"⚠️ Error deleting {file_path}: {e}")
        
        log.info(f"✅ Cleanup {directory}: deleted={deleted} files (>{max_age_hours}h), freed={freed_mb:.2f}MB")
    
    except Exception as e:
        log.error(f"❌ Cleanup {directory} error: {e}")


async def emergency_cleanup_if_needed():
    """Экстренная очистка если диск заполнен >80%"""
    try:
        stat = shutil.disk_usage("/app")
        used_percent = (stat.used / stat.total) * 100
        
        if used_percent > 80:
            log.warning(f"🚨 Disk usage at {used_percent:.1f}% - emergency cleanup!")
            
            # Статистика ДО очистки
            before_free_gb = stat.free / (1024**3)
            
            # Уведомление админу
            if settings.ADMIN_ID:
                try:
                    from aiogram import Bot
                    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                    await bot.send_message(
                        settings.ADMIN_ID,
                        f"🚨 <b>CRITICAL</b>: Disk usage at {used_percent:.1f}%!\n\n"
                        f"📊 Total: {stat.total / (1024**3):.1f} GB\n"
                        f"📊 Used: {stat.used / (1024**3):.1f} GB\n"
                        f"📊 Free: {stat.free / (1024**3):.1f} GB\n\n"
                        f"🧹 Deleting files older than 2 minutes...",
                        parse_mode="HTML"
                    )
                    await bot.session.close()
                except Exception as e:
                    log.error(f"Failed to send disk alert: {e}")
            
            # ✅ АГРЕССИВНО: удалить ВСЕ файлы старше 2 МИНУТ (было 5)
            await _cleanup_directory(Path("/tmp/nanobanana"), max_age_hours=0.033, pattern="*")  # ~2 мин
            await _cleanup_directory(Path("/app/temp_inputs"), max_age_hours=0.033, pattern="*")  # ~2 мин
            
            # Статистика ПОСЛЕ очистки
            stat_after = shutil.disk_usage("/app")
            after_free_gb = stat_after.free / (1024**3)
            freed_gb = after_free_gb - before_free_gb
            new_used_percent = (stat_after.used / stat_after.total) * 100
            
            log.info(f"✅ Emergency cleanup: freed {freed_gb:.2f} GB, now {new_used_percent:.1f}% used")
            
            # Уведомление об успехе
            if settings.ADMIN_ID and freed_gb > 0:
                try:
                    from aiogram import Bot
                    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                    await bot.send_message(
                        settings.ADMIN_ID,
                        f"✅ <b>Emergency cleanup completed</b>\n\n"
                        f"🗑️ Freed: {freed_gb:.2f} GB\n"
                        f"💾 Disk now: {new_used_percent:.1f}% used\n"
                        f"📊 Free: {after_free_gb:.1f} GB",
                        parse_mode="HTML"
                    )
                    await bot.session.close()
                except Exception:
                    pass
        else:
            log.info(f"💾 Disk: {used_percent:.1f}% used")
    except Exception as e:
        log.error(f"❌ Emergency cleanup error: {e}")


async def cleanup_old_temp_files():
    """
    ✅ АГРЕССИВНАЯ очистка temp файлов
    /tmp/nanobanana - 10 минут (было 30)
    /app/temp_inputs - 3 минуты (было 5)
    """
    # /tmp/nanobanana (результаты) - 10 минут
    temp_dir = Path("/tmp/nanobanana")
    if temp_dir.exists():
        await _cleanup_directory(temp_dir, max_age_hours=0.17, pattern="*")  # ✅ 10 минут
    
    # /app/temp_inputs - 3 минуты
    temp_inputs = Path("/app/temp_inputs")
    if temp_inputs.exists():
        await _cleanup_directory(temp_inputs, max_age_hours=0.05, pattern="*")  # ✅ 3 минуты


async def cleanup_old_redis_markers():
    """Очистка старых маркеров в Redis"""
    r = aioredis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB_CACHE)
    
    try:
        deleted = 0
        
        # Очистка wb:lock:*
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match="wb:lock:*", count=100)
            for key in keys:
                try:
                    ttl = await r.ttl(key)
                    if ttl == -1 or ttl == -2:
                        await r.delete(key)
                        deleted += 1
                except Exception:
                    pass
            if cursor == 0:
                break
        
        # Очистка task:pending:*
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match="task:pending:*", count=100)
            for key in keys:
                try:
                    ttl = await r.ttl(key)
                    if ttl == -1:
                        await r.delete(key)
                        deleted += 1
                except Exception:
                    pass
            if cursor == 0:
                break
        
        log.info(f"✅ Redis markers cleanup: deleted={deleted}")
    
    except Exception as e:
        log.error(f"❌ Redis markers cleanup error: {e}")
    finally:
        await r.aclose()


async def main():
    log.info("🧹 Starting cleanup...")
    
    await emergency_cleanup_if_needed()
    await cleanup_fsm_old_states()
    await cleanup_old_temp_files()
    await cleanup_old_redis_markers()
    
    log.info("✅ Cleanup completed")


if __name__ == "__main__":
    asyncio.run(main())