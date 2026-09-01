import os
import asyncio
import logging
from datetime import datetime

# Настройки базы данных
DB_NAME = "bot_database"
DB_USER = "postgres"
DB_PASS = "asddsa123"
BACKUP_DIR = "data/backups"

# Путь к pg_dump
PG_DUMP_PATH = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"

os.makedirs(BACKUP_DIR, exist_ok=True)

def cleanup_old_backups(max_files=10):
    """Удаляет старые бэкапы, оставляя только свежие."""
    try:
        files = [
            os.path.join(BACKUP_DIR, f) 
            for f in os.listdir(BACKUP_DIR) 
            if f.startswith("backup_full_") and f.endswith(".sql")
        ]
        files.sort(key=os.path.getctime)
        
        while len(files) > max_files:
            file_to_delete = files.pop(0)
            os.remove(file_to_delete)
            logging.info(f"🧹 [Бэкапер] Удален старый дамп: {file_to_delete}")
            
    except Exception as e:
        logging.error(f"❌ [Бэкапер] Ошибка при очистке старых файлов: {e}")

# 🔥 Эта функция теперь принимает аргументы от APScheduler
async def create_backup(bot, admin_id, is_full=True):
    """Создает полный слепок базы данных. Вызывается APScheduler'ом."""
    now = datetime.now().strftime("%Y_%m_%d_%H_%M")
    backup_file = os.path.join(BACKUP_DIR, f"backup_full_{now}.sql")
    
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS
    
    command = [
        PG_DUMP_PATH,
        "-U", DB_USER,
        "-d", DB_NAME,
        "--clean",
        "--if-exists",
        "-f", backup_file
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            logging.info(f"✅ [Бэкапер] Успех! Файл сохранен: {backup_file}")
            cleanup_old_backups(max_files=10)
            
            # Закомментируй следующую строчку, если не хочешь, чтобы бот спамил тебе в ЛС каждый час
            # await bot.send_message(admin_id, f"💾 Авто-бэкап успешно завершен. Файлов в архиве: 10.")
        else:
            error_msg = stderr.decode('cp1251', errors='ignore')
            logging.error(f"❌ [Бэкапер] Сбой pg_dump: {error_msg}")
            await bot.send_message(admin_id, f"❌ <b>ОШИБКА БЭКАПА:</b>\n<code>{error_msg}</code>", parse_mode="HTML")
            
    except Exception as e:
        logging.error(f"❌ [Бэкапер] Критическая ошибка: {e}")