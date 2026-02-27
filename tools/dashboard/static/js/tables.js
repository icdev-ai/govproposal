/**
 * CUI // SP-PROPIN
 *
 * GovProposal Dashboard — Table Enhancement Module
 * Adds search, sort, column filter, CSV export, and row count to all dashboard tables.
 * Extends window.ICDEV namespace (shared with charts.js).
 *
 * No external dependencies. Works with the rendered DOM only.
 * Auto-initializes on section.card elements that contain a table.data-table.
 */

(function () {
    "use strict";

    var NS = window.ICDEV || (window.ICDEV = {});

    // ========================================================================
    // Constants
    // ========================================================================

    var MAX_FILTER_CARDINALITY = 10;
    var SORT_ASC = "asc";
    var SORT_DESC = "desc";

    // Inline style fragments matching the GovProposal light theme
    var STYLES = {
        input: [
            "background: #ffffff",
            "color: #2c3e50",
            "border: 1px solid #dfe6e9",
            "border-radius: 4px",
            "padding: 5px 10px",
            "font-size: 0.8rem",
            "outline: none",
            "font-family: inherit",
            "min-width: 160px"
        ].join(";"),
        button: [
            "background: #0984e3",
            "color: #fff",
            "border: none",
            "border-radius: 4px",
            "padding: 5px 12px",
            "font-size: 0.78rem",
            "font-weight: 600",
            "cursor: pointer",
            "font-family: inherit",
            "white-space: nowrap"
        ].join(";"),
        rowCount: [
            "font-size: 0.75rem",
            "color: #7f8c8d",
            "padding: 6px 16px 8px",
            "text-align: right"
        ].join(";"),
        emptyMsg: [
            "text-align: center",
            "color: #7f8c8d",
            "padding: 32px 16px",
            "font-style: italic"
        ].join(";"),
        sortIndicator: [
            "margin-left: 4px",
            "font-size: 0.65rem",
            "opacity: 0.7"
        ].join(";"),
        thClickable: [
            "cursor: pointer",
            "user-select: none"
        ].join(";"),
        filterIcon: [
            "margin-left: 4px",
            "cursor: pointer",
            "font-size: 0.65rem",
            "opacity: 0.6",
            "position: relative"
        ].join(";"),
        filterDropdown: [
            "position: absolute",
            "top: 100%",
            "left: 0",
            "z-index: 100",
            "background: #ffffff",
            "border: 1px solid #dfe6e9",
            "border-radius: 4px",
            "padding: 8px",
            "min-width: 160px",
            "max-height: 220px",
            "overflow-y: auto",
            "box-shadow: 0 4px 16px rgba(0,0,0,0.12)",
            "font-weight: normal",
            "text-transform: none",
            "letter-spacing: normal"
        ].join(";"),
        filterLabel: [
            "display: flex",
            "align-items: center",
            "gap: 6px",
            "padding: 3px 0",
            "font-size: 0.8rem",
            "color: #2c3e50",
            "cursor: pointer",
            "white-space: nowrap"
        ].join(";"),
        headerControls: [
            "display: flex",
            "align-items: center",
            "gap: 8px"
        ].join(";")
    };

    // ========================================================================
    // Utility helpers
    // ========================================================================

    function sanitizeFilename(str) {
        return str.replace(/[^a-zA-Z0-9_\- ]/g, "").replace(/\s+/g, "_").substring(0, 80) || "export";
    }

    function cellText(td) {
        return (td.textContent || "").trim();
    }

    function isNumeric(str) {
        if (!str) return false;
        var cleaned = str.replace(/[,$%]/g, "");
        return cleaned !== "" && !isNaN(Number(cleaned));
    }

    function parseDate(str) {
        if (!str) return NaN;
        var d = new Date(str);
        return d.getTime();
    }

    function compareValues(a, b) {
        if (isNumeric(a) && isNumeric(b)) {
            return parseFloat(a.replace(/[,$%]/g, "")) - parseFloat(b.replace(/[,$%]/g, ""));
        }
        var da = parseDate(a);
        var db = parseDate(b);
        if (!isNaN(da) && !isNaN(db)) {
            return da - db;
        }
        return a.localeCompare(b, undefined, { sensitivity: "base" });
    }

    function getDataRows(tbody) {
        var rows = [];
        var trs = tbody.querySelectorAll("tr");
        for (var i = 0; i < trs.length; i++) {
            if (!trs[i].classList.contains("empty-row") && !trs[i].hasAttribute("data-gp-empty-msg")) {
                rows.push(trs[i]);
            }
        }
        return rows;
    }

    // ========================================================================
    // Table enhancer
    // ========================================================================

    /**
     * Enhance a single card container with search, sort, filter, export, and
     * row count capabilities.
     *
     * @param {HTMLElement} container - A section.card element containing table.data-table
     */
    function enhanceTable(container) {
        var table = container.querySelector("table.data-table");
        if (!table) return;

        var thead = table.querySelector("thead");
        var tbody = table.querySelector("tbody");
        if (!thead || !tbody) return;

        var allDataRows = getDataRows(tbody);
        if (allDataRows.length === 0) return;

        var ths = thead.querySelectorAll("th");
        var colCount = ths.length;
        if (colCount === 0) return;

        // ---- State ----
        var sortCol = -1;
        var sortDir = null;
        var searchTerm = "";
        var columnFilters = {};
        var openDropdown = null;

        // Hide existing empty-row elements
        var emptyRows = tbody.querySelectorAll("tr.empty-row");
        for (var er = 0; er < emptyRows.length; er++) {
            emptyRows[er].style.display = "none";
        }

        // ---- Build controls toolbar above the table ----
        var tableHeader = container.querySelector(".card-header");
        var controlsWrapper = document.createElement("div");
        controlsWrapper.setAttribute("style", STYLES.headerControls);

        var searchInput = document.createElement("input");
        searchInput.type = "text";
        searchInput.placeholder = "Search\u2026";
        searchInput.setAttribute("aria-label", "Search table rows");
        searchInput.setAttribute("style", STYLES.input);
        controlsWrapper.appendChild(searchInput);

        var exportBtn = document.createElement("button");
        exportBtn.type = "button";
        exportBtn.textContent = "Export CSV";
        exportBtn.setAttribute("aria-label", "Export visible rows as CSV");
        exportBtn.setAttribute("style", STYLES.button);
        controlsWrapper.appendChild(exportBtn);

        if (tableHeader) {
            tableHeader.appendChild(controlsWrapper);
        } else {
            var syntheticHeader = document.createElement("div");
            syntheticHeader.setAttribute("style", "padding: 10px 16px; display: flex; justify-content: flex-end; align-items: center;");
            syntheticHeader.appendChild(controlsWrapper);
            container.insertBefore(syntheticHeader, table);
        }

        // ---- Row count element ----
        var rowCountEl = document.createElement("div");
        rowCountEl.setAttribute("style", STYLES.rowCount);
        rowCountEl.setAttribute("aria-live", "polite");
        if (table.nextSibling) {
            container.insertBefore(rowCountEl, table.nextSibling);
        } else {
            container.appendChild(rowCountEl);
        }

        // ---- Empty message row ----
        var emptyMsgRow = document.createElement("tr");
        emptyMsgRow.setAttribute("data-gp-empty-msg", "1");
        var emptyMsgTd = document.createElement("td");
        emptyMsgTd.setAttribute("colspan", String(colCount));
        emptyMsgTd.setAttribute("style", STYLES.emptyMsg);
        emptyMsgTd.textContent = "No matching rows";
        emptyMsgRow.appendChild(emptyMsgTd);
        emptyMsgRow.style.display = "none";
        tbody.appendChild(emptyMsgRow);

        // ================================================================
        // Column sort setup
        // ================================================================

        var sortIndicators = [];

        for (var ci = 0; ci < colCount; ci++) {
            (function (colIndex) {
                var th = ths[colIndex];
                th.setAttribute("style", (th.getAttribute("style") || "") + ";" + STYLES.thClickable);
                th.setAttribute("aria-sort", "none");
                th.setAttribute("role", "columnheader");

                var indicator = document.createElement("span");
                indicator.setAttribute("style", STYLES.sortIndicator);
                indicator.setAttribute("aria-hidden", "true");
                indicator.textContent = "";
                th.appendChild(indicator);
                sortIndicators.push(indicator);

                th.addEventListener("click", function (e) {
                    if (e.target.closest && e.target.closest("[data-gp-filter-dropdown]")) return;
                    if (e.target.hasAttribute && e.target.hasAttribute("data-gp-filter-icon")) return;

                    if (sortCol === colIndex) {
                        sortDir = sortDir === SORT_ASC ? SORT_DESC : SORT_ASC;
                    } else {
                        sortCol = colIndex;
                        sortDir = SORT_ASC;
                    }
                    applyAll();
                });
            })(ci);
        }

        // ================================================================
        // Column filter setup (low-cardinality columns only)
        // ================================================================

        for (var fi = 0; fi < colCount; fi++) {
            (function (colIndex) {
                var uniqueValues = {};
                for (var ri = 0; ri < allDataRows.length; ri++) {
                    var cells = allDataRows[ri].querySelectorAll("td");
                    if (cells[colIndex]) {
                        var val = cellText(cells[colIndex]);
                        uniqueValues[val] = true;
                    }
                }
                var keys = Object.keys(uniqueValues);
                if (keys.length < 2 || keys.length > MAX_FILTER_CARDINALITY) return;

                keys.sort(function (a, b) {
                    return a.localeCompare(b, undefined, { sensitivity: "base" });
                });

                var th = ths[colIndex];
                th.style.position = "relative";

                var filterIcon = document.createElement("span");
                filterIcon.setAttribute("style", STYLES.filterIcon);
                filterIcon.setAttribute("data-gp-filter-icon", "1");
                filterIcon.setAttribute("aria-label", "Filter this column");
                filterIcon.setAttribute("role", "button");
                filterIcon.setAttribute("tabindex", "0");
                filterIcon.textContent = "\u25BC";
                th.appendChild(filterIcon);

                var dropdown = document.createElement("div");
                dropdown.setAttribute("style", STYLES.filterDropdown);
                dropdown.setAttribute("data-gp-filter-dropdown", "1");
                dropdown.style.display = "none";

                var checkboxes = [];

                for (var ki = 0; ki < keys.length; ki++) {
                    (function (value) {
                        var label = document.createElement("label");
                        label.setAttribute("style", STYLES.filterLabel);

                        var cb = document.createElement("input");
                        cb.type = "checkbox";
                        cb.checked = true;
                        cb.value = value;
                        cb.addEventListener("change", function () {
                            updateColumnFilter(colIndex, checkboxes);
                        });
                        checkboxes.push(cb);

                        var text = document.createElement("span");
                        text.textContent = value || "(empty)";

                        label.appendChild(cb);
                        label.appendChild(text);
                        dropdown.appendChild(label);
                    })(keys[ki]);
                }

                th.appendChild(dropdown);

                filterIcon.addEventListener("click", function (e) {
                    e.stopPropagation();
                    toggleDropdown(dropdown);
                });
                filterIcon.addEventListener("keydown", function (e) {
                    if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.stopPropagation();
                        toggleDropdown(dropdown);
                    }
                });

                dropdown.addEventListener("click", function (e) {
                    e.stopPropagation();
                });
            })(fi);
        }

        function toggleDropdown(dropdown) {
            if (openDropdown && openDropdown !== dropdown) {
                openDropdown.style.display = "none";
            }
            if (dropdown.style.display === "none") {
                dropdown.style.display = "block";
                openDropdown = dropdown;
            } else {
                dropdown.style.display = "none";
                openDropdown = null;
            }
        }

        function updateColumnFilter(colIndex, checkboxes) {
            var allChecked = true;
            var allowed = {};
            for (var i = 0; i < checkboxes.length; i++) {
                if (checkboxes[i].checked) {
                    allowed[checkboxes[i].value] = true;
                } else {
                    allChecked = false;
                }
            }
            if (allChecked) {
                delete columnFilters[colIndex];
            } else {
                columnFilters[colIndex] = allowed;
            }
            applyAll();
        }

        // ================================================================
        // Close dropdowns when clicking outside
        // ================================================================

        document.addEventListener("click", function (e) {
            if (openDropdown && !openDropdown.contains(e.target)) {
                openDropdown.style.display = "none";
                openDropdown = null;
            }
        });

        // ================================================================
        // Search handler
        // ================================================================

        searchInput.addEventListener("input", function () {
            searchTerm = searchInput.value.toLowerCase();
            applyAll();
        });

        // ================================================================
        // Export CSV handler
        // ================================================================

        exportBtn.addEventListener("click", function () {
            var visibleRows = getVisibleRows();
            var headers = [];
            for (var hi = 0; hi < colCount; hi++) {
                var headerText = ths[hi].childNodes[0];
                headers.push(headerText ? headerText.textContent.trim() : "");
            }

            var csvLines = [];
            csvLines.push(headers.map(csvEscape).join(","));

            for (var ri = 0; ri < visibleRows.length; ri++) {
                var cells = visibleRows[ri].querySelectorAll("td");
                var row = [];
                for (var ci2 = 0; ci2 < colCount; ci2++) {
                    row.push(csvEscape(cells[ci2] ? cellText(cells[ci2]) : ""));
                }
                csvLines.push(row.join(","));
            }

            var csvContent = csvLines.join("\n");
            var filename = "export";
            if (tableHeader) {
                var h2 = tableHeader.querySelector("h2,h3");
                if (h2) filename = sanitizeFilename(h2.textContent);
            }

            downloadCSV(csvContent, filename + ".csv");
        });

        // ================================================================
        // Core apply function: filter, sort, update visibility
        // ================================================================

        function applyAll() {
            var filtered = [];
            for (var i = 0; i < allDataRows.length; i++) {
                var row = allDataRows[i];
                if (!matchesSearch(row)) continue;
                if (!matchesFilters(row)) continue;
                filtered.push(row);
            }

            if (sortCol >= 0 && sortDir) {
                filtered.sort(function (a, b) {
                    var cellsA = a.querySelectorAll("td");
                    var cellsB = b.querySelectorAll("td");
                    var valA = cellsA[sortCol] ? cellText(cellsA[sortCol]) : "";
                    var valB = cellsB[sortCol] ? cellText(cellsB[sortCol]) : "";
                    var cmp = compareValues(valA, valB);
                    return sortDir === SORT_DESC ? -cmp : cmp;
                });
            }

            for (var h = 0; h < allDataRows.length; h++) {
                allDataRows[h].style.display = "none";
            }

            for (var s = 0; s < filtered.length; s++) {
                filtered[s].style.display = "";
                tbody.appendChild(filtered[s]);
            }

            for (var si = 0; si < sortIndicators.length; si++) {
                if (si === sortCol && sortDir) {
                    sortIndicators[si].textContent = sortDir === SORT_ASC ? " \u25B2" : " \u25BC";
                    ths[si].setAttribute("aria-sort", sortDir === SORT_ASC ? "ascending" : "descending");
                } else {
                    sortIndicators[si].textContent = "";
                    ths[si].setAttribute("aria-sort", "none");
                }
            }

            if (filtered.length === 0) {
                emptyMsgRow.style.display = "";
            } else {
                emptyMsgRow.style.display = "none";
            }

            updateRowCount(filtered.length, allDataRows.length);
        }

        function matchesSearch(row) {
            if (!searchTerm) return true;
            var cells = row.querySelectorAll("td");
            for (var c = 0; c < cells.length; c++) {
                if (cellText(cells[c]).toLowerCase().indexOf(searchTerm) !== -1) {
                    return true;
                }
            }
            return false;
        }

        function matchesFilters(row) {
            var cells = row.querySelectorAll("td");
            for (var colIdx in columnFilters) {
                if (!columnFilters.hasOwnProperty(colIdx)) continue;
                var allowed = columnFilters[colIdx];
                var idx = parseInt(colIdx, 10);
                var val = cells[idx] ? cellText(cells[idx]) : "";
                if (!allowed[val]) return false;
            }
            return true;
        }

        function getVisibleRows() {
            var visible = [];
            for (var i = 0; i < allDataRows.length; i++) {
                if (allDataRows[i].style.display !== "none") {
                    visible.push(allDataRows[i]);
                }
            }
            return visible;
        }

        function updateRowCount(shown, total) {
            if (shown === total) {
                rowCountEl.textContent = "Showing " + total + " row" + (total !== 1 ? "s" : "");
            } else {
                rowCountEl.textContent = "Showing " + shown + " of " + total + " rows";
            }
        }

        updateRowCount(allDataRows.length, allDataRows.length);
    }

    // ========================================================================
    // CSV helpers
    // ========================================================================

    function csvEscape(value) {
        if (value == null) return '""';
        var str = String(value);
        if (str.indexOf(",") !== -1 || str.indexOf('"') !== -1 || str.indexOf("\n") !== -1) {
            return '"' + str.replace(/"/g, '""') + '"';
        }
        return str;
    }

    function downloadCSV(csvContent, filename) {
        var blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        link.style.display = "none";
        document.body.appendChild(link);
        link.click();
        setTimeout(function () {
            document.body.removeChild(link);
            URL.revokeObjectURL(link.href);
        }, 100);
    }

    // ========================================================================
    // Public API
    // ========================================================================

    NS.enhanceTable = enhanceTable;

    // ========================================================================
    // Auto-initialization — targets section.card elements with table.data-table
    // ========================================================================

    function initTables() {
        var cards = document.querySelectorAll("section.card");
        for (var i = 0; i < cards.length; i++) {
            if (cards[i].querySelector("table.data-table")) {
                enhanceTable(cards[i]);
            }
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initTables);
    } else {
        initTables();
    }

})();
