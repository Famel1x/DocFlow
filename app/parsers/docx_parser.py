"""Парсер DOCX с поддержкой объединённых ячеек (gridSpan + vMerge)."""

import docx
from typing import Any
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.parsers.base import BaseParser

NSMAP = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


class DOCXParser(BaseParser):
    def parse(self) -> list[dict[str, Any]]:
        content = []
        doc = docx.Document(self.file_path)

        for child in doc.element.body:
            if isinstance(child, CT_P):
                p = Paragraph(child, doc)
                text = p.text.strip()
                if text:
                    content.append({"type": "text", "value": text})
            elif isinstance(child, CT_Tbl):
                table = Table(child, doc)
                table_data, merges = self._extract_table(table)
                if table_data:
                    item = {"type": "table", "value": table_data}
                    if merges:
                        item["merges"] = merges
                    content.append(item)

        return content

    def _extract_table(self, table: Table):
        """Извлекает таблицу как плоскую сетку, заполняя объединённые ячейки."""
        num_cols = max(len(row.cells) for row in table.rows)
        num_rows = len(table.rows)

        # Сетка: значения ячеек
        grid = [[""] * num_cols for _ in range(num_rows)]
        # Маска: True если ячейка уже занята (merge)
        occupied = [[False] * num_cols for _ in range(num_rows)]
        merges = []

        for row_idx, row in enumerate(table.rows):
            col_cursor = 0
            tc_list = row._tr.findall(f"w:tc", NSMAP)

            for tc in tc_list:
                # Пропускаем занятые столбцы (вертикальный merge)
                while col_cursor < num_cols and occupied[row_idx][col_cursor]:
                    col_cursor += 1
                if col_cursor >= num_cols:
                    break

                # Текст ячейки
                text_parts = []
                for p in tc.findall(f"w:p", NSMAP):
                    runs = p.findall(f".//w:r/w:t", NSMAP)
                    text_parts.append("".join(r.text or "" for r in runs))
                cell_text = "\n".join(text_parts).strip()

                # Горизонтальное объединение (gridSpan)
                tc_pr = tc.find(f"w:tcPr", NSMAP)
                h_span = 1
                if tc_pr is not None:
                    gs = tc_pr.find(f"w:gridSpan", NSMAP)
                    if gs is not None:
                        h_span = int(gs.get(f"{{{NSMAP['w']}}}val", "1"))

                # Вертикальное объединение (vMerge)
                is_vmerge_restart = False
                is_vmerge_continue = False
                if tc_pr is not None:
                    vm = tc_pr.find(f"w:vMerge", NSMAP)
                    if vm is not None:
                        val = vm.get(f"{{{NSMAP['w']}}}val", "")
                        if val == "restart":
                            is_vmerge_restart = True
                        else:
                            is_vmerge_continue = True

                if is_vmerge_continue:
                    # Берём значение из ячейки выше
                    for r in range(row_idx - 1, -1, -1):
                        if grid[r][col_cursor]:
                            cell_text = grid[r][col_cursor]
                            break

                # Заполняем сетку
                for c in range(h_span):
                    if col_cursor + c < num_cols:
                        grid[row_idx][col_cursor + c] = cell_text
                        if c > 0:
                            occupied[row_idx][col_cursor + c] = True

                # Если начало вертикального merge — помечаем строки ниже как occupied
                if is_vmerge_restart:
                    # Ищем сколько строк ниже продолжается merge
                    for next_row in range(row_idx + 1, num_rows):
                        next_tr = table.rows[next_row]._tr
                        next_tcs = next_tr.findall(f"w:tc", NSMAP)
                        found_continue = False
                        # Находим соответствующий tc
                        nc = 0
                        for ntc in next_tcs:
                            while nc < num_cols and occupied[next_row][nc]:
                                nc += 1
                            if nc == col_cursor:
                                ntc_pr = ntc.find(f"w:tcPr", NSMAP)
                                if ntc_pr is not None:
                                    nvm = ntc_pr.find(f"w:vMerge", NSMAP)
                                    if nvm is not None:
                                        nval = nvm.get(f"{{{NSMAP['w']}}}val", "")
                                        if nval != "restart":
                                            found_continue = True
                                            for c in range(h_span):
                                                if col_cursor + c < num_cols:
                                                    occupied[next_row][col_cursor + c] = True
                                                    grid[next_row][col_cursor + c] = cell_text
                                break
                            # Считаем span текущего ntc
                            ntc_pr2 = ntc.find(f"w:tcPr", NSMAP)
                            ns = 1
                            if ntc_pr2 is not None:
                                ngs = ntc_pr2.find(f"w:gridSpan", NSMAP)
                                if ngs is not None:
                                    ns = int(ngs.get(f"{{{NSMAP['w']}}}val", "1"))
                            nc += ns
                        if not found_continue:
                            break

                    # Записываем merge
                    merge_end_row = row_idx
                    for r in range(row_idx + 1, num_rows):
                        if occupied[r][col_cursor]:
                            merge_end_row = r
                        else:
                            break

                    if merge_end_row > row_idx or h_span > 1:
                        merges.append({
                            "min_row": row_idx, "min_col": col_cursor,
                            "max_row": merge_end_row,
                            "max_col": col_cursor + h_span - 1,
                        })
                elif h_span > 1:
                    merges.append({
                        "min_row": row_idx, "min_col": col_cursor,
                        "max_row": row_idx,
                        "max_col": col_cursor + h_span - 1,
                    })

                col_cursor += h_span

        return grid, merges
