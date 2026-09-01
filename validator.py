import os
import ast
import importlib.util
import sys

# Форсируем UTF-8 для Windows
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Добавляем корень проекта в пути
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def is_module_available(module_name):
    """Физически проверяет, существует ли файл/библиотека для импорта"""
    try:
        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except ModuleNotFoundError:
        return False
    except Exception:
        return True

def run_validator():
    has_errors = False
    scanned_files = 0
    missing_modules = set()

    print("🧪 [VALIDATOR] Запуск умного AST-сканирования (Без выполнения кода)...\n")

    # Автоматически обходим ВСЕ папки в проекте
    for root, dirs, files in os.walk(project_root):
        # Игнорируем кэш, логи, бэкапы и старые проекты
        if any(ignore in root for ignore in ['.git', '__pycache__', 'venv', 'env', 'logs', 'data', 'tourner', 'tests']):
            continue

        for file in files:
            if not file.endswith('.py'):
                continue

            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, project_root)
            scanned_files += 1

            # 🛡 БРОНЕБОЙНОЕ ЧТЕНИЕ: Пытаемся открыть в UTF-8, при сбое падаем на Windows-1251
            source = None
            for encoding in ['utf-8', 'cp1251', 'utf-8-sig']:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        source = f.read()
                    break # Если прочиталось без ошибок, выходим из цикла
                except UnicodeDecodeError:
                    continue
            
            if source is None:
                # Если ничего не помогло, читаем грубо, игнорируя битые символы
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    source = f.read()

            try:
                # Читаем код как абстрактное дерево (ловит SyntaxError)
                tree = ast.parse(source, filename=rel_path)
            except SyntaxError as e:
                print(f"❌ [SyntaxError] в {rel_path} (Строка {e.lineno}): {e.msg}")
                has_errors = True
                continue

            # Ищем импорты абсолютно ВЕЗДЕ (и глобально, и внутри функций)
            for node in ast.walk(tree):
                module_to_check = None
                line_num = getattr(node, 'lineno', '?')

                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_to_check = alias.name.split('.')[0] 
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.level == 0: 
                        # Проверяем только абсолютные импорты проекта (core, handlers и т.д.)
                        module_to_check = node.module.split('.')[0]

                if module_to_check:
                    # Игнорируем стандартные библиотеки питона
                    if module_to_check in sys.builtin_module_names:
                        continue
                        
                    if not is_module_available(module_to_check):
                        error_msg = f"⚠️ [ОШИБКА ИМПОРТА] в {rel_path} (Строка {line_num}): Файл или модуль '{module_to_check}' не найден!"
                        if error_msg not in missing_modules:
                            print(error_msg)
                            missing_modules.add(error_msg)
                            has_errors = True

    print(f"\n📊 Просканировано файлов: {scanned_files}")
    if has_errors:
        print("🚨 [VALIDATOR] Проверка провалена. В коде есть битые импорты. Рестарт заблокирован!")
        sys.exit(1) 
    else:
        print("💎 [VALIDATOR] Целостность системы подтверждена. Все связи монолитны.")
        sys.exit(0)

if __name__ == "__main__":
    run_validator()