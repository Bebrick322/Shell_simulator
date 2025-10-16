import tkinter as tk
from tkinter import scrolledtext
import re
import getpass
import socket
import argparse
import json
import os
import sys
import zipfile
from io import BytesIO
import base64

def parse_arguments(line):
    """Разбирает строку на аргументы, корректно обрабатывая кавычки."""
    pattern = r'"[^"]*"|\'[^\']*\'|[^\s\'"]+'
    tokens = re.findall(pattern, line.strip())
    args = []
    for token in tokens:
        if len(token) >= 2 and ((token.startswith('"') and token.endswith('"')) or
                                (token.startswith("'") and token.endswith("'"))):
            args.append(token[1:-1])
        else:
            args.append(token)
    return args


class VirtualFileSystem:
    def __init__(self, zip_path=None):
        self.file_tree = {}  
        self.current_dir = "/"
        if zip_path:
            self.load_from_zip(zip_path)

    def load_from_zip(self, zip_path):
        """Загружает структуру файлов из ZIP-архива в память."""
        if not os.path.isfile(zip_path):
            raise FileNotFoundError(f"VFS archive not found: {zip_path}")

        try:
            with open(zip_path, 'rb') as f:
                data = f.read()
            archive = zipfile.ZipFile(BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError(f"Invalid or corrupted ZIP file: {zip_path}")

        for file_info in archive.infolist():
            path = file_info.filename.replace("\\", "/")
            if path.endswith("/"):
                self._add_dir(path.rstrip("/"))
            else:
                raw = archive.read(file_info)
                # Попытка декодирования как text (utf-8)
                try:
                    text = raw.decode('utf-8')
                    # Считать как текстовый файл
                    self._add_file(path, text, binary=False)
                except Exception:
                    # Для бинарных данных — хранить в base64
                    b64 = base64.b64encode(raw).decode('ascii')
                    self._add_file(path, b64, binary=True)

        # Гарантируется существование корня
        if "/" not in self.file_tree:
            self.file_tree["/"] = {"type": "dir"}

    def _add_dir(self, path):
        parts = path.strip("/").split("/") if path.strip("/") else []
        current = ""
        for part in parts:
            if not current:
                current = "/" + part
            else:
                current = current + "/" + part
            if current not in self.file_tree:
                self.file_tree[current] = {"type": "dir"}

    def _add_file(self, path, content="", binary=False):
        parent = "/".join(path.split("/")[:-1]) or "/"
        if parent != "" and parent not in self.file_tree:
            self._add_dir(parent)
        elif parent == "":
            self._add_dir("/")
        entry = {"type": "file", "content": content}
        if binary:
            entry["binary"] = True
        self.file_tree[self._normalize_path(path)] = entry

    def list_dir(self, path):
        """Возвращает список элементов указанной директории."""
        target = path if path.startswith("/") else self._normalize_path(self.current_dir + "/" + path)
        target = self._normalize_path(target)

        if target not in self.file_tree or self.file_tree[target]["type"] != "dir":
            return None

        prefix = target + "/" if target != "/" else "/"
        items = []
        for full_path in self.file_tree:
            if full_path == target:
                continue
            if full_path.startswith(prefix):
                rel = full_path[len(prefix):]
                if "/" not in rel:
                    items.append(rel or full_path.split("/")[-1])
        return sorted(set(items))

    def change_dir(self, path):
        """Изменяет текущую директорию."""
        target = path if path.startswith("/") else self._normalize_path(self.current_dir + "/" + path)
        target = self._normalize_path(target)

        if target in self.file_tree and self.file_tree[target]["type"] == "dir":
            self.current_dir = target
            return True
        return False

    def _normalize_path(self, path):
        """Нормализует путь, обрабатывая ., .."""
        parts = []
        for part in path.strip("/").split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part and part != ".":
                parts.append(part)
        return "/" + "/".join(parts) if parts else "/"

    def get_content(self, path):
        """Возвращает содержимое файла по относительному или абсолютному пути.
           Если файл бинарный — возвращает None (чтобы команды текста корректно реагировали)."""
        full_path = self._resolve_path(path)
        if full_path in self.file_tree and self.file_tree[full_path]["type"] == "file":
            entry = self.file_tree[full_path]
            if entry.get("binary"):
                return None
            return entry.get("content", "")
        return None

    def create_file(self, path):
        """Создаёт новый пустой файл в VFS."""
        full_path = self._resolve_path(path)
        parent = "/".join(full_path.split("/")[:-1]) or "/"
        if parent not in self.file_tree or self.file_tree[parent]["type"] != "dir":
            return False
        self.file_tree[full_path] = {"type": "file", "content": ""}
        return True

    def _resolve_path(self, path):
        """Преобразует относительный путь в абсолютный."""
        if path.startswith("/"):
            return self._normalize_path(path)
        return self._normalize_path(self.current_dir + "/" + path)


class ShellEmulator:
    def __init__(self, root, vfs_path, startup_script, config_error=None):
        self.root = root
        self.vfs_path = vfs_path
        self.startup_script = startup_script
        self.vfs = VirtualFileSystem()
        self.command_history = []
        self.config_error = config_error

        # Получение данных пользователя и хоста для заголовка и приглашения
        self.username = getpass.getuser()
        self.hostname = socket.gethostname()

        # Настройка окна
        root.title(f"Эмулятор - [{self.username}@{self.hostname}]")
        root.geometry("800x600")

        # Область вывода
        self.text_area = scrolledtext.ScrolledText(root, state='disabled', wrap=tk.WORD, font=("Courier", 10))
        self.text_area.pack(expand=True, fill='both', padx=10, pady=10)

        # Строка ввода
        input_frame = tk.Frame(root)
        input_frame.pack(fill='x', padx=10, pady=5)

        self.prompt_label = tk.Label(input_frame, text="")
        self.prompt_label.pack(side='left')

        self.entry = tk.Entry(input_frame)
        self.entry.pack(side='left', fill='x', expand=True)
        self.entry.bind('<Return>', self.run_command)
        self.entry.bind('<FocusIn>', self.on_focus_in)
        self.entry.focus()

        # Загрузка VFS из ZIP-архива (в памяти)
        if self.vfs_path:
            self.load_vfs()
        else:
            self.show_output("[VFS] Не указан путь к архиву.")

        # Отладочный вывод конфигурации
        self.debug_print_config()

        # Выполнение стартового скрипта, если задан
        if self.startup_script:
            self.run_startup_script()

        self.update_prompt()
        self.print_prompt()

    def load_vfs(self):
        """Загружает VFS из указанного ZIP-файла."""
        try:
            temp_vfs = VirtualFileSystem(self.vfs_path)
            self.vfs.file_tree = temp_vfs.file_tree
            self.vfs.current_dir = temp_vfs.current_dir
            self.show_output(f"[VFS] Загружено: {self.vfs_path}")
        except Exception as e:
            self.show_error(f"[VFS] Ошибка загрузки: {e}")

    def debug_print_config(self):
        """Отображает параметры запуска в интерфейсе."""
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, "="*60 + "\n")
        self.text_area.insert(tk.END, "НАСТРОЙКИ ЭМУЛЯТОРА\n")
        self.text_area.insert(tk.END, f"VFS путь: {self.vfs_path or 'не задан'}\n")
        self.text_area.insert(tk.END, f"Стартовый скрипт: {self.startup_script or 'не задан'}\n")
        if self.config_error:
            self.text_area.insert(tk.END, f"Ошибка чтения конфига: {self.config_error}\n")
        if self.vfs.file_tree:
            self.text_area.insert(tk.END, "VFS: успешно загружена\n")
        self.text_area.insert(tk.END, "="*60 + "\n\n")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    def update_prompt(self):
        """Обновляет текст метки приглашения."""
        self.prompt_label.config(text=f"{self.username}@{self.hostname}:{self.vfs.current_dir}$ ")

    def print_prompt(self):
        """Добавляет приглашение ко вводу в область вывода."""
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, f"{self.username}@{self.hostname}:{self.vfs.current_dir}$ ")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    def run_startup_script(self):
        """Выполняет команды из стартового скрипта построчно."""
        if not os.path.isfile(self.startup_script):
            self.show_error(f"Startup script not found: {self.startup_script}")
            return

        try:
            with open(self.startup_script, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            self.show_error(f"Cannot read startup script '{self.startup_script}': {e}")
            return

        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, f"# Выполнение стартового скрипта: {self.startup_script}\n")
        self.text_area.config(state='disabled')

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Имитация ввода пользователем
            self.text_area.config(state='normal')
            self.text_area.insert(tk.END, f"{self.username}@{self.hostname}:{self.vfs.current_dir}$ {line}\n")
            self.text_area.config(state='disabled')

            try:
                args = parse_arguments(line)
                if args:
                    self.command_history.append(line)
                    self.execute_command(args)
            except Exception as e:
                self.show_error(f"[Line {line_num}] Execution error: {e}")

        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, "# Конец выполнения стартового скрипта.\n\n")
        self.text_area.config(state='disabled')

    def on_focus_in(self, event):
        """Фокусировка на поле ввода."""
        self.entry.focus()

    def run_command(self, event=None):
        """Обработка ввода команды пользователем."""
        cmd_line = self.entry.get()
        self.entry.delete(0, tk.END)

        if cmd_line.strip():
            self.command_history.append(cmd_line)

        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, f"{self.username}@{self.hostname}:{self.vfs.current_dir}$ {cmd_line}\n")
        self.text_area.config(state='disabled')

        if not cmd_line.strip():
            self.print_prompt()
            return

        try:
            args = parse_arguments(cmd_line)
        except Exception as e:
            self.show_error(f"Parse error: {e}")
            self.print_prompt()
            return

        if not args:
            self.print_prompt()
            return

        self.execute_command(args)
        self.update_prompt()
        self.print_prompt()

    def execute_command(self, args):
        """Выполнение команды."""
        command = args[0]
        rest = args[1:]

        if command == "exit":
            if rest:
                self.show_error("exit: too many arguments")
            else:
                self.root.quit()
        elif command == "ls":
            target = rest[0] if rest else "."
            items = self.vfs.list_dir(target)
            if items is None:
                self.show_error(f"ls: cannot access '{target}': No such file or directory")
            else:
                # выводим построчно для читаемости
                if items:
                    for it in items:
                        self.show_output(it)
                else:
                    self.show_output("")
        elif command == "cd":
            if not rest:
                self.show_error("cd: missing argument")
            elif len(rest) > 1:
                self.show_error("cd: too many arguments")
            else:
                if not self.vfs.change_dir(rest[0]):
                    self.show_error(f"cd: no such directory: {rest[0]}")
        elif command == "tac":
            if len(rest) != 1:
                self.show_error("tac: wrong number of arguments")
            else:
                fname = rest[0]
                content = self.vfs.get_content(fname)
                if content is None:
                    self.show_error(f"tac: {fname}: No such file or/or file is binary")
                else:
                    lines = content.strip().split('\n')
                    self.show_output('\n'.join(reversed(lines)))
        elif command == "echo":
            self.show_output(" ".join(rest))
        elif command == "history":
            for i, cmd in enumerate(self.command_history, 1):
                self.show_output(f"{i}  {cmd}")
        elif command == "touch":
            if not rest:
                self.show_error("touch: missing file operand")
            else:
                for fname in rest:
                    if not self.vfs.create_file(fname):
                        self.show_error(f"touch: cannot touch '{fname}': No such file or directory")
        else:
            self.show_error(f"{command}: command not found")

    def show_output(self, msg):
        """Вывод результата выполнения команды."""
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, msg + "\n")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    def show_error(self, msg):
        """Вывод сообщения об ошибке."""
        self.text_area.config(state='normal')
        self.text_area.insert(tk.END, f"Error: {msg}\n")
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)


