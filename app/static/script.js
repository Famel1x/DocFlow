/**
 * Парсер документов → FAQ
 * Клиентская логика: загрузка файлов, навигация по таблицам,
 * редактирование ячеек таблицы, применение правил, редактирование превью и ответов LLM,
 * фиксация преобразований и экспорт готового документа.
 */

document.addEventListener('DOMContentLoaded', () => {
    // ═══ Состояние приложения ═══
    const state = {
        files: [],           // [{file_id, filename, file_type, tables_count}]
        activeFileId: null,
        activeFileData: null, // Полные данные текущего файла
        currentTableIndex: 0,
        transformedText: '',
        tableEdited: false,
    };

    // ═══ DOM-элементы ═══
    const $ = (sel) => document.querySelector(sel);
    const fileInput = $('#file-input');
    const folderInput = $('#folder-input');
    const fileTabs = $('#file-tabs');
    const emptyState = $('#empty-state');
    const workArea = $('#work-area');
    const dropZone = $('#drop-zone');
    const tableView = $('#table-view');
    const tableTitle = $('#table-title');
    const tableCounter = $('#table-counter');
    const prevTableBtn = $('#prev-table');
    const nextTableBtn = $('#next-table');
    const saveTableEditsBtn = $('#save-table-edits-btn');
    const rulesInput = $('#rules-input');
    const applyRulesBtn = $('#apply-rules-btn');
    const transformPreviewEdit = $('#transform-preview-edit');
    const savePreviewConvertedBtn = $('#save-preview-as-converted-btn');
    const sendToLlmBtn = $('#send-to-llm-btn');
    const llmResultEdit = $('#llm-result-edit');
    const saveLlmConvertedBtn = $('#save-llm-as-converted-btn');
    const copyResultBtn = $('#copy-result-btn');
    const tableConvertedStatus = $('#table-converted-status');
    const downloadConvertedBtn = $('#download-converted-btn');
    const settingsBtn = $('#settings-btn');
    const settingsModal = $('#settings-modal');
    const closeSettingsBtn = $('#close-settings');
    const saveSettingsBtn = $('#save-settings-btn');
    const loadingOverlay = $('#loading');
    const loadingText = $('#loading-text');
    const themeCheckbox = $('#theme-checkbox');
    const tempSlider = $('#temperature');
    const tempValue = $('#temp-value');

    // ═══ Тема ═══
    function initTheme() {
        const saved = localStorage.getItem('theme');
        if (saved === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            themeCheckbox.checked = true;
        }
    }
    themeCheckbox.addEventListener('change', () => {
        const theme = themeCheckbox.checked ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
    });
    initTheme();

    // ═══ Drag & Drop ═══
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(ev => {
        document.body.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); });
    });
    if (dropZone) {
        ['dragenter', 'dragover'].forEach(ev => {
            dropZone.addEventListener(ev, () => dropZone.classList.add('dragover'));
        });
        ['dragleave', 'drop'].forEach(ev => {
            dropZone.addEventListener(ev, () => dropZone.classList.remove('dragover'));
        });
        dropZone.addEventListener('drop', e => {
            uploadFiles(e.dataTransfer.files);
        });
    }

    // ═══ Файловые инпуты ═══
    fileInput.addEventListener('change', function () {
        if (this.files.length) uploadFiles(this.files);
        this.value = '';
    });
    folderInput.addEventListener('change', function () {
        if (this.files.length) uploadFiles(this.files);
        this.value = '';
    });

    // ═══ Загрузка файлов ═══
    async function uploadFiles(fileList) {
        const formData = new FormData();
        let count = 0;
        for (const file of fileList) {
            const ext = file.name.split('.').pop().toLowerCase();
            if (['pdf', 'docx', 'pptx', 'xlsx'].includes(ext)) {
                formData.append('files', file);
                count++;
            }
        }
        if (!count) {
            alert('Нет поддерживаемых файлов (.pdf, .docx, .pptx, .xlsx)');
            return;
        }

        showLoading(`Обработка ${count} файл(ов)...`);
        try {
            const resp = await fetch('/api/upload', { method: 'POST', body: formData });
            if (!resp.ok) throw new Error('Ошибка загрузки');
            const data = await resp.json();

            // Добавляем файлы в стейт
            for (const f of data.files) {
                if (f.file_id) {
                    state.files.push(f);
                }
            }
            renderFileTabs();

            // Активируем первый загруженный
            if (data.files.length > 0 && data.files[0].file_id) {
                activateFile(data.files[0].file_id);
            }
        } catch (err) {
            console.error(err);
            alert('Ошибка при загрузке: ' + err.message);
        } finally {
            hideLoading();
        }
    }

    // ═══ Табы файлов ═══
    function renderFileTabs() {
        if (state.files.length === 0) {
            fileTabs.innerHTML = '<span class="file-bar-placeholder">Загрузите файлы для начала работы</span>';
            return;
        }
        fileTabs.innerHTML = '';
        for (const f of state.files) {
            const tab = document.createElement('button');
            tab.className = 'file-tab' + (f.file_id === state.activeFileId ? ' active' : '');
            tab.innerHTML = `
                <span class="type-badge">${f.file_type}</span>
                ${escapeHtml(f.filename)}
                <span class="tab-close" data-id="${f.file_id}" title="Удалить">✕</span>
            `;
            tab.addEventListener('click', (e) => {
                if (e.target.classList.contains('tab-close')) {
                    removeFile(e.target.dataset.id);
                    return;
                }
                activateFile(f.file_id);
            });
            fileTabs.appendChild(tab);
        }
    }

    // ═══ Активация файла ═══
    async function activateFile(fileId) {
        state.activeFileId = fileId;
        state.currentTableIndex = 0;
        renderFileTabs();

        emptyState.classList.add('hidden');
        workArea.classList.remove('hidden');

        showLoading('Загрузка данных...');
        try {
            const resp = await fetch(`/api/files/${fileId}`);
            if (!resp.ok) throw new Error('Файл не найден');
            state.activeFileData = await resp.json();
            if (!state.activeFileData.converted_tables) {
                state.activeFileData.converted_tables = {};
            }
            renderCurrentTable();
            checkAllTablesConverted();
        } catch (err) {
            console.error(err);
            tableView.innerHTML = `<p class="muted">Ошибка загрузки: ${err.message}</p>`;
        } finally {
            hideLoading();
        }
    }

    // ═══ Удаление файла ═══
    async function removeFile(fileId) {
        await fetch(`/api/files/${fileId}`, { method: 'DELETE' });
        state.files = state.files.filter(f => f.file_id !== fileId);

        if (state.activeFileId === fileId) {
            state.activeFileId = null;
            state.activeFileData = null;
            if (state.files.length > 0) {
                activateFile(state.files[0].file_id);
            } else {
                emptyState.classList.remove('hidden');
                workArea.classList.add('hidden');
                downloadConvertedBtn.classList.add('hidden');
            }
        }
        renderFileTabs();
    }

    // ═══ Навигация по таблицам ═══
    prevTableBtn.addEventListener('click', () => {
        if (state.currentTableIndex > 0) {
            state.currentTableIndex--;
            renderCurrentTable();
        }
    });
    nextTableBtn.addEventListener('click', () => {
        const data = state.activeFileData;
        if (data && state.currentTableIndex < data.tables.length - 1) {
            state.currentTableIndex++;
            renderCurrentTable();
        }
    });

    function renderCurrentTable() {
        const data = state.activeFileData;
        if (!data) return;

        const tables = data.tables || [];
        const idx = state.currentTableIndex;

        tableTitle.textContent = data.filename;
        tableCounter.textContent = tables.length > 0
            ? `${idx + 1} / ${tables.length}`
            : 'Нет таблиц';

        prevTableBtn.disabled = idx <= 0;
        nextTableBtn.disabled = idx >= tables.length - 1;
        saveTableEditsBtn.style.display = 'none';

        // Обновляем статус конвертации текущей таблицы
        updateCurrentTableStatus();

        if (tables.length === 0) {
            if (data.text_blocks && data.text_blocks.length > 0) {
                tableView.innerHTML = data.text_blocks
                    .map(t => `<div style="margin-bottom:1rem;white-space:pre-wrap;">${escapeHtml(t)}</div>`)
                    .join('');
            } else {
                tableView.innerHTML = '<p class="muted">В файле нет таблиц и текста</p>';
            }
            applyRulesBtn.disabled = true;
            return;
        }

        applyRulesBtn.disabled = false;
        const tableObj = tables[idx];
        tableView.innerHTML = buildTableHtml(tableObj);
        attachTableCellEditListeners();
    }

    function buildTableHtml(tableObj) {
        if (!tableObj) return '<p class="muted">Пустая таблица</p>';
        
        const grid = Array.isArray(tableObj) ? tableObj : (tableObj.value || []);
        const merges = (!Array.isArray(tableObj) && tableObj.merges) ? tableObj.merges : [];

        if (!grid || grid.length === 0) return '<p class="muted">Пустая таблица</p>';

        const rowsCount = grid.length;
        const colsCount = Math.max(...grid.map(r => r.length), 0);
        const cellAction = Array.from({ length: rowsCount }, () => Array(colsCount).fill(undefined));

        merges.forEach(m => {
            const minR = m.min_row;
            const maxR = m.max_row;
            const minC = m.min_col;
            const maxC = m.max_col;
            const rSpan = maxR - minR + 1;
            const cSpan = maxC - minC + 1;

            for (let r = minR; r <= maxR; r++) {
                for (let c = minC; c <= maxC; c++) {
                    if (r === minR && c === minC) {
                        cellAction[r][c] = { rowspan: rSpan, colspan: cSpan };
                    } else {
                        cellAction[r][c] = 'skip';
                    }
                }
            }
        });

        let html = '<table id="editable-data-table">';
        grid.forEach((row, rowIdx) => {
            html += '<tr>';
            row.forEach((cell, colIdx) => {
                const action = cellAction[rowIdx] ? cellAction[rowIdx][colIdx] : undefined;
                if (action === 'skip') return;

                const tag = rowIdx === 0 ? 'th' : 'td';
                let attrs = ` contenteditable="true" data-row="${rowIdx}" data-col="${colIdx}"`;
                if (action && typeof action === 'object') {
                    if (action.rowspan > 1) attrs += ` rowspan="${action.rowspan}"`;
                    if (action.colspan > 1) attrs += ` colspan="${action.colspan}"`;
                    attrs += ` class="merged-cell"`;
                }

                html += `<${tag}${attrs}>${escapeHtml(cell || '')}</${tag}>`;
            });
            html += '</tr>';
        });
        html += '</table>';
        return html;
    }

    // ═══ Редактирование ячеек таблицы и структуры (Строки / Столбцы) ═══
    let selectedCellPos = { row: 0, col: 0 };

    function syncGridFromDom() {
        const tableEl = document.getElementById('editable-data-table');
        if (!tableEl || !state.activeFileData) return null;

        const currentItem = state.activeFileData.tables[state.currentTableIndex];
        const grid = Array.isArray(currentItem) ? currentItem : currentItem.value;

        const rows = tableEl.querySelectorAll('tr');
        rows.forEach((row) => {
            const cells = row.children;
            for (let c = 0; c < cells.length; c++) {
                const cell = cells[c];
                const r = parseInt(cell.dataset.row, 10);
                const col = parseInt(cell.dataset.col, 10);
                if (!isNaN(r) && !isNaN(col) && grid[r] && col < grid[r].length) {
                    grid[r][col] = cell.innerText.trim();
                }
            }
        });
        return grid;
    }

    function highlightSelectedCell(r, c) {
        selectedCellPos = { row: r, col: c };
        tableView.querySelectorAll('.selected-cell').forEach(el => el.classList.remove('selected-cell'));
        const target = tableView.querySelector(`[data-row="${r}"][data-col="${c}"]`);
        if (target) {
            target.classList.add('selected-cell');
        }
    }

    function attachTableCellEditListeners() {
        const cells = tableView.querySelectorAll('[contenteditable="true"]');
        cells.forEach(cell => {
            cell.addEventListener('input', () => {
                saveTableEditsBtn.style.display = 'inline-flex';
            });
            cell.addEventListener('focus', () => {
                const r = parseInt(cell.dataset.row, 10);
                const c = parseInt(cell.dataset.col, 10);
                if (!isNaN(r) && !isNaN(c)) {
                    highlightSelectedCell(r, c);
                }
            });
            // Удобная навигация стрелками и Tab/Enter
            cell.addEventListener('keydown', (e) => {
                const r = parseInt(cell.dataset.row, 10);
                const c = parseInt(cell.dataset.col, 10);
                let nextTarget = null;

                if (e.key === 'ArrowDown') {
                    nextTarget = tableView.querySelector(`[data-row="${r + 1}"][data-col="${c}"]`);
                } else if (e.key === 'ArrowUp') {
                    nextTarget = tableView.querySelector(`[data-row="${r - 1}"][data-col="${c}"]`);
                } else if (e.key === 'Tab' && !e.shiftKey) {
                    e.preventDefault();
                    nextTarget = tableView.querySelector(`[data-row="${r}"][data-col="${c + 1}"]`) ||
                                 tableView.querySelector(`[data-row="${r + 1}"][data-col="0"]`);
                } else if (e.key === 'Tab' && e.shiftKey) {
                    e.preventDefault();
                    nextTarget = tableView.querySelector(`[data-row="${r}"][data-col="${c - 1}"]`);
                }

                if (nextTarget) {
                    nextTarget.focus();
                }
            });
        });
    }

    // Тулбар манипуляции структурой таблицы и ячейками
    function getActiveTableItem() {
        syncGridFromDom();
        const currentItem = state.activeFileData.tables[state.currentTableIndex];
        if (Array.isArray(currentItem)) {
            const wrapped = { value: currentItem, merges: [] };
            state.activeFileData.tables[state.currentTableIndex] = wrapped;
            return wrapped;
        }
        if (!currentItem.merges) currentItem.merges = [];
        return currentItem;
    }

    function reRenderAndNotify(tableObj) {
        tableView.innerHTML = buildTableHtml(tableObj);
        attachTableCellEditListeners();
        saveTableEditsBtn.style.display = 'inline-flex';
        const grid = tableObj.value || tableObj;
        highlightSelectedCell(
            Math.min(selectedCellPos.row, grid.length - 1),
            Math.min(selectedCellPos.col, (grid[0]?.length || 1) - 1)
        );
    }

    // Вспомогательные функции для коррекции merges при добавлении/удалении строк и столбцов
    function shiftMergesRowInsert(merges, insertIdx) {
        merges.forEach(m => {
            if (m.min_row >= insertIdx) {
                m.min_row += 1;
                m.max_row += 1;
            } else if (m.max_row >= insertIdx) {
                m.max_row += 1;
            }
        });
    }

    function shiftMergesRowDelete(merges, delIdx) {
        for (let i = merges.length - 1; i >= 0; i--) {
            const m = merges[i];
            if (m.min_row === delIdx && m.max_row === delIdx) {
                merges.splice(i, 1);
            } else if (m.min_row > delIdx) {
                m.min_row -= 1;
                m.max_row -= 1;
            } else if (m.max_row >= delIdx) {
                m.max_row -= 1;
            }
        }
    }

    function shiftMergesColInsert(merges, insertIdx) {
        merges.forEach(m => {
            if (m.min_col >= insertIdx) {
                m.min_col += 1;
                m.max_col += 1;
            } else if (m.max_col >= insertIdx) {
                m.max_col += 1;
            }
        });
    }

    function shiftMergesColDelete(merges, delIdx) {
        for (let i = merges.length - 1; i >= 0; i--) {
            const m = merges[i];
            if (m.min_col === delIdx && m.max_col === delIdx) {
                merges.splice(i, 1);
            } else if (m.min_col > delIdx) {
                m.min_col -= 1;
                m.max_col -= 1;
            } else if (m.max_col >= delIdx) {
                m.max_col -= 1;
            }
        }
    }

    // 1. Добавить строку в конец
    $('#btn-add-row')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const numCols = grid[0] ? grid[0].length : 1;
        grid.push(Array(numCols).fill(''));
        reRenderAndNotify(item);
    });

    // 2. Вставить строку ниже выбранной
    $('#btn-insert-row-after')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const numCols = grid[0] ? grid[0].length : 1;
        const insertIdx = selectedCellPos.row + 1;
        grid.splice(insertIdx, 0, Array(numCols).fill(''));
        shiftMergesRowInsert(item.merges, insertIdx);
        selectedCellPos.row = insertIdx;
        reRenderAndNotify(item);
    });

    // 3. Удалить выбранную строку
    $('#btn-del-row')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        if (grid.length <= 1) {
            alert('Нельзя удалить единственную строку таблицы');
            return;
        }
        grid.splice(selectedCellPos.row, 1);
        shiftMergesRowDelete(item.merges, selectedCellPos.row);
        if (selectedCellPos.row >= grid.length) selectedCellPos.row = grid.length - 1;
        reRenderAndNotify(item);
    });

    // 4. Переместить строку вверх
    $('#btn-move-row-up')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const r = selectedCellPos.row;
        if (r > 0) {
            const temp = grid[r];
            grid[r] = grid[r - 1];
            grid[r - 1] = temp;
            selectedCellPos.row = r - 1;
            reRenderAndNotify(item);
        }
    });

    // 5. Переместить строку вниз
    $('#btn-move-row-down')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const r = selectedCellPos.row;
        if (r < grid.length - 1) {
            const temp = grid[r];
            grid[r] = grid[r + 1];
            grid[r + 1] = temp;
            selectedCellPos.row = r + 1;
            reRenderAndNotify(item);
        }
    });

    // 6. Добавить столбец справа
    $('#btn-add-col')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        grid.forEach(row => row.push(''));
        reRenderAndNotify(item);
    });

    // 7. Вставить столбец справа от выбранного
    $('#btn-insert-col-after')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const insertC = selectedCellPos.col + 1;
        grid.forEach(row => row.splice(insertC, 0, ''));
        shiftMergesColInsert(item.merges, insertC);
        selectedCellPos.col = insertC;
        reRenderAndNotify(item);
    });

    // 8. Удалить выбранный столбец
    $('#btn-del-col')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const numCols = grid[0] ? grid[0].length : 0;
        if (numCols <= 1) {
            alert('Нельзя удалить единственный столбец таблицы');
            return;
        }
        const c = selectedCellPos.col;
        grid.forEach(row => row.splice(c, 1));
        shiftMergesColDelete(item.merges, c);
        if (selectedCellPos.col >= grid[0].length) selectedCellPos.col = grid[0].length - 1;
        reRenderAndNotify(item);
    });

    // 9. Переместить столбец влево
    $('#btn-move-col-left')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const c = selectedCellPos.col;
        if (c > 0) {
            grid.forEach(row => {
                const temp = row[c];
                row[c] = row[c - 1];
                row[c - 1] = temp;
            });
            selectedCellPos.col = c - 1;
            reRenderAndNotify(item);
        }
    });

    // 10. Переместить столбец вправо
    $('#btn-move-col-right')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const c = selectedCellPos.col;
        const maxC = (grid[0]?.length || 1) - 1;
        if (c < maxC) {
            grid.forEach(row => {
                const temp = row[c];
                row[c] = row[c + 1];
                row[c + 1] = temp;
            });
            selectedCellPos.col = c + 1;
            reRenderAndNotify(item);
        }
    });

    // 11. Объединить ячейку со следующей справа
    $('#btn-merge-right')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const r = selectedCellPos.row;
        const c = selectedCellPos.col;
        if (c < grid[0].length - 1) {
            // Проверяем существующий merge
            let existing = item.merges.find(m => m.min_row <= r && r <= m.max_row && m.min_col <= c && c <= m.max_col);
            if (existing) {
                existing.max_col = Math.min(existing.max_col + 1, grid[0].length - 1);
            } else {
                item.merges.push({
                    min_row: r,
                    max_row: r,
                    min_col: c,
                    max_col: c + 1
                });
            }
            reRenderAndNotify(item);
        }
    });

    // 12. Объединить ячейку со следующей снизу
    $('#btn-merge-down')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const grid = item.value;
        const r = selectedCellPos.row;
        const c = selectedCellPos.col;
        if (r < grid.length - 1) {
            let existing = item.merges.find(m => m.min_row <= r && r <= m.max_row && m.min_col <= c && c <= m.max_col);
            if (existing) {
                existing.max_row = Math.min(existing.max_row + 1, grid.length - 1);
            } else {
                item.merges.push({
                    min_row: r,
                    max_row: r + 1,
                    min_col: c,
                    max_col: c
                });
            }
            reRenderAndNotify(item);
        }
    });

    // 13. Разъединить ячейку
    $('#btn-split-cell')?.addEventListener('click', () => {
        const item = getActiveTableItem();
        const r = selectedCellPos.row;
        const c = selectedCellPos.col;
        const idx = item.merges.findIndex(m => m.min_row <= r && r <= m.max_row && m.min_col <= c && c <= m.max_col);
        if (idx !== -1) {
            item.merges.splice(idx, 1);
            reRenderAndNotify(item);
        } else {
            alert('Выбранная ячейка не входит ни в одно объединение');
        }
    });

    // 14. Сброс к первоначальной таблице с подтверждением
    const resetTableBtn = $('#reset-table-btn');
    if (resetTableBtn) {
        resetTableBtn.addEventListener('click', async () => {
            if (!state.activeFileId) return;

            const confirmed = confirm(
                '⚠️ Вы уверены, что хотите сбросить текущую таблицу к первоначальному виду из файла?\nВсе внесенные правки, добавленные строки/столбцы и объединения будут отменены.'
            );
            if (!confirmed) return;

            showLoading('Сброс к исходному виду...');
            try {
                const resp = await fetch(`/api/files/${state.activeFileId}/tables/${state.currentTableIndex}/reset`, {
                    method: 'POST'
                });
                if (!resp.ok) throw new Error('Ошибка сброса таблицы');
                const resData = await resp.json();
                
                // Обновляем состояние таблицы
                state.activeFileData.tables[state.currentTableIndex] = resData.table;
                renderCurrentTable();
                saveTableEditsBtn.style.display = 'none';
                alert('Таблица успешно возвращена к первоначальному виду!');
            } catch (err) {
                alert('Ошибка: ' + err.message);
            } finally {
                hideLoading();
            }
        });
    }

    saveTableEditsBtn.addEventListener('click', async () => {
        const item = getActiveTableItem();
        const grid = item.value;

        showLoading('Сохранение таблицы...');
        try {
            const resp = await fetch(`/api/files/${state.activeFileId}/tables/${state.currentTableIndex}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: state.activeFileId,
                    table_index: state.currentTableIndex,
                    table: grid,
                    merges: item.merges || [],
                }),
            });
            if (!resp.ok) throw new Error('Ошибка сохранения таблицы');
            saveTableEditsBtn.style.display = 'none';
            alert('Таблица и объединения ячеек успешно сохранены!');
        } catch (err) {
            alert('Ошибка: ' + err.message);
        } finally {
            hideLoading();
        }
    });



    // ═══ Применение правил ═══
    applyRulesBtn.addEventListener('click', applyRules);

    async function applyRules() {
        const data = state.activeFileData;
        if (!data || data.tables.length === 0) return;

        showLoading('Применение правил...');
        try {
            const resp = await fetch('/api/transform', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: state.activeFileId,
                    table_index: state.currentTableIndex,
                    rules: rulesInput.value,
                }),
            });
            if (!resp.ok) throw new Error('Ошибка преобразования');
            const result = await resp.json();

            state.transformedText = result.full_text;
            transformPreviewEdit.value = result.full_text;
            sendToLlmBtn.disabled = false;
            savePreviewConvertedBtn.disabled = false;
        } catch (err) {
            console.error(err);
            transformPreviewEdit.value = `Ошибка: ${err.message}`;
        } finally {
            hideLoading();
        }
    }

    // ═══ Фиксация превью как готового текста таблицы ═══
    savePreviewConvertedBtn.addEventListener('click', async () => {
        const text = transformPreviewEdit.value.trim();
        if (!text) {
            alert('Поле превью пустое. Примените правила или введите текст.');
            return;
        }
        await commitConvertedText(text);
    });

    // ═══ GigaChat ═══
    sendToLlmBtn.addEventListener('click', sendToGigaChat);

    async function sendToGigaChat() {
        // Берем текст из редактируемого textarea превью
        const textToSend = transformPreviewEdit.value.trim() || state.transformedText;
        if (!textToSend) {
            alert('Нет текста для отправки в LLM.');
            return;
        }

        showLoading('Генерация через GigaChat...');
        try {
            const resp = await fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: textToSend,
                    system_prompt: '',
                }),
            });
            const result = await resp.json();

            if (result.error) {
                llmResultEdit.value = `❌ ${result.error}`;
                saveLlmConvertedBtn.style.display = 'none';
                copyResultBtn.style.display = 'none';
            } else {
                llmResultEdit.value = result.result;
                saveLlmConvertedBtn.style.display = 'inline-flex';
                copyResultBtn.style.display = 'inline-flex';
            }
        } catch (err) {
            console.error(err);
            llmResultEdit.value = `Ошибка запроса: ${err.message}`;
        } finally {
            hideLoading();
        }
    }

    // ═══ Фиксация ответа LLM как готового текста таблицы ═══
    saveLlmConvertedBtn.addEventListener('click', async () => {
        const text = llmResultEdit.value.trim();
        if (!text) {
            alert('Поле ответа LLM пустое.');
            return;
        }
        await commitConvertedText(text);
    });

    async function commitConvertedText(text) {
        showLoading('Сохранение текста таблицы...');
        try {
            const resp = await fetch(`/api/files/${state.activeFileId}/tables/${state.currentTableIndex}/converted`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: state.activeFileId,
                    table_index: state.currentTableIndex,
                    converted_text: text,
                }),
            });
            if (!resp.ok) throw new Error('Ошибка сохранения');
            const res = await resp.json();

            if (!state.activeFileData.converted_tables) {
                state.activeFileData.converted_tables = {};
            }
            state.activeFileData.converted_tables[strIndex(state.currentTableIndex)] = text;

            updateCurrentTableStatus();
            checkAllTablesConverted();

            alert(`✅ Текст для Таблицы ${state.currentTableIndex + 1} успешно сохранен! (${res.converted_count} из ${res.total_tables} готово)`);
        } catch (err) {
            alert('Ошибка: ' + err.message);
        } finally {
            hideLoading();
        }
    }

    function strIndex(idx) {
        return String(idx);
    }

    function updateCurrentTableStatus() {
        const data = state.activeFileData;
        if (!data || !data.tables || data.tables.length === 0) {
            tableConvertedStatus.style.display = 'none';
            return;
        }

        const idxStr = strIndex(state.currentTableIndex);
        const hasConverted = data.converted_tables && data.converted_tables[idxStr];

        tableConvertedStatus.style.display = 'block';
        if (hasConverted) {
            tableConvertedStatus.innerHTML = `✅ <b>Таблица ${state.currentTableIndex + 1} зафиксирована</b>. При формировании итогового документа она будет заменена на этот текст.`;
            tableConvertedStatus.style.borderLeft = '3px solid var(--accent-emerald)';
            tableConvertedStatus.style.background = 'rgba(16, 185, 129, 0.08)';
            if (!transformPreviewEdit.value && !llmResultEdit.value) {
                transformPreviewEdit.value = data.converted_tables[idxStr];
                savePreviewConvertedBtn.disabled = false;
            }
        } else {
            tableConvertedStatus.innerHTML = `⏳ <b>Таблица ${state.currentTableIndex + 1} ожидает фиксации</b>. Примените правила или ответ LLM и нажмите «В документ».`;
            tableConvertedStatus.style.borderLeft = '3px solid var(--accent-cyan)';
            tableConvertedStatus.style.background = 'rgba(6, 182, 212, 0.05)';
        }
    }


    function checkAllTablesConverted() {
        const data = state.activeFileData;
        if (!data || !data.tables || data.tables.length === 0) {
            downloadConvertedBtn.classList.add('hidden');
            return;
        }

        const total = data.tables.length;
        const converted = data.converted_tables ? Object.keys(data.converted_tables).length : 0;

        if (converted >= total && total > 0) {
            downloadConvertedBtn.classList.remove('hidden');
        } else {
            downloadConvertedBtn.classList.add('hidden');
        }
    }

    // ═══ Скачивание итогового документа ═══
    downloadConvertedBtn.addEventListener('click', () => {
        if (!state.activeFileId) return;
        window.open(`/api/files/${state.activeFileId}/download-converted`, '_blank');
    });

    // ═══ Копирование результата ═══
    copyResultBtn.addEventListener('click', () => {
        const text = llmResultEdit.value;
        if (text) {
            navigator.clipboard.writeText(text)
                .then(() => {
                    copyResultBtn.textContent = '✅ Скопировано!';
                    setTimeout(() => { copyResultBtn.textContent = '📋 Копировать'; }, 2000);
                });
        }
    });

    // ═══ Настройки ═══
    let currentAuthMode = 'key';

    const authModeButtons = document.querySelectorAll('#auth-mode-switch .segmented-option, #auth-mode-switch .segment-btn');
    const authKeyFields = $('#auth-key-fields');
    const authCertFields = $('#auth-cert-fields');

    authModeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            setAuthMode(btn.dataset.mode);
        });
    });


    function setAuthMode(mode) {
        currentAuthMode = mode;
        authModeButtons.forEach(b => {
            b.classList.toggle('active', b.dataset.mode === mode);
        });
        if (mode === 'key') {
            authKeyFields.classList.remove('hidden');
            authCertFields.classList.add('hidden');
        } else {
            authKeyFields.classList.add('hidden');
            authCertFields.classList.remove('hidden');
        }
    }

    settingsBtn.addEventListener('click', openSettings);
    closeSettingsBtn.addEventListener('click', closeSettings);
    settingsModal.addEventListener('click', (e) => {
        if (e.target === settingsModal) closeSettings();
    });
    saveSettingsBtn.addEventListener('click', saveSettings);
    tempSlider.addEventListener('input', () => {
        tempValue.textContent = tempSlider.value;
    });

    async function openSettings() {
        try {
            const resp = await fetch('/api/settings');
            const s = await resp.json();
            setAuthMode(s.auth_mode || 'key');
            $('#auth-key').value = s.auth_key || '';
            $('#cert-file').value = s.cert_file || '';
            $('#key-file').value = s.key_file || '';
            $('#ca-file').value = s.ca_file || '';
            $('#scope-select').value = s.scope || 'GIGACHAT_API_PERS';
            $('#model-select').value = s.model || 'GigaChat';
            tempSlider.value = s.temperature ?? 0.7;
            tempValue.textContent = s.temperature ?? 0.7;
            $('#system-prompt').value = s.system_prompt || '';
            // OCR поля
            if ($('#ocr-engine-select')) $('#ocr-engine-select').value = s.ocr_engine || 'rapidocr';
            if ($('#ocr-lang-select')) $('#ocr-lang-select').value = s.ocr_lang || 'rus+eng';
            if ($('#ocr-enabled')) $('#ocr-enabled').checked = s.ocr_enabled !== false;
        } catch (err) {
            console.error(err);
        }
        settingsModal.classList.remove('hidden');
    }

    function closeSettings() {
        settingsModal.classList.add('hidden');
    }

    // Переключение вкладок в модалке настроек
    const settingsTabButtons = document.querySelectorAll('.settings-tab-btn');
    const settingsTabPanels = document.querySelectorAll('.settings-tab-content');

    settingsTabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.dataset.tab;
            settingsTabButtons.forEach(b => b.classList.toggle('active', b.dataset.tab === targetTab));
            settingsTabPanels.forEach(p => {
                p.classList.toggle('hidden', p.id !== `settings-tab-${targetTab}`);
            });
        });
    });


    async function saveSettings() {
        const payload = {
            auth_mode: currentAuthMode,
            auth_key: $('#auth-key').value.trim(),
            cert_file: $('#cert-file').value.trim(),
            key_file: $('#key-file').value.trim(),
            ca_file: $('#ca-file').value.trim(),
            scope: $('#scope-select').value,
            model: $('#model-select').value,
            temperature: parseFloat(tempSlider.value),
            system_prompt: $('#system-prompt').value.trim(),
            ocr_engine: $('#ocr-engine-select') ? $('#ocr-engine-select').value : 'rapidocr',
            ocr_lang: $('#ocr-lang-select') ? $('#ocr-lang-select').value : 'rus+eng',
            ocr_enabled: $('#ocr-enabled') ? $('#ocr-enabled').checked : true,
        };


        showLoading('Сохранение настроек...');
        try {
            const resp = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!resp.ok) throw new Error('Ошибка сервера при сохранении');
            closeSettings();
            alert('✅ Настройки успешно сохранены на сервере!');
        } catch (err) {
            alert('Ошибка сохранения: ' + err.message);
        } finally {
            hideLoading();
        }
    }

    // ═══ Поп-ап окно: Справочник правил ═══
    const openRulesModalBtn = $('#open-rules-modal-btn');
    const rulesGuideModal = $('#rules-guide-modal');
    const closeRulesModalBtn = $('#close-rules-modal');
    const closeRulesModalBottomBtn = $('#close-rules-modal-bottom');
    const guideTabButtons = document.querySelectorAll('.guide-tab-btn');
    const guideContentPanels = document.querySelectorAll('.guide-content-panel');

    if (openRulesModalBtn) {
        openRulesModalBtn.addEventListener('click', () => {
            rulesGuideModal.classList.remove('hidden');
        });
    }

    function closeRulesGuide() {
        if (rulesGuideModal) rulesGuideModal.classList.add('hidden');
    }

    if (closeRulesModalBtn) closeRulesModalBtn.addEventListener('click', closeRulesGuide);
    if (closeRulesModalBottomBtn) closeRulesModalBottomBtn.addEventListener('click', closeRulesGuide);
    if (rulesGuideModal) {
        rulesGuideModal.addEventListener('click', (e) => {
            if (e.target === rulesGuideModal) closeRulesGuide();
        });
    }

    // Переключение вкладок в справочнике
    guideTabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.dataset.tab;
            guideTabButtons.forEach(b => b.classList.toggle('active', b.dataset.tab === targetTab));
            guideContentPanels.forEach(p => {
                p.classList.toggle('hidden', p.id !== `tab-${targetTab}`);
            });
        });
    });

    // Быстрая вставка шаблона правила из справочника в поле ввода
    document.querySelectorAll('.copy-rule-template').forEach(btn => {
        btn.addEventListener('click', () => {
            const template = btn.getAttribute('data-template');
            if (template && rulesInput) {
                rulesInput.value = template;
                closeRulesGuide();
                // Фокус на поле ввода и мягкая подсветка
                rulesInput.focus();
                const originalText = btn.textContent;
                btn.textContent = '✅ Вставлено!';
                setTimeout(() => { btn.textContent = originalText; }, 1500);
            }
        });
    });



    // ═══ Утилиты ═══
    function showLoading(text = 'Обработка...') {
        loadingText.textContent = text;
        loadingOverlay.classList.remove('hidden');
    }
    function hideLoading() {
        loadingOverlay.classList.add('hidden');
    }
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
});
