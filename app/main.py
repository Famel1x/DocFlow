"""FastAPI-приложение: парсер документов для подготовки FAQ через GigaChat."""

import copy
import logging
import os
import re
import shutil
import sys
import tempfile
import uuid
from typing import Any




from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.gigachat_client import gigachat_client
from app.models import (
    GigaChatSettings,
    GenerateRequest,
    GenerateResponse,
    TransformRequest,
    UpdateTableRequest,
    SaveConvertedTableRequest,
)

from app.parsers.docx_parser import DOCXParser
from app.parsers.pdf_parser import PDFParser
from app.parsers.pptx_parser import PPTXParser
from app.parsers.xlsx_parser import XLSXParser
from app.storage import storage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Document Parser for FAQ")

# Статические файлы
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    STATIC_DIR = os.path.join(BASE_DIR, "app", "static")
else:
    STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")



@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ─── Парсинг файлов ──────────────────────────────────────────────────────────


SUPPORTED_EXTENSIONS = {"pdf", "docx", "pptx", "xlsx"}

PARSERS = {
    "pdf": PDFParser,
    "docx": DOCXParser,
    "pptx": PPTXParser,
    "xlsx": XLSXParser,
}


def parse_file(file_path: str, filename: str) -> dict[str, Any]:
    """Парсит файл и возвращает структурированный контент."""
    ext = filename.rsplit(".", 1)[-1].lower()
    parser_class = PARSERS.get(ext)
    if not parser_class:
        raise ValueError(f"Неподдерживаемый формат: {ext}")

    parser = parser_class(file_path)
    content = parser.parse()

    # Разделяем контент на таблицы и текст
    tables = []
    text_blocks = []
    for item in content:
        if item["type"] == "table":
            tables.append({
                "value": item["value"],
                "merges": item.get("merges", [])
            })
        elif item["type"] == "text":
            text_blocks.append(item["value"])

    return {
        "filename": filename,
        "file_type": ext,
        "tables": tables,
        "original_tables": copy.deepcopy(tables),
        "text_blocks": text_blocks,
        "content": content,
    }




@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """Загрузка и парсинг файлов."""
    results = []

    for file in files:
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        # Сохраняем во временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            parsed = parse_file(tmp_path, file.filename)
            file_id = str(uuid.uuid4())[:8]
            parsed["file_id"] = file_id

            # Сохраняем в хранилище
            storage.add_file(file_id, parsed)

            results.append({
                "file_id": file_id,
                "filename": parsed["filename"],
                "file_type": parsed["file_type"],
                "tables_count": len(parsed["tables"]),
                "text_blocks_count": len(parsed["text_blocks"]),
            })
        except Exception as e:
            logger.error(f"Ошибка парсинга {file.filename}: {e}")
            results.append({
                "file_id": "",
                "filename": file.filename,
                "file_type": ext,
                "error": str(e),
            })
        finally:
            os.unlink(tmp_path)

    return {"files": results}


@app.get("/api/files")
async def get_files():
    """Список загруженных файлов."""
    files_list = []
    for file_id, data in storage.get_all_files().items():
        files_list.append({
            "file_id": file_id,
            "filename": data["filename"],
            "file_type": data["file_type"],
            "tables_count": len(data["tables"]),
            "text_blocks_count": len(data["text_blocks"]),
        })
    return {"files": files_list}


@app.get("/api/files/{file_id}")
async def get_file(file_id: str):
    """Получить полные данные файла."""
    data = storage.get_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return data


@app.get("/api/files/{file_id}/tables/{table_index}")
async def get_table(file_id: str, table_index: int):
    """Получить конкретную таблицу из файла."""
    data = storage.get_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")

    tables = data["tables"]
    if table_index < 0 or table_index >= len(tables):
        raise HTTPException(status_code=404, detail="Таблица не найдена")

    return {
        "table": tables[table_index],
        "table_index": table_index,
        "total_tables": len(tables),
        "filename": data["filename"],
    }


@app.put("/api/files/{file_id}/tables/{table_index}")
async def update_table(file_id: str, table_index: int, req: UpdateTableRequest):
    """Обновить отредактированную таблицу."""
    data = storage.get_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")
    tables = data["tables"]
    if table_index < 0 or table_index >= len(tables):
        raise HTTPException(status_code=404, detail="Таблица не найдена")
    
    current_item = tables[table_index]
    if isinstance(current_item, dict):
        current_item["value"] = req.table
        if req.merges is not None:
            current_item["merges"] = req.merges
    else:
        tables[table_index] = {"value": req.table, "merges": req.merges or []}
    return {"status": "ok"}


@app.post("/api/files/{file_id}/tables/{table_index}/reset")
async def reset_table(file_id: str, table_index: int):
    """Сбросить таблицу к первоначальному виду из файла."""
    data = storage.get_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")
    tables = data["tables"]
    orig_tables = data.get("original_tables", [])
    if table_index < 0 or table_index >= len(tables):
        raise HTTPException(status_code=404, detail="Таблица не найдена")

    if table_index < len(orig_tables):
        data["tables"][table_index] = copy.deepcopy(orig_tables[table_index])
    return {
        "status": "ok",
        "table": data["tables"][table_index],
    }



@app.post("/api/files/{file_id}/tables/{table_index}/converted")
async def save_converted_table(file_id: str, table_index: int, req: SaveConvertedTableRequest):
    """Сохранить готовый преобразованный текст для таблицы."""
    data = storage.get_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")
    tables = data["tables"]
    if table_index < 0 or table_index >= len(tables):
        raise HTTPException(status_code=404, detail="Таблица не найдена")
    
    if "converted_tables" not in data:
        data["converted_tables"] = {}
    data["converted_tables"][str(table_index)] = req.converted_text
    
    all_converted = len(data["converted_tables"]) >= len(tables) and len(tables) > 0
    return {
        "status": "ok",
        "converted_count": len(data["converted_tables"]),
        "total_tables": len(tables),
        "all_converted": all_converted,
    }


@app.get("/api/files/{file_id}/download-converted")
async def download_converted(file_id: str):
    """
    Скачать итоговый документ, в котором вместо исходных таблиц подставлен
    преобразованный текст (из правил или LLM).
    """
    data = storage.get_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    converted_dict = data.get("converted_tables", {})
    tables = data.get("tables", [])
    
    # Формируем итоговый текст документа
    # Идем по content в исходном порядке
    content_list = data.get("content", [])
    result_parts = []
    
    table_counter = 0
    for item in content_list:
        if item["type"] == "text":
            result_parts.append(item["value"])
        elif item["type"] == "table":
            conv_text = converted_dict.get(str(table_counter), "")
            if conv_text:
                result_parts.append(conv_text)
            else:
                # Если таблица не была отдельно сохранена, сериализуем сетку
                t_val = item["value"]
                grid = t_val if isinstance(t_val, list) else t_val.get("value", [])
                lines = ["; ".join(str(c) for c in row if str(c).strip()) for row in grid]
                result_parts.append("\n".join(lines))
            table_counter += 1
            result_parts.append("\n" + ("=" * 40) + "\n")
            
    final_text = "\n\n".join(result_parts)
    
    filename_base = data["filename"].rsplit(".", 1)[0]
    out_filename = f"{filename_base}_converted.txt"
    
    # Записываем во временный файл и возвращаем
    temp_dir = tempfile.gettempdir()
    out_path = os.path.join(temp_dir, out_filename)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(final_text)
        
    return FileResponse(
        out_path,
        media_type="text/plain; charset=utf-8",
        filename=out_filename
    )


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str):
    """Удалить файл из хранилища."""
    storage.remove_file(file_id)
    return {"status": "ok"}


@app.delete("/api/files")
async def delete_all_files():
    """Удалить все файлы."""
    storage.clear_files()
    return {"status": "ok"}


# ─── Преобразование таблиц ────────────────────────────────────────────────────



@app.post("/api/transform")
async def transform_table(req: TransformRequest):
    """Преобразовать таблицу по правилам пользователя."""
    data = storage.get_file(req.file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")

    tables = data["tables"]
    if req.table_index < 0 or req.table_index >= len(tables):
        raise HTTPException(status_code=404, detail="Таблица не найдена")

    table = tables[req.table_index]
    rules = req.rules.strip()

    # Применяем правила к таблице
    transformed_lines = apply_rules(table, rules)

    return {"lines": transformed_lines, "full_text": "\n".join(transformed_lines)}


def apply_rules(table: list[list[str]], rules: str) -> list[str]:
    """
    Мощный движок правил для преобразования таблиц в текст.
    
    ═══ ДИРЕКТИВЫ (строки начинающиеся с @) ═══
    
    @mode MODE        — режим чтения (row, column, kv, matrix, group, flat)
    @header_rows N    — кол-во строк заголовков (по умолчанию 1)
    @header_cols N    — кол-во столбцов-заголовков (для matrix, по умолчанию 0)
    @skip_empty       — пропускать пустые строки/ячейки
    @separator TEXT    — разделитель полей (по умолчанию "; ")
    @group_by N       — группировать по столбцу N (индекс или имя)
    @enumerate        — нумеровать строки результата
    @prefix TEXT      — добавить префикс к каждой строке
    @merge_repeated   — объединять повторяющиеся значения в столбце (группировка)
    @data_rows N:M    — диапазон строк данных (1-indexed, включительно)
    @data_cols N:M    — диапазон столбцов данных (0-indexed, включительно)
    
    ═══ ШАБЛОН (строки без @) ═══
    
    {0}, {1}, {2}     — столбец по индексу
    {Название}        — столбец по имени заголовка
    {_row}            — номер строки (с 1)
    {_group}          — имя группы (для mode=group)
    {_all}            — все ячейки через разделитель
    
    ═══ РЕЖИМЫ ═══
    
    row     — построчное чтение с шаблоном (по умолчанию)
    column  — чтение по столбцам
    kv      — ключ-значение (столбец 0 = ключ, остальные = значения)
    matrix  — перекрёстная таблица: строка × столбец → значение
    group   — группировка по столбцу @group_by
    flat    — плоский вывод всех ячеек
    """
    # Извлекаем данные таблицы и возможные merges
    merges = []
    if isinstance(table, dict):
        merges = table.get("merges", [])
        table_grid = table.get("value", [])
    else:
        table_grid = table

    if not table_grid or len(table_grid) < 1:
        return ["Пустая таблица"]


    # ─── Парсим директивы и шаблон ───
    directives: dict[str, str] = {}
    template_parts: list[str] = []

    for line in rules.split("\n"):
        stripped = line.strip()
        if stripped.startswith("@"):
            # Разбираем директиву: @key value
            parts = stripped[1:].split(None, 1)
            key = parts[0].lower()
            value = parts[1] if len(parts) > 1 else "true"
            directives[key] = value
        elif stripped:
            template_parts.append(stripped)

    template = "\n".join(template_parts) if template_parts else ""

    # ─── Читаем параметры ───
    mode = directives.get("mode", "row")
    header_rows = int(directives.get("header_rows", "1"))
    header_cols = int(directives.get("header_cols", "0"))
    skip_empty = "skip_empty" in directives
    separator = directives.get("separator", "; ")
    group_col = directives.get("group_by", None)
    do_enum = "enumerate" in directives
    prefix = directives.get("prefix", "")
    merge_repeated = "merge_repeated" in directives

    # Диапазоны строк/столбцов
    data_rows_range = directives.get("data_rows", None)
    data_cols_range = directives.get("data_cols", None)

    # ─── Заголовки ───
    headers = table_grid[0] if header_rows >= 1 and table_grid else []
    multi_headers = table_grid[:header_rows] if header_rows > 0 else []
    
    # Составной заголовок (для многострочных заголовков)
    if header_rows > 1:
        combined_headers = []
        num_cols = max(len(r) for r in table_grid) if table_grid else 0
        for c in range(num_cols):
            parts = []
            for h_row in multi_headers:
                if c < len(h_row) and h_row[c].strip():
                    parts.append(h_row[c].strip())
            combined_headers.append(" > ".join(parts) if parts else f"Кол.{c}")
        headers = combined_headers

    # Строки данных (после заголовков)
    data = table_grid[header_rows:] if header_rows < len(table_grid) else []

    # Фильтруем по @data_rows
    if data_rows_range:
        rng = data_rows_range.split(":")
        start = int(rng[0]) - 1 if rng[0] else 0
        end = int(rng[1]) if len(rng) > 1 and rng[1] else len(data)
        data = data[start:end]

    # Фильтруем по @data_cols
    col_indices = None
    if data_cols_range:
        rng = data_cols_range.split(":")
        start = int(rng[0]) if rng[0] else 0
        end = int(rng[1]) + 1 if len(rng) > 1 and rng[1] else len(headers)
        col_indices = list(range(start, end))

    # ─── Выбор режима ───
    if mode == "row":
        lines = _mode_row(data, headers, template, separator, skip_empty, col_indices)
    elif mode == "column":
        lines = _mode_column(data, headers, template, separator, skip_empty)
    elif mode in ("kv", "key-value"):
        lines = _mode_kv(data, headers, template, separator, header_rows, table_grid)
    elif mode == "matrix":
        lines = _mode_matrix(data, headers, template, separator, header_cols)
    elif mode == "group":
        lines = _mode_group(data, headers, template, separator, group_col, skip_empty, merge_repeated)
    elif mode == "flat":
        lines = _mode_flat(data, headers, separator, skip_empty)
    else:
        lines = _mode_row(data, headers, template, separator, skip_empty, col_indices)


    # ─── Постобработка ───
    if do_enum:
        lines = [f"{i+1}. {line}" for i, line in enumerate(lines)]
    if prefix:
        lines = [f"{prefix}{line}" for line in lines]

    return lines if lines else ["Нет данных для преобразования"]


def _apply_template(template: str, row: list[str], headers: list[str], 
                     row_num: int = 0, group_name: str = "", separator: str = "; ") -> str:
    """
    Применяет шаблон к строке данных с нечувствительностью к регистру,
    лишним пробелам и переводам строк в именах заголовков.
    """
    line = template
    
    # {_row} — номер строки
    line = line.replace("{_row}", str(row_num))
    # {_group} — имя группы
    line = line.replace("{_group}", group_name)
    # {_all} — все ячейки
    line = line.replace("{_all}", separator.join(c for c in row if c.strip()))
    
    # {0}, {1}, {2}... — по индексу
    for col_idx, cell in enumerate(row):
        line = line.replace(f"{{{col_idx}}}", cell if cell else "")
    
    # Подготовка маппинга заголовков с нормализацией пробелов
    normalized_headers: dict[str, str] = {}
    for col_idx, header in enumerate(headers):
        if header and col_idx < len(row):
            val = row[col_idx] if row[col_idx] else ""
            # Прямой ключ
            normalized_headers[header.strip()] = val
            # Ключ без лишних пробелов и в нижнем регистре
            clean_key = re.sub(r"\s+", " ", header.strip().lower())
            normalized_headers[clean_key] = val

    # Замена всех {переменных}
    def _replace_placeholder(match: re.Match) -> str:
        var_name = match.group(1).strip()
        # Проверяем прямое совпадение
        if var_name in normalized_headers:
            return normalized_headers[var_name]
        # Проверяем совпадение без регистра и пробелов
        clean_var = re.sub(r"\s+", " ", var_name.lower())
        if clean_var in normalized_headers:
            return normalized_headers[clean_var]
        # Если это числовой индекс {0}, {1}
        if var_name.isdigit():
            idx = int(var_name)
            if idx < len(row):
                return row[idx] if row[idx] else ""
            return ""
        # Если ничего не подошло — возвращаем исходную метку
        return match.group(0)

    line = re.sub(r"\{([^}]+)\}", _replace_placeholder, line)
    return line



def _default_row_text(row: list[str], headers: list[str], separator: str, 
                       col_indices: list[int] | None = None) -> str:
    """Текст строки по умолчанию (header: value)."""
    parts = []
    indices = col_indices if col_indices else range(len(row))
    for col_idx in indices:
        if col_idx >= len(row):
            continue
        cell = row[col_idx]
        header = headers[col_idx] if col_idx < len(headers) else f"Кол.{col_idx}"
        if cell and cell.strip():
            parts.append(f"{header}: {cell}")
    return separator.join(parts)


# ═══════════════════════════════════════════════════════════════════
# РЕЖИМЫ
# ═══════════════════════════════════════════════════════════════════


def _mode_row(data, headers, template, separator, skip_empty, col_indices) -> list[str]:
    """Построчное чтение с шаблоном."""
    lines = []
    for row_num, row in enumerate(data, 1):
        if skip_empty and not any(c.strip() for c in row):
            continue
        if template:
            lines.append(_apply_template(template, row, headers, row_num, separator=separator))
        else:
            text = _default_row_text(row, headers, separator, col_indices)
            if text:
                lines.append(text)
    return lines


def _mode_column(data, headers, template, separator, skip_empty) -> list[str]:
    """Чтение по столбцам: каждый столбец — одна строка результата."""
    lines = []
    num_cols = len(headers) if headers else (max(len(r) for r in data) if data else 0)
    
    for col_idx in range(num_cols):
        header = headers[col_idx] if col_idx < len(headers) else f"Кол.{col_idx}"
        values = []
        for row in data:
            if col_idx < len(row):
                val = row[col_idx].strip()
                if val or not skip_empty:
                    values.append(val)
        
        if template:
            # В шаблоне: {0}=заголовок, {1}=значения через разделитель
            line = template.replace("{0}", header)
            line = line.replace("{1}", separator.join(values))
            line = line.replace("{_values}", separator.join(values))
            line = line.replace("{_header}", header)
            line = line.replace("{_count}", str(len(values)))
            lines.append(line)
        else:
            lines.append(f"{header}: {separator.join(values)}")
    
    return lines


def _mode_kv(data, headers, template, separator, header_rows, full_table) -> list[str]:
    """Режим ключ-значение: столбец 0 — ключ, остальные — значения."""
    lines = []
    # Используем все строки включая заголовки, если таблица из 2 столбцов
    rows_to_process = full_table if len(headers) <= 2 else data
    
    for row in rows_to_process:
        if len(row) < 2:
            continue
        key = row[0].strip()
        if not key:
            continue
        
        values = [c.strip() for c in row[1:] if c.strip()]
        value_text = separator.join(values)
        
        if template:
            line = template.replace("{_key}", key)
            line = line.replace("{_value}", value_text)
            line = line.replace("{0}", key)
            for i, v in enumerate(values):
                line = line.replace(f"{{{i+1}}}", v)
            # По заголовку
            for col_idx, header in enumerate(headers):
                if header and col_idx < len(row):
                    line = line.replace(f"{{{header}}}", row[col_idx] if row[col_idx] else "")
            lines.append(line)
        else:
            lines.append(f"{key}: {value_text}")
    
    return lines


def _mode_matrix(data, headers, template, separator, header_cols) -> list[str]:
    """
    Режим матрицы: перекрёстная таблица.
    Заголовки строк в первых header_cols столбцах,
    заголовки столбцов — headers.
    Для каждой ячейки: row_header × col_header = value.
    """
    lines = []
    h_cols = max(header_cols, 1)
    col_headers = headers[h_cols:] if len(headers) > h_cols else []
    
    for row in data:
        row_header_parts = [row[c].strip() for c in range(min(h_cols, len(row)))]
        row_header = " > ".join(p for p in row_header_parts if p)
        
        for col_idx, col_header in enumerate(col_headers):
            data_col = h_cols + col_idx
            if data_col >= len(row):
                continue
            value = row[data_col].strip()
            if not value:
                continue
            
            if template:
                line = template.replace("{_row_header}", row_header)
                line = line.replace("{_col_header}", col_header)
                line = line.replace("{_value}", value)
                lines.append(line)
            else:
                lines.append(f"{row_header} | {col_header}: {value}")
    
    return lines


def _mode_group(data, headers, template, separator, group_col, skip_empty, merge_repeated) -> list[str]:
    """
    Режим группировки: строки группируются по значению в указанном столбце.
    Полезно для таблиц с вертикально объединёнными ячейками.
    """
    lines = []
    
    # Определяем индекс столбца для группировки
    g_col = 0
    if group_col is not None:
        try:
            g_col = int(group_col)
        except ValueError:
            # Поиск по имени заголовка
            for i, h in enumerate(headers):
                if h.strip().lower() == group_col.strip().lower():
                    g_col = i
                    break
    
    # Группируем строки
    groups: dict[str, list[list[str]]] = {}
    group_order: list[str] = []
    current_group = ""
    
    for row in data:
        if skip_empty and not any(c.strip() for c in row):
            continue
        
        group_val = row[g_col].strip() if g_col < len(row) else ""
        
        if merge_repeated:
            # Если значение совпадает с предыдущим или пустое — используем текущую группу
            if group_val and group_val != current_group:
                current_group = group_val
            group_val = current_group
        elif group_val:
            current_group = group_val
        else:
            group_val = current_group
        
        if group_val not in groups:
            groups[group_val] = []
            group_order.append(group_val)
        groups[group_val].append(row)
    
    # Формируем результат
    for group_name in group_order:
        rows = groups[group_name]
        lines.append(f"[{group_name}]")
        
        for row_num, row in enumerate(rows, 1):
            # Убираем столбец группировки из вывода
            filtered_row = [c for i, c in enumerate(row) if i != g_col]
            filtered_headers = [h for i, h in enumerate(headers) if i != g_col]
            
            if template:
                line = _apply_template(
                    template, filtered_row, filtered_headers,
                    row_num, group_name, separator
                )
                lines.append(f"  {line}")
            else:
                text = _default_row_text(filtered_row, filtered_headers, separator)
                if text:
                    lines.append(f"  {text}")
        
        lines.append("")  # Пустая строка между группами
    
    return lines


def _mode_flat(data, headers, separator, skip_empty) -> list[str]:
    """Плоский вывод: все непустые ячейки в одну строку."""
    all_values = []
    for row in data:
        for cell in row:
            val = cell.strip() if cell else ""
            if val or not skip_empty:
                all_values.append(val)
    return [separator.join(v for v in all_values if v)] if all_values else []


# ─── GigaChat ─────────────────────────────────────────────────────────────────


@app.post("/api/generate")
async def generate_text(req: GenerateRequest):
    """Отправить текст в GigaChat для генерации FAQ."""
    settings = storage.get_settings()

    if settings.auth_mode == "key" and not settings.auth_key:
        return GenerateResponse(result="", error="API-ключ GigaChat не задан. Укажите его в настройках.")
    elif settings.auth_mode == "cert" and not settings.cert_file and not settings.auth_key:
        return GenerateResponse(result="", error="Режим сертификатов: укажите путь к сертификату или ключ авторизации.")

    system_prompt = req.system_prompt if req.system_prompt else settings.system_prompt

    try:
        result = await gigachat_client.generate(
            auth_mode=settings.auth_mode,
            auth_key=settings.auth_key,
            cert_file=settings.cert_file,
            key_file=settings.key_file,
            ca_file=settings.ca_file,
            scope=settings.scope,
            user_text=req.text,
            system_prompt=system_prompt,
            model=settings.model,
            temperature=settings.temperature,
        )
        return GenerateResponse(result=result)
    except Exception as e:
        logger.error(f"Ошибка GigaChat: {e}")
        return GenerateResponse(result="", error=f"Ошибка GigaChat: {str(e)}")


# ─── Настройки ────────────────────────────────────────────────────────────────


@app.get("/api/settings")
async def get_settings():
    """Получить текущие настройки."""
    settings = storage.get_settings()
    return settings.model_dump()


@app.post("/api/settings")
async def update_settings(settings: GigaChatSettings):
    """Обновить настройки."""
    old_settings = storage.get_settings()
    if (settings.auth_key != old_settings.auth_key or 
        settings.cert_file != old_settings.cert_file or
        settings.auth_mode != old_settings.auth_mode):
        gigachat_client.reset_token()

    storage.update_settings(settings)
    return {"status": "ok"}