def load_config_from_file(config_path):
    """Чтение конфигурации из JSON-файла.
       Возвращает (config_dict, error_message)."""
    if not config_path:
        return {}, None
    if not os.path.isfile(config_path):
        return {}, f"Config file not found: {config_path}"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {
                'vfs_path': data.get('vfs_path'),
                'startup_script': data.get('startup_script')
            }, None
    except json.JSONDecodeError as je:
        return {}, f"JSON decode error: {je}"
    except Exception as e:
        return {}, f"Cannot read config: {e}"


def main():
    parser = argparse.ArgumentParser(description="Shell Emulator with VFS support.")
    parser.add_argument('--vfs', help="Путь к ZIP-архиву VFS")
    parser.add_argument('--script', help="Путь к стартовому скрипту")
    parser.add_argument('--config', help="Путь к конфигурационному файлу (JSON)")
    args = parser.parse_args()

    # Чтение конфигурации из файла (возвращает также ошибку чтения)
    config_data, config_error = load_config_from_file(args.config)

    # Приоритет: CLI > config file
    vfs_path = args.vfs or config_data.get('vfs_path')
    startup_script = args.script or config_data.get('startup_script')

    # Запуск GUI
    root = tk.Tk()
    app = ShellEmulator(root, vfs_path=vfs_path, startup_script=startup_script, config_error=config_error)
    root.mainloop()


if __name__ == "__main__":
    main()

