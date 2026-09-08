(function () {
    var uploadDraftForms = [];
    var uploadDraftCleanupBound = false;

    function parseJsonResponse(response, fallbackMessage) {
        return response.text().then(function (raw) {
            var payload;
            try {
                payload = raw ? JSON.parse(raw) : null;
            } catch (error) {
                var status = response.status ? "（HTTP " + response.status + "）" : "";
                throw new Error(
                    (fallbackMessage || "服务器返回了无效响应") +
                    status + "，请检查 Gunicorn/Nginx 日志"
                );
            }
            if (!payload || typeof payload !== "object") {
                var emptyStatus = response.status ? "（HTTP " + response.status + "）" : "";
                throw new Error(
                    (fallbackMessage || "服务器返回了无效响应") +
                    emptyStatus + "，请检查 Gunicorn/Nginx 日志"
                );
            }
            if (!response.ok || payload.success === false) {
                var message = payload.msg || payload.message || "请求失败";
                if (response.status && message === "请求失败") {
                    message += "（HTTP " + response.status + "）";
                }
                throw new Error(message);
            }
            return payload;
        });
    }

    function request(url, options) {
        options = options || {};
        var method = String(options.method || "GET").toUpperCase();
        var requestUrl = String(url);
        if (method === "GET" || method === "HEAD") {
            requestUrl += (requestUrl.indexOf("?") >= 0 ? "&" : "?") +
                "_fresh=" + Date.now();
        }
        options.cache = "no-store";
        options.headers = Object.assign({"Content-Type": "application/json"}, options.headers || {});
        return fetch(requestUrl, options).then(function (response) {
            return parseJsonResponse(response, "服务器返回了无效响应");
        });
    }

    function uploadDraftStorageKey(form) {
        return "amazon-ai-upload-draft:" +
            String(window.location.pathname || "") + ":" +
            String(form && form.id || "");
    }

    function normalizeAssetIds(values) {
        var ids = [];
        (Array.isArray(values) ? values : []).forEach(function (value) {
            var id = Number(value);
            if (Number.isFinite(id) && id > 0 && ids.indexOf(id) < 0) {
                ids.push(id);
            }
        });
        return ids;
    }

    function readUploadDraftIds(form) {
        try {
            var stored = window.sessionStorage.getItem(
                uploadDraftStorageKey(form)
            );
            if (stored !== null) {
                return normalizeAssetIds(JSON.parse(stored || "[]"));
            }
        } catch (error) {
            // Fall back to the current form state when storage is unavailable.
        }
        return normalizeAssetIds(form && form._amazonDraftAssetIds);
    }

    function writeUploadDraftIds(form, ids) {
        var normalized = normalizeAssetIds(ids);
        if (form) form._amazonDraftAssetIds = normalized;
        try {
            if (normalized.length) {
                window.sessionStorage.setItem(
                    uploadDraftStorageKey(form),
                    JSON.stringify(normalized)
                );
            } else {
                window.sessionStorage.removeItem(uploadDraftStorageKey(form));
            }
        } catch (error) {
            // Private browsing may disable sessionStorage; pagehide still retries in memory.
        }
    }

    function rememberUploadDraftAssets(form, assets) {
        var ids = readUploadDraftIds(form);
        (assets || []).forEach(function (asset) {
            if (asset && asset.id != null) ids.push(asset.id);
        });
        writeUploadDraftIds(form, ids);
    }

    function forgetUploadDraftAsset(form, assetId) {
        var targetId = String(assetId);
        writeUploadDraftIds(
            form,
            readUploadDraftIds(form).filter(function (id) {
                return String(id) !== targetId;
            })
        );
    }

    function clearUploadDraft(form) {
        writeUploadDraftIds(form, []);
    }

    function uploadDraftCleanupUrl(form) {
        var configured = String(form && form.dataset.cleanupUploadUrl || "");
        if (configured) return configured;
        var deleteUrl = String(form && form.dataset.deleteUploadUrl || "");
        return deleteUrl ? deleteUrl.replace(/\/?$/, "/cleanup") : "";
    }

    function cleanupUploadDraft(form) {
        var ids = readUploadDraftIds(form);
        var url = uploadDraftCleanupUrl(form);
        if (!ids.length || !url) return Promise.resolve(null);
        return request(url, {
            method: "POST",
            body: JSON.stringify({asset_ids: ids})
        }).then(function (result) {
            var retryIds = result.data && Array.isArray(
                result.data.retry_asset_ids
            ) ? result.data.retry_asset_ids : [];
            writeUploadDraftIds(form, retryIds);
            return result;
        });
    }

    function sendUploadDraftCleanup(form) {
        var ids = readUploadDraftIds(form);
        var url = uploadDraftCleanupUrl(form);
        if (!ids.length || !url) return;
        var body = JSON.stringify({asset_ids: ids});
        var sent = false;
        if (navigator.sendBeacon) {
            try {
                sent = navigator.sendBeacon(
                    url,
                    new Blob([body], {type: "application/json"})
                );
            } catch (error) {
                sent = false;
            }
        }
        if (!sent) {
            try {
                fetch(url, {
                    method: "POST",
                    body: body,
                    headers: {"Content-Type": "application/json"},
                    credentials: "same-origin",
                    cache: "no-store",
                    keepalive: true
                });
            } catch (error) {
                // The next page load retries the same sessionStorage draft.
            }
        }
    }

    function registerUploadDraftForm(form) {
        if (form && uploadDraftForms.indexOf(form) < 0) {
            form._amazonTaskRequestStarted = false;
            uploadDraftForms.push(form);
        }
        if (uploadDraftCleanupBound) return;
        uploadDraftCleanupBound = true;
        window.addEventListener("pagehide", function () {
            uploadDraftForms.forEach(function (item) {
                if (!item._amazonTaskRequestStarted) {
                    sendUploadDraftCleanup(item);
                }
            });
        });
    }

    function formBody(form) {
        var body = {};
        new FormData(form).forEach(function (value, key) {
            if (typeof File !== "undefined" && value instanceof File) return;
            body[key] = value;
        });
        return body;
    }

    function setResult(form, text, error) {
        var target = form.querySelector(".amazon-form-result");
        if (target) {
            target.textContent = text;
            target.style.color = error ? "#b42318" : "";
        }
    }

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function statusText(status) {
        return {
            PENDING: "待执行",
            RUNNING: "执行中",
            SUCCEEDED: "成功",
            FAILED: "失败",
            CANCELLED: "已取消"
        }[status] || status || "未知";
    }

    function statusClass(status) {
        return {
            RUNNING: "blue",
            SUCCEEDED: "green",
            FAILED: "red",
            CANCELLED: "orange"
        }[status] || "";
    }

    function displayTaskId(task) {
        if (!task) return "";
        if (task.task_number != null) return String(task.task_number);
        if (task.id != null) return String(task.id);
        return String(task.display_id || task.task_display_id || task.task_code || "");
    }

    function displaySavedTaskId(task) {
        if (
            task &&
            task.task_type === "BASIC_INFO_CORRECT"
        ) {
            return String(
                task.display_id ||
                task.response_filename ||
                task.task_number ||
                task.id ||
                ""
            );
        }
        return displayTaskId(task);
    }

    function renderRecentTasks(items) {
        var body = document.getElementById("amazonRecentTasks");
        if (!body) return;
        if (!items || !items.length) {
            body.innerHTML = '<tr><td colspan="5" class="amazon-empty-cell">暂无任务记录</td></tr>';
            return;
        }
        body.innerHTML = items.map(function (item) {
            return "<tr>" +
                '<td><span class="amazon-task-code">' + escapeHtml(displayTaskId(item)) + "</span></td>" +
                '<td><span class="amazon-task-title" title="' + escapeHtml(item.title) + '">' + escapeHtml(item.title) + "</span></td>" +
                '<td><span class="amazon-task-type">' + escapeHtml(item.task_type_label || item.task_type) + "</span></td>" +
                '<td><span class="amazon-status ' + statusClass(item.status) + '">' + escapeHtml(statusText(item.status)) + "</span></td>" +
                '<td>' + escapeHtml(item.created_at) + "</td>" +
                "</tr>";
        }).join("");
    }

    function renderTaskTypeStats(items) {
        var target = document.getElementById("amazonTaskTypeStats");
        if (!target) return;
        if (!items || !items.length) {
            target.innerHTML = '<div class="amazon-empty-shortcuts">暂无统计数据</div>';
            return;
        }
        target.innerHTML = items.map(function (item) {
            return '<div class="amazon-type-row"><span>' +
                escapeHtml(item.title || item.task_type) + "</span><span>" +
                escapeHtml(item.count) + "</span></div>";
        }).join("");
    }

    function renderList(targetId, items, titleKey, bodyKey) {
        var target = document.getElementById(targetId);
        if (!target) return;
        if (!items || !items.length) {
            target.textContent = "暂无数据";
            return;
        }
        target.innerHTML = items.map(function (item) {
            var title = item[titleKey] || item.id || "记录";
            var body = item[bodyKey] || item.analysis_text || item.summary || "";
            return '<div class="amazon-list-item"><strong>' +
                escapeHtml(title) + '</strong><span>' +
                escapeHtml(body) + '</span></div>';
        }).join("");
    }

    function getTaskHistoryConfig(listApi) {
        return {
            competitors: {
                historyPath: "/amazon-ai/api/competitors/history",
                resultPath: "/amazon-ai/api/competitors/history/",
                emptyText: "暂无竞品分析历史",
                historyLabel: "竞品分析历史",
                editableName: true
            },
            differentiation: {
                historyPath: "/amazon-ai/api/differentiation/history",
                resultPath: "/amazon-ai/api/differentiation/history/",
                emptyText: "暂无差异化分析历史",
                historyLabel: "差异化分析历史",
                editableName: true
            },
            basicInfo: {
                historyPath: "/amazon-ai/api/basic-info/history",
                resultPath: "/amazon-ai/api/basic-info/history/",
                emptyText: "暂无基础信息修正历史",
                historyLabel: "基础信息修正历史",
                editableName: false
            },
            listing: {
                historyPath: "/amazon-ai/api/listing/history",
                resultPath: "/amazon-ai/api/listing/history/",
                emptyText: "暂无 Listing 创作历史",
                historyLabel: "Listing 创作历史",
                editableName: true
            }
        }[listApi] || null;
    }

    function supportsCustomTaskName(task) {
        return Boolean(
            task &&
            ["COMPETITOR_ANALYZE", "DIFFERENTIATION_GENERATE", "LISTING_GENERATE"]
                .indexOf(task.task_type) >= 0
        );
    }

    function saveTaskCustomName(taskRef, customName) {
        return request(
            "/amazon-ai/api/tasks/" +
            encodeURIComponent(taskRef) +
            "/custom-name",
            {
                method: "POST",
                body: JSON.stringify({custom_name: String(customName == null ? "" : customName)})
            }
        );
    }

    function renderSavedTaskHistory(targetId, items, config) {
        var target = document.getElementById(targetId);
        if (!target) return;
        config = config || getTaskHistoryConfig("competitors") || {};
        if (!items || !items.length) {
            target.innerHTML = '<div class="amazon-empty-shortcuts">' +
                escapeHtml(config.emptyText || "暂无分析历史") + '</div>';
            return;
        }
        target.innerHTML = items.map(function (item) {
            var taskCode = String(item.task_code || "");
            var detailId = "amazon-saved-task-" + safeDomId(taskCode);
            var title = item.title || item.task_type_label || "竞品分析";
            var status = statusText(item.status);
            var detailMessage = item.status === "SUCCEEDED"
                ? "点击查看完整分析结果"
                : (item.error_message || "该任务没有可展开的完整结果");
            var editableName = Boolean(
                config.editableName && supportsCustomTaskName(item)
            );
            return '<details class="amazon-saved-task" data-task-code="' +
                escapeHtml(taskCode) + '">' +
                '<summary><span class="amazon-saved-task-main">' +
                '<strong>' + escapeHtml(displaySavedTaskId(item)) + '</strong>' +
                '<span class="amazon-saved-task-title" title="' +
                escapeHtml(title) + '">' + escapeHtml(title) + '</span>' +
                '<span class="amazon-saved-task-meta">' +
                escapeHtml(status) + ' · ' + escapeHtml(item.created_at || "") +
                '</span></span><span class="amazon-saved-task-actions">' +
                '<button type="button" class="amazon-button quiet amazon-saved-task-view">查看</button>' +
                (editableName
                    ? '<button type="button" class="amazon-button quiet amazon-saved-task-edit">编辑名称</button>'
                    : "") +
                '<button type="button" class="amazon-button quiet amazon-saved-task-delete">删除</button>' +
                '</span></summary>' +
                '<div class="amazon-saved-task-body" id="' + detailId +
                '"><div class="amazon-helper">' + escapeHtml(detailMessage) +
                '</div></div></details>';
        }).join("");

        target.querySelectorAll(".amazon-saved-task").forEach(function (item) {
            var taskCode = item.dataset.taskCode || "";
            var viewButton = item.querySelector(".amazon-saved-task-view");
            var editButton = item.querySelector(".amazon-saved-task-edit");
            var deleteButton = item.querySelector(".amazon-saved-task-delete");
            var body = item.querySelector(".amazon-saved-task-body");
            var loaded = false;
            var loading = false;
            var titleNode = item.querySelector(".amazon-saved-task-title");
            var originalTitle = titleNode ? titleNode.textContent : "";

            function restoreTitle() {
                if (!titleNode) return;
                titleNode.textContent = originalTitle;
                titleNode.title = originalTitle;
                if (editButton) {
                    editButton.dataset.editing = "0";
                    editButton.disabled = false;
                    editButton.textContent = "编辑名称";
                }
            }

            function startNameEdit(event) {
                event.preventDefault();
                event.stopPropagation();
                if (!titleNode || !editButton) return;
                if (editButton.dataset.editing === "1") {
                    var input = titleNode.querySelector(".amazon-saved-task-name-input");
                    editButton.disabled = true;
                    editButton.textContent = "保存中...";
                    saveTaskCustomName(taskCode, input ? input.value : "")
                        .then(function () {
                            return refreshSavedTaskHistory(targetId, config);
                        })
                        .catch(function (error) {
                            editButton.disabled = false;
                            editButton.textContent = "保存";
                            window.alert(error.message);
                        });
                    return;
                }
                titleNode.innerHTML =
                    '<input type="text" class="amazon-saved-task-name-input" value="' +
                    escapeHtml(originalTitle) + '">';
                var nameInput = titleNode.querySelector(
                    ".amazon-saved-task-name-input"
                );
                editButton.dataset.editing = "1";
                editButton.textContent = "保存";
                if (nameInput) {
                    nameInput.addEventListener("click", function (inputEvent) {
                        inputEvent.stopPropagation();
                    });
                    nameInput.addEventListener("keydown", function (inputEvent) {
                        if (inputEvent.key === "Escape") {
                            inputEvent.preventDefault();
                            restoreTitle();
                        } else if (inputEvent.key === "Enter") {
                            inputEvent.preventDefault();
                            editButton.click();
                        }
                    });
                    nameInput.focus();
                    nameInput.select();
                }
            }

            function loadResult() {
                if (loaded || loading || !taskCode || !body) {
                    return Promise.resolve();
                }
                loading = true;
                body.innerHTML = '<div class="amazon-loading">读取分析结果中...</div>';
                return request(
                    (config.resultPath || "/amazon-ai/api/competitors/history/") +
                    encodeURIComponent(taskCode) + "/result"
                ).then(function (result) {
                    var resultTask = result.data || {};
                    renderTaskResult(
                        body.id,
                        resultTask,
                        resultTask.task_type_label || "竞品分析"
                    );
                    loaded = true;
                }).catch(function (error) {
                    body.innerHTML = '<div class="amazon-helper is-error">' +
                        escapeHtml(error.message) + '</div>';
                }).finally(function () {
                    loading = false;
                });
            }

            item.addEventListener("toggle", function () {
                if (item.open) {
                    viewButton.textContent = "收起";
                    loadResult();
                } else {
                    viewButton.textContent = "查看";
                }
            });
            if (viewButton) {
                viewButton.addEventListener("click", function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    item.open = !item.open;
                });
            }
            if (editButton) {
                editButton.addEventListener("click", startNameEdit);
            }
            if (deleteButton) {
                deleteButton.addEventListener("click", function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    if (!window.confirm(
                        "确定删除" +
                        (config.historyLabel || "分析") +
                        " " +
                        (displaySavedTaskId(items.find(function (entry) {
                            return String(entry.task_code || "") === taskCode;
                        })) || taskCode) +
                        " 吗？关联的 GoFastDFS 文件也会删除。"
                    )) {
                        return;
                    }
                    deleteButton.disabled = true;
                    deleteButton.textContent = "删除中...";
                    request(
                        "/amazon-ai/api/tasks/" + encodeURIComponent(taskCode),
                        {method: "DELETE"}
                    ).then(function () {
                        return refreshSavedTaskHistory(targetId, config);
                    }).catch(function (error) {
                        deleteButton.disabled = false;
                        deleteButton.textContent = "删除";
                        window.alert(error.message);
                    });
                });
            }
        });
    }

    function refreshSavedTaskHistory(targetId, config) {
        config = config || getTaskHistoryConfig("competitors");
        return request(config.historyPath).then(function (result) {
            renderSavedTaskHistory(targetId, result.data || [], config);
        });
    }

    function safeDomId(value) {
        return String(value || "result").replace(/[^A-Za-z0-9_-]/g, "-");
    }

    function bindTabActivation(refresh) {
        if (typeof refresh !== "function") return;
        window.addEventListener("message", function (event) {
            if (event.source !== window.parent ||
                event.origin !== window.location.origin) {
                return;
            }
            var message = event.data || {};
            if (message.type !== "pear-tab-activated") return;
            Promise.resolve().then(refresh).catch(function () {});
        });
    }

    function copyText(text, button) {
        var value = String(text || "");
        var done = function () {
            if (!button) return;
            var original = button.textContent;
            button.textContent = "已复制";
            window.setTimeout(function () {
                button.textContent = original;
            }, 1200);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(value).then(done);
        }
        var textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand("copy");
            done();
        } finally {
            document.body.removeChild(textarea);
        }
        return Promise.resolve();
    }

    function bindCopyButtons(container) {
        if (!container) return;
        container.querySelectorAll("[data-copy-target]").forEach(function (button) {
            if (button.dataset.bound === "1") return;
            button.dataset.bound = "1";
            button.addEventListener("click", function () {
                var target = document.getElementById(button.dataset.copyTarget);
                copyText(target ? target.textContent : "", button);
            });
        });
    }

    function hasMarkdownSyntax(text) {
        return /(^|\n)\s{0,3}(#{1,6}\s|[-*+]\s+|\d+[.)]\s+|>\s?|```|~~~|---+\s*$)/m.test(text) ||
            /(\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|`[^`\n]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/.test(text);
    }

    function renderInlineMarkdown(value) {
        var html = escapeHtml(value);
        var tokens = [];

        function token(content) {
            var marker = "\uE000" + tokens.length + "\uE001";
            tokens.push(content);
            return marker;
        }

        html = html.replace(/`([^`\n]+)`/g, function (match, code) {
            return token("<code>" + code + "</code>");
        });
        html = html.replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            function (match, label, url) {
                return token(
                    '<a href="' + url +
                    '" target="_blank" rel="noopener noreferrer">' +
                    label + "</a>"
                );
            }
        );
        html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
        html = html.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
        html = html.replace(
            /(^|[^\*])\*([^*\n]+)\*([^\*]|$)/g,
            "$1<em>$2</em>$3"
        );
        html = html.replace(
            /(^|[^_])_([^_\n]+)_([^_]|$)/g,
            "$1<em>$2</em>$3"
        );
        return html.replace(/\uE000(\d+)\uE001/g, function (match, index) {
            return tokens[Number(index)] || "";
        });
    }

    function renderMarkdown(text) {
        var lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
        var html = [];
        var listType = "";
        var inCode = false;
        var codeLines = [];

        function splitTableRow(line) {
            var value = String(line || "").trim();
            if (value.charAt(0) === "|") value = value.slice(1);
            if (value.charAt(value.length - 1) === "|") {
                value = value.slice(0, -1);
            }
            return value.split("|").map(function (cell) {
                return cell.trim();
            });
        }

        function closeList() {
            if (listType) {
                html.push("</" + listType + ">");
                listType = "";
            }
        }

        function closeCode() {
            if (!inCode) return;
            html.push(
                '<pre class="amazon-markdown-code"><code>' +
                escapeHtml(codeLines.join("\n")) +
                "</code></pre>"
            );
            codeLines = [];
            inCode = false;
        }

        for (var lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
            var line = lines[lineIndex];
            var fence = line.match(/^\s*(```|~~~)/);
            if (fence) {
                closeList();
                if (inCode) closeCode();
                else inCode = true;
                continue;
            }
            if (inCode) {
                codeLines.push(line);
                continue;
            }

            var heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
            var unordered = line.match(/^\s*[-*+]\s+(.+)$/);
            var ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
            var quote = line.match(/^\s{0,3}>\s?(.*)$/);
            var tableSeparator = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(
                lines[lineIndex + 1] || ""
            );
            if (!line.trim()) {
                closeList();
                continue;
            }
            if (line.indexOf("|") >= 0 && tableSeparator) {
                closeList();
                var headers = splitTableRow(line);
                var tableRows = [];
                lineIndex += 2;
                while (
                    lineIndex < lines.length &&
                    lines[lineIndex].trim() &&
                    lines[lineIndex].indexOf("|") >= 0
                ) {
                    tableRows.push(splitTableRow(lines[lineIndex]));
                    lineIndex += 1;
                }
                lineIndex -= 1;
                html.push('<div class="amazon-markdown-table-wrap"><table><thead><tr>');
                headers.forEach(function (cell) {
                    html.push("<th>" + renderInlineMarkdown(cell) + "</th>");
                });
                html.push("</tr></thead>");
                if (tableRows.length) {
                    html.push("<tbody>");
                    tableRows.forEach(function (row) {
                        html.push("<tr>");
                        headers.forEach(function (cell, cellIndex) {
                            html.push(
                                "<td>" +
                                renderInlineMarkdown(row[cellIndex] || "") +
                                "</td>"
                            );
                        });
                        html.push("</tr>");
                    });
                    html.push("</tbody>");
                }
                html.push("</table></div>");
                continue;
            }
            if (heading) {
                closeList();
                var level = heading[1].length;
                html.push(
                    "<h" + level + ">" +
                    renderInlineMarkdown(heading[2]) +
                    "</h" + level + ">"
                );
                continue;
            }
            if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
                closeList();
                html.push("<hr>");
                continue;
            }
            if (unordered || ordered) {
                var nextType = unordered ? "ul" : "ol";
                if (listType !== nextType) {
                    closeList();
                    listType = nextType;
                    html.push("<" + listType + ">");
                }
                html.push(
                    "<li>" +
                    renderInlineMarkdown((unordered || ordered)[1]) +
                    "</li>"
                );
                continue;
            }
            closeList();
            if (quote) {
                html.push(
                    '<blockquote>' +
                    renderInlineMarkdown(quote[1]) +
                    "</blockquote>"
                );
                continue;
            }
            html.push("<p>" + renderInlineMarkdown(line) + "</p>");
        }

        closeList();
        closeCode();
        return html.join("");
    }

    function renderTaskResult(targetId, task, label) {
        var target = document.getElementById(targetId);
        if (!target || !task) return;
        var resultText = String(
            task.response_text ||
            (task.response_sections || []).map(function (item) {
                return item.content || "";
            }).join("\n\n") ||
            ""
        );
        var taskId = safeDomId(
            task.task_number != null
                ? task.task_number
                : (task.id != null ? task.id : task.task_code)
        );
        var resultPrefix = "amazon-result-" + safeDomId(targetId) + "-" + taskId;
        var rawResultId = resultPrefix + "-raw";
        var viewerHtml = resultText
            ? (
                hasMarkdownSyntax(resultText)
                    ? '<article class="amazon-markdown-body">' +
                        renderMarkdown(resultText) + "</article>"
                    : '<pre class="amazon-result-text">' +
                        escapeHtml(resultText) + "</pre>"
            )
            : '<div class="amazon-empty-shortcuts">暂无完整结果</div>';
        var download = task.response_download_url
            ? '<a class="amazon-button quiet" href="' +
                escapeHtml(task.response_download_url) +
                '" download="' + escapeHtml(task.response_filename || "amazon-ai-result.txt") +
                '" target="_blank" rel="noopener">下载 TXT</a>'
            : '<span class="amazon-helper">TXT 暂无下载地址，页面结果仍可复制</span>';
        target.hidden = false;
        target.innerHTML =
            '<div class="amazon-result-toolbar"><span class="amazon-task-code">' +
            escapeHtml(label || task.task_type_label || "任务结果") + " · " +
            escapeHtml(displayTaskId(task)) + '</span><span class="amazon-result-actions">' +
            '<button type="button" class="amazon-button quiet amazon-copy-button" ' +
            'data-copy-target="' + rawResultId + '">复制全文</button>' +
            download + '</span></div>' +
            '<div class="amazon-result-viewer">' + viewerHtml + "</div>" +
            '<pre id="' + rawResultId + '" class="amazon-result-raw">' +
            escapeHtml(resultText) + "</pre>";
        bindCopyButtons(target);
    }

    function loadResultTasks(taskType) {
        var query = new URLSearchParams();
        query.set("task_type", taskType);
        return request("/amazon-ai/api/result-tasks?" + query.toString())
            .then(function (result) { return result.data || []; });
    }

    function formUploadedAssets(form) {
        if (!Array.isArray(form._amazonUploadedAssets)) {
            form._amazonUploadedAssets = [];
        }
        return form._amazonUploadedAssets;
    }

    function setAssetIds(form, assets) {
        var input = form.querySelector('[name="input_asset_ids"]');
        if (!input) {
            input = document.createElement("input");
            input.type = "hidden";
            input.name = "input_asset_ids";
            form.appendChild(input);
        }
        input.value = JSON.stringify((assets || []).map(function (asset) {
            return asset.id;
        }).filter(function (id) {
            return id != null && String(id) !== "";
        }));
    }

    function renderUploadedFiles(form, targetId) {
        var target = document.getElementById(targetId);
        if (!target) return;
        var assets = formUploadedAssets(form);
        var pending = Array.isArray(form._amazonPendingUploads)
            ? form._amazonPendingUploads
            : [];
        var errors = Array.isArray(form._amazonUploadErrors)
            ? form._amazonUploadErrors
            : [];
        var html = pending.map(function (item) {
            return '<span class="amazon-file-chip is-pending">' +
                '<span class="amazon-file-name">' +
                escapeHtml(item.name) +
                '</span><span class="amazon-file-state">上传中</span></span>';
        });
        html = html.concat(assets.map(function (asset) {
            var assetId = String(asset.id);
            return '<span class="amazon-file-chip" data-asset-id="' +
                escapeHtml(assetId) + '">' +
                '<span class="amazon-file-name">' +
                escapeHtml(asset.filename || "未命名文件") +
                '</span><span class="amazon-file-state">7天保留</span>' +
                '<button type="button" class="amazon-file-remove" ' +
                'data-asset-remove="' + escapeHtml(assetId) +
                '" title="删除并清理 GoFastDFS 文件">删除</button></span>';
        }));
        html = html.concat(errors.map(function (item) {
            return '<span class="amazon-file-chip is-error">' +
                '<span class="amazon-file-name">' +
                escapeHtml(item.name) +
                '</span><span class="amazon-file-state">' +
                escapeHtml(item.message || "上传失败") +
                "</span></span>";
        }));
        target.innerHTML = html.length
            ? html.join("")
            : '<span class="amazon-helper">暂无已上传文件</span>';

        target.querySelectorAll("[data-asset-remove]").forEach(function (button) {
            button.addEventListener("click", function (event) {
                event.preventDefault();
                event.stopPropagation();
                var assetId = String(button.getAttribute("data-asset-remove") || "");
                var deleteUrl = String(form.dataset.deleteUploadUrl || "");
                if (!assetId || !deleteUrl) return;
                button.disabled = true;
                button.textContent = "删除中";
                request(
                    deleteUrl.replace(/\/?$/, "/") +
                    encodeURIComponent(assetId),
                    {method: "DELETE"}
                ).then(function () {
                    form._amazonUploadedAssets = formUploadedAssets(form).filter(
                        function (asset) {
                            return String(asset.id) !== assetId;
                        }
                    );
                    forgetUploadDraftAsset(form, assetId);
                    setAssetIds(form, form._amazonUploadedAssets);
                    renderUploadedFiles(form, targetId);
                }).catch(function (error) {
                    button.disabled = false;
                    button.textContent = "删除";
                    window.alert(error.message);
                });
            });
        });
    }

    function addAssetIds(form, assets, targetId) {
        var current = formUploadedAssets(form);
        var byId = {};
        current.concat(assets || []).forEach(function (asset) {
            if (!asset || asset.id == null) return;
            byId[String(asset.id)] = asset;
        });
        form._amazonUploadedAssets = Object.keys(byId).map(function (id) {
            return byId[id];
        });
        rememberUploadDraftAssets(form, assets);
        setAssetIds(form, form._amazonUploadedAssets);
        renderUploadedFiles(form, targetId);
    }

    function maxUploadFileBytes(form) {
        var configured = Number(form && form.dataset.maxFileBytes);
        if (!Number.isFinite(configured) || configured < 1) {
            return 512 * 1024 * 1024;
        }
        return configured;
    }

    function formatUploadFileSize(size) {
        var value = Number(size) || 0;
        var units = ["B", "KB", "MB", "GB"];
        var unitIndex = 0;
        while (value >= 1024 && unitIndex < units.length - 1) {
            value /= 1024;
            unitIndex += 1;
        }
        var precision = unitIndex === 0 ? 0 : (value >= 10 ? 0 : 1);
        return value.toFixed(precision) + " " + units[unitIndex];
    }

    function oversizedFileMessage(file, maximumSize) {
        return "文件“" + file.name + "”大小为 " +
            formatUploadFileSize(file.size) +
            "，超过单个文件最大限制 " +
            formatUploadFileSize(maximumSize) +
            "，文件未上传";
    }

    function uploadFiles(files, url, form, targetId) {
        files = Array.from(files || []).filter(function (file) {
            return file && file.name;
        });
        if (!files.length) return Promise.resolve([]);
        var batch = files.map(function (file, index) {
            return {
                file: file,
                key: Date.now() + "-" + index + "-" + file.name,
                name: file.name
            };
        });
        var batchKeys = batch.map(function (item) { return item.key; });
        var maximumSize = maxUploadFileBytes(form);
        var oversizedFailures = batch.filter(function (item) {
            return Number(item.file.size) > maximumSize;
        }).map(function (item) {
            return {
                key: item.key,
                name: item.name,
                message: oversizedFileMessage(item.file, maximumSize)
            };
        });
        var uploadBatch = batch.filter(function (item) {
            return Number(item.file.size) <= maximumSize;
        });
        form._amazonPendingUploads = (
            Array.isArray(form._amazonPendingUploads)
                ? form._amazonPendingUploads
                : []
        ).concat(uploadBatch.map(function (item) {
            return {key: item.key, name: item.name};
        }));
        form._amazonUploadErrors = (
            Array.isArray(form._amazonUploadErrors)
                ? form._amazonUploadErrors
                : []
        ).filter(function (item) {
            return batchKeys.indexOf(item.key) < 0;
        }).concat(oversizedFailures);
        renderUploadedFiles(form, targetId);

        if (oversizedFailures.length &&
            typeof window !== "undefined" &&
            typeof window.alert === "function") {
            window.alert(
                oversizedFailures.map(function (item) {
                    return item.message;
                }).join("\n")
            );
        }
        if (!uploadBatch.length) {
            return Promise.reject(new Error(
                oversizedFailures.map(function (item) {
                    return item.message;
                }).join("；")
            ));
        }

        return Promise.all(uploadBatch.map(function (item) {
            var body = new FormData();
            body.append("file", item.file);
            return fetch(url, {
                method: "POST",
                body: body,
                credentials: "same-origin",
                cache: "no-store"
            }).then(function (response) {
                return parseJsonResponse(response, "服务器返回了无效响应").then(function (payload) {
                    if (!payload.data || payload.data.id == null) {
                        throw new Error("文件上传成功但服务器没有返回文件记录");
                    }
                    return {
                        key: item.key,
                        asset: payload.data
                    };
                });
            }).catch(function (error) {
                return {
                    key: item.key,
                    name: item.name,
                    error: error
                };
            });
        })).then(function (results) {
            var successAssets = results.filter(function (item) {
                return item.asset;
            }).map(function (item) {
                return item.asset;
            });
            var failures = results.filter(function (item) {
                return item.error;
            });
            form._amazonPendingUploads = (
                form._amazonPendingUploads || []
            ).filter(function (item) {
                return batchKeys.indexOf(item.key) < 0;
            });
            form._amazonUploadErrors = (
                form._amazonUploadErrors || []
            ).filter(function (item) {
                return batchKeys.indexOf(item.key) < 0;
            }).concat(oversizedFailures).concat(
                failures.map(function (item) {
                    return {
                        key: item.key,
                        name: item.name || "未命名文件",
                        message: item.error.message
                    };
                })
            );
            if (successAssets.length) {
                addAssetIds(form, successAssets, targetId);
            } else {
                renderUploadedFiles(form, targetId);
            }
            var allFailures = oversizedFailures.concat(failures);
            if (allFailures.length) {
                var message = oversizedFailures.map(function (item) {
                    return item.message;
                }).concat(failures.map(function (item) {
                    return item.error.message;
                })).join("；");
                if (successAssets.length) {
                    message = successAssets.length + " 个文件上传成功，" +
                        allFailures.length + " 个文件上传失败：" + message;
                    setResult(form, message, true);
                    return successAssets;
                }
                throw new Error(message);
            }
            return successAssets;
        });
    }

    function queueUploadFiles(form, files, url, targetId) {
        var previous = form._amazonUploadQueue || Promise.resolve([]);
        var next = previous.catch(function () {
            return [];
        }).then(function () {
            return uploadFiles(files, url, form, targetId);
        });
        form._amazonUploadQueue = next.catch(function () {
            return [];
        });
        return next;
    }

    function bindUploadDropzone(dropzone, fileInput, onFiles) {
        if (!dropzone || !fileInput || !onFiles) return;
        dropzone.addEventListener("click", function (event) {
            if (event.target === fileInput) return;
            fileInput.click();
        });
        dropzone.addEventListener("keydown", function (event) {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            fileInput.click();
        });
        var dragDepth = 0;
        dropzone.addEventListener("dragenter", function (event) {
            event.preventDefault();
            event.stopPropagation();
            dragDepth += 1;
            dropzone.classList.add("is-dragging");
        });
        dropzone.addEventListener("dragover", function (event) {
            event.preventDefault();
            event.stopPropagation();
            if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
        });
        dropzone.addEventListener("dragleave", function (event) {
            event.preventDefault();
            event.stopPropagation();
            dragDepth = Math.max(0, dragDepth - 1);
            if (!dragDepth) dropzone.classList.remove("is-dragging");
        });
        dropzone.addEventListener("drop", function (event) {
            event.preventDefault();
            event.stopPropagation();
            dragDepth = 0;
            dropzone.classList.remove("is-dragging");
            onFiles(event.dataTransfer ? event.dataTransfer.files : []);
        });
    }

    function setOptions(select, items, valueKey, labelBuilder, emptyLabel) {
        if (!select) return;
        var currentValue = select.value;
        var options = [
            '<option value="">' + escapeHtml(emptyLabel || "请选择") + "</option>"
        ];
        (items || []).forEach(function (item) {
            options.push(
                '<option value="' + escapeHtml(item[valueKey]) + '">' +
                escapeHtml(labelBuilder(item)) + "</option>"
            );
        });
        select.innerHTML = options.join("");
        if (currentValue && Array.from(select.options).some(function (option) {
            return option.value === currentValue;
        })) {
            select.value = currentValue;
        }
    }

    function populateFormOptions(form, data) {
        var state = data.global_chat_model || {};
        form.querySelectorAll(".amazon-option-model").forEach(function (select) {
            setOptions(
                select,
                data.chat_models || [],
                "id",
                function (item) {
                    return item.name + " · " + item.model_code + " · " + item.provider_name;
                },
                "请选择语言模型"
            );
            if (state.model && state.model.id) {
                select.value = String(state.model.id);
            }
        });

        var availableSkills = data.skills || [];
        form.querySelectorAll(
            ".amazon-option-skill, .amazon-option-diff-skill"
        ).forEach(function (select) {
            var emptyLabel = form.id === "listingForm"
                ? "不选择 Skill（可选）"
                : "请选择本次使用的 Skill";
            setOptions(
                select,
                availableSkills,
                "id",
                function (item) {
                    var mediaType = item.media_type
                        ? " · " + item.media_type
                        : "";
                    return item.name + " · " + item.code + mediaType;
                },
                emptyLabel
            );
        });

        form.querySelectorAll(".amazon-option-product").forEach(function (select) {
            var emptyLabel = select.id === "basicInfoProductId"
                ? "不写入产品核心卖点"
                : "不关联产品核心卖点";
            setOptions(
                select,
                data.products || [],
                "id",
                function (item) {
                    return item.name + " · " + item.code +
                        (item.has_core_selling_points
                            ? " · 已配置核心卖点"
                            : " · 待维护核心卖点");
                },
                emptyLabel
            );
        });

    }

    function loadOptionsForForm(form) {
        return request("/amazon-ai/api/options").then(function (result) {
            var data = result.data || {};
            populateFormOptions(form, data);
            return data;
        });
    }

    function renderHistory(items) {
        var body = document.getElementById("amazonHistoryTable");
        if (!body) return;
        if (!items || !items.length) {
            body.innerHTML = '<tr><td colspan="9" class="amazon-empty-cell">暂无任务记录</td></tr>';
            return;
        }
        body.innerHTML = items.map(function (item) {
            var taskCode = String(item.task_code || "");
            var taskId = item.id != null ? String(item.id) : "";
            var detailId = "amazon-history-detail-" + safeDomId(taskCode);
            return '<tr class="amazon-history-row">' +
                '<td class="amazon-history-select-cell"><input type="checkbox" class="amazon-history-select" ' +
                'data-task-id="' + escapeHtml(taskId) + '" data-task-code="' +
                escapeHtml(taskCode) + '" aria-label="选择任务 ' + escapeHtml(displayTaskId(item)) + '"></td>' +
                '<td><span class="amazon-task-code">' + escapeHtml(displayTaskId(item)) + "</span></td>" +
                '<td><span class="amazon-task-title" title="' + escapeHtml(item.title) + '">' + escapeHtml(item.title) + "</span></td>" +
                '<td>' + escapeHtml(item.task_type_label || item.task_type) + "</td>" +
                '<td>' + escapeHtml(item.model_code || "") + "</td>" +
                '<td>' + escapeHtml(item.skill_name || "") + "</td>" +
            '<td><span class="amazon-status ' + statusClass(item.status) + '">' + escapeHtml(statusText(item.status)) + "</span></td>" +
            '<td>' + escapeHtml(item.created_at) + "</td>" +
            '<td class="amazon-history-actions">' +
            '<button type="button" class="amazon-button quiet amazon-history-view" ' +
            'data-task-code="' + escapeHtml(taskCode) + '">查看</button>' +
            (supportsCustomTaskName(item)
                ? '<button type="button" class="amazon-button quiet amazon-history-edit" ' +
                    'data-task-code="' + escapeHtml(taskCode) + '">编辑名称</button>'
                : "") +
            '<button type="button" class="amazon-button quiet amazon-history-delete" ' +
            'data-task-code="' + escapeHtml(taskCode) + '">删除</button>' +
                "</td></tr>" +
                '<tr class="amazon-history-detail-row" hidden>' +
                '<td colspan="9"><div id="' + detailId + '" class="amazon-history-detail"></div></td></tr>';
        }).join("");
    }

    window.AmazonAI = {
        request: request,
        bindDashboardControls: function () {
            var button = document.getElementById("amazonRefreshDashboard");
            if (!button || button.dataset.bound === "1") return;
            button.dataset.bound = "1";
            button.addEventListener("click", function () {
                button.classList.add("is-loading");
                button.setAttribute("aria-busy", "true");
                window.AmazonAI.loadDashboard().finally(function () {
                    button.classList.remove("is-loading");
                    button.removeAttribute("aria-busy");
                });
            });
        },
        loadDashboard: function () {
            return request("/amazon-ai/api/dashboard").then(function (result) {
                var data = result.data || {};
                Object.keys(data).forEach(function (key) {
                    var node = document.querySelector('[data-stat="' + key + '"]');
                    if (node) node.textContent = data[key];
                });
                renderRecentTasks(data.recent_tasks || []);
                renderTaskTypeStats(data.task_type_stats || []);
                var state = data.global_chat_model || {};
                var badge = document.getElementById("amazonModelBadge");
                var text = document.getElementById("amazonModelState");
                if (!badge || !text) return;
                badge.textContent = state.allowed ? "可执行" : "禁止执行";
                badge.className = "amazon-badge " + (state.allowed ? "ok" : "bad");
                text.textContent = state.model ?
                    ("当前模型：" + state.model.model_code + "，供应商：" + state.model.provider_name +
                    (state.allowed ? "" : "；当前模型或供应商未启用，或尚未配置 API Key")) :
                    "当前没有配置全局语言模型，Amazon AI 任务不可执行";
            }).catch(function (error) {
                var text = document.getElementById("amazonModelState");
                if (text) text.textContent = error.message;
            });
        },
        loadTasks: function () {
            request("/amazon-ai/api/tasks?page=1&page_size=8").then(function (result) {
                renderRecentTasks(result.data || []);
            });
        },
        bindHistory: function () {
            var page = 1;
            var hasMore = false;
            var loading = false;
            var historyBody = document.getElementById("amazonHistoryTable");
            var searchButton = document.getElementById("amazonHistorySearch");
            var refreshButton = document.getElementById("amazonHistoryRefresh");
            var previousButton = document.getElementById("amazonHistoryPrevious");
            var nextButton = document.getElementById("amazonHistoryNext");
            var selectAll = document.getElementById("amazonHistorySelectAll");
            var batchDeleteButton = document.getElementById("amazonHistoryBatchDelete");
            var selectionInfo = document.getElementById("amazonHistorySelectionInfo");

            function selectedCheckboxes() {
                return historyBody ?
                    Array.from(historyBody.querySelectorAll(".amazon-history-select:checked")) :
                    [];
            }

            function updateSelectionControls() {
                var checkboxes = historyBody ?
                    Array.from(historyBody.querySelectorAll(".amazon-history-select")) :
                    [];
                var selected = selectedCheckboxes();
                if (selectAll) {
                    selectAll.checked = Boolean(checkboxes.length && selected.length === checkboxes.length);
                    selectAll.indeterminate = Boolean(selected.length && selected.length < checkboxes.length);
                    selectAll.disabled = loading || !checkboxes.length;
                }
                if (batchDeleteButton) {
                    batchDeleteButton.disabled = loading || !selected.length;
                }
                if (selectionInfo) {
                    selectionInfo.textContent = selected.length ? ("已选择 " + selected.length + " 条") : "";
                }
            }

            function updateControls() {
                if (searchButton) searchButton.disabled = loading;
                if (refreshButton) refreshButton.disabled = loading;
                if (previousButton) {
                    previousButton.disabled = loading || page <= 1;
                }
                if (nextButton) {
                    nextButton.disabled = loading || !hasMore;
                }
                updateSelectionControls();
            }

            function load(targetPage) {
                if (loading) return;
                loading = true;
                page = Math.max(1, Number(targetPage) || 1);
                updateControls();
                var query = new URLSearchParams();
                var type = document.getElementById("amazonHistoryType").value;
                var status = document.getElementById("amazonHistoryStatus").value;
                if (type) query.set("task_type", type);
                if (status) query.set("status", status);
                query.set("page", page);
                query.set("page_size", "20");
                request("/amazon-ai/api/history?" + query.toString()).then(function (result) {
                    renderHistory(result.data || []);
                    hasMore = Boolean(result.meta && result.meta.has_more);
                    document.getElementById("amazonHistoryPageInfo").textContent =
                        "第 " + page + " 页" + (hasMore ? "，还有更多" : "");
                    if (selectAll) {
                        selectAll.checked = false;
                        selectAll.indeterminate = false;
                    }
                }).catch(function (error) {
                    document.getElementById("amazonHistoryTable").innerHTML =
                        '<tr><td colspan="9" class="amazon-empty-cell">' + escapeHtml(error.message) + "</td></tr>";
                }).finally(function () {
                    loading = false;
                    updateControls();
                });
            }
            if (historyBody) {
                historyBody.addEventListener("change", function (event) {
                    if (event.target === selectAll) {
                        historyBody.querySelectorAll(".amazon-history-select").forEach(function (checkbox) {
                            checkbox.checked = selectAll.checked;
                        });
                    }
                    updateSelectionControls();
                });
                historyBody.addEventListener("click", function (event) {
                    var viewButton = event.target.closest(".amazon-history-view");
                    var editButton = event.target.closest(".amazon-history-edit");
                    var deleteButton = event.target.closest(".amazon-history-delete");
                    var button = viewButton || editButton || deleteButton;
                    if (!button) return;
                    var taskCode = button.getAttribute("data-task-code") || "";
                    if (!taskCode) return;
                    if (editButton) {
                        event.preventDefault();
                        var titleNode = button.closest("tr").querySelector(
                            ".amazon-task-title"
                        );
                        var currentName = titleNode ? titleNode.textContent : "";
                        var nextName = window.prompt(
                            "请输入自定义任务名称，留空可恢复系统标题",
                            currentName
                        );
                        if (nextName === null) return;
                        editButton.disabled = true;
                        editButton.textContent = "保存中...";
                        saveTaskCustomName(taskCode, nextName)
                            .then(function () {
                                load(page);
                            })
                            .catch(function (error) {
                                editButton.disabled = false;
                                editButton.textContent = "编辑名称";
                                window.alert(error.message);
                            });
                        return;
                    }
                    if (viewButton) {
                        var detailRow = viewButton.closest("tr").nextElementSibling;
                        var detailId = "amazon-history-detail-" + safeDomId(taskCode);
                        var detail = document.getElementById(detailId);
                        if (!detailRow || !detail) return;
                        if (!detailRow.hidden && detailRow.dataset.loaded === "1") {
                            detailRow.hidden = true;
                            viewButton.textContent = "查看";
                            return;
                        }
                        detailRow.hidden = false;
                        viewButton.disabled = true;
                        if (detailRow.dataset.loaded !== "1") {
                            detail.innerHTML = '<div class="amazon-loading">读取结果中...</div>';
                            request(
                                "/amazon-ai/api/tasks/" +
                                encodeURIComponent(taskCode) + "/result"
                            ).then(function (result) {
                                renderTaskResult(
                                    detailId,
                                    result.data,
                                    result.data.task_type_label
                                );
                                detailRow.dataset.loaded = "1";
                                viewButton.textContent = "收起";
                            }).catch(function (error) {
                                detail.innerHTML =
                                    '<div class="amazon-loading amazon-error-text">' +
                                    escapeHtml(error.message) + "</div>";
                            }).finally(function () {
                                viewButton.disabled = false;
                            });
                        } else {
                            viewButton.disabled = false;
                            viewButton.textContent = "收起";
                        }
                        return;
                    }
                    if (!window.confirm(
                        "确定删除任务 " +
                        button.closest("tr").querySelector(".amazon-task-code").textContent +
                        " 吗？关联的 GoFastDFS 文件也会删除。"
                    )) {
                        return;
                    }
                    deleteButton.disabled = true;
                    deleteButton.textContent = "删除中...";
                    request(
                        "/amazon-ai/api/tasks/" + encodeURIComponent(taskCode),
                        {method: "DELETE"}
                    ).then(function () {
                        load(page);
                    }).catch(function (error) {
                        deleteButton.disabled = false;
                        deleteButton.textContent = "删除";
                        window.alert(error.message);
                    });
                });
            }
            if (selectAll) {
                selectAll.addEventListener("change", function () {
                    if (!historyBody) return;
                    historyBody.querySelectorAll(".amazon-history-select").forEach(function (checkbox) {
                        checkbox.checked = selectAll.checked;
                    });
                    updateSelectionControls();
                });
            }
            if (batchDeleteButton) {
                batchDeleteButton.addEventListener("click", function () {
                    var selected = selectedCheckboxes().map(function (checkbox) {
                        return checkbox.getAttribute("data-task-id") || "";
                    }).filter(function (value) { return value; });
                    if (!selected.length) return;
                    if (!window.confirm(
                        "确定删除选中的 " + selected.length +
                        " 条任务吗？关联的 GoFastDFS 文件也会删除。"
                    )) {
                        return;
                    }
                    batchDeleteButton.disabled = true;
                    loading = true;
                    updateControls();
                    request("/amazon-ai/api/tasks/batch-delete", {
                        method: "POST",
                        body: JSON.stringify({task_ids: selected})
                    }).then(function (result) {
                        loading = false;
                        window.alert(result.msg || "批量删除完成");
                        load(page);
                    }).catch(function (error) {
                        loading = false;
                        updateControls();
                        window.alert(error.message);
                        load(page);
                    });
                });
            }
            if (searchButton) searchButton.addEventListener("click", function () { load(1); });
            if (refreshButton) refreshButton.addEventListener("click", function () { load(page); });
            if (previousButton) previousButton.addEventListener("click", function () { load(page - 1); });
            if (nextButton) nextButton.addEventListener("click", function () { load(page + 1); });
            updateControls();
            load(1);
        },
        bindAnalysisForm: function (formId, url, listId, listApi) {
            var form = document.getElementById(formId);
            if (!form) return;
            registerUploadDraftForm(form);
            cleanupUploadDraft(form).catch(function (error) {
                setResult(form, "上次未运行文件清理失败：" + error.message, true);
            });
            var historyConfig = getTaskHistoryConfig(listApi);
            function refreshSavedList() {
                if (historyConfig) {
                    return refreshSavedTaskHistory(listId, historyConfig);
                }
                if (!listApi) return Promise.resolve();
                if (!listId) return Promise.resolve();
                return request("/amazon-ai/api/" + listApi).then(function (result) {
                    var key = listApi === "competitors" ? "title" :
                        (listApi === "keywords" ? "keyword" : "title");
                    renderList(listId, result.data || [], key, "analysis_text");
                });
            }
            loadOptionsForForm(form).catch(function (error) {
                setResult(form, error.message, true);
            });
            refreshSavedList().catch(function (error) {
                var target = document.getElementById(listId);
                if (target) target.textContent = error.message;
            });
            var fileInput = form.querySelector('input[type="file"]');
            var fileList = form.querySelector(".amazon-file-list");
            var dropzone = form.querySelector("[data-upload-dropzone]");
            var uploadPromise = Promise.resolve([]);
            function handleFiles(files) {
                if (!fileInput || !fileList) return;
                uploadPromise = queueUploadFiles(
                    form,
                    files,
                    form.dataset.uploadUrl,
                    fileList.id
                );
                uploadPromise.catch(function (error) {
                    setResult(form, error.message, true);
                });
            }
            if (fileInput && fileList) {
                fileInput.addEventListener("change", function () {
                    handleFiles(fileInput.files);
                    fileInput.value = "";
                });
            }
            bindUploadDropzone(dropzone, fileInput, handleFiles);
            form.addEventListener("submit", function (event) {
                event.preventDefault();
                form._amazonTaskRequestStarted = true;
                setResult(form, "任务执行中...", false);
                uploadPromise.then(function () {
                    return request(
                        url,
                        {method: "POST", body: JSON.stringify(formBody(form))}
                    );
                })
                    .then(function (result) {
                        setResult(form, result.msg || "完成", false);
                        clearUploadDraft(form);
                        form._amazonTaskRequestStarted = false;
                        return refreshSavedList();
                    })
                    .catch(function (error) {
                        form._amazonTaskRequestStarted = false;
                        setResult(form, error.message, true);
                    });
            });
        },
        bindBasicInfoForm: function (formId) {
            var form = document.getElementById(formId);
            if (!form) return;
            var competitorSelect = document.getElementById("basicCompetitorTaskCode");
            var differentiationSelect = document.getElementById("basicDifferentiationTaskCode");
            var content = document.getElementById("basicInfoContent");
            var filenameInput = document.getElementById("basicInfoFilename");
            var sourceItemsByCode = {};
            var historyConfig = getTaskHistoryConfig("basicInfo");

            function sourceLabel(task) {
                if (!task) return "";
                var title = String(task.title || "").trim();
                if (title) return title;
                var filename = String(task.response_filename || "").trim();
                if (filename) {
                    return filename.replace(/\.[^.]+$/, "");
                }
                return displayTaskId(task);
            }

            function loadSources() {
                return request("/amazon-ai/api/basic-info/source-tasks").then(function (result) {
                    var items = result.data || [];
                    sourceItemsByCode = {};
                    items.forEach(function (item) {
                        sourceItemsByCode[String(item.task_code || "")] = item;
                    });
                    setOptions(
                        competitorSelect,
                        items.filter(function (item) {
                            return item.task_type === "COMPETITOR_ANALYZE";
                        }),
                        "task_code",
                        sourceLabel,
                        "选择竞品分析任务 ID"
                    );
                    setOptions(
                        differentiationSelect,
                        items.filter(function (item) {
                            return item.task_type === "DIFFERENTIATION_GENERATE";
                        }),
                        "task_code",
                        sourceLabel,
                        "选择差异化分析任务 ID"
                    );
                });
            }

            function sourceDisplayId(code) {
                var item = sourceItemsByCode[String(code || "")];
                return sourceLabel(item) || code;
            }

            function loadResult(code) {
                if (!code) return Promise.resolve("");
                return request(
                    "/amazon-ai/api/basic-info/source-tasks/" +
                    encodeURIComponent(code) + "/result"
                ).then(function (result) {
                    var data = result.data || {};
                    return data.response_text || (data.response_sections || []).map(function (item) {
                        return item.content || "";
                    }).join("\n\n");
                });
            }

            function refreshContent() {
                var competitorCode = competitorSelect && competitorSelect.value;
                var differentiationCode = differentiationSelect && differentiationSelect.value;
                if (!content) return;
                var sources = [];
                if (competitorCode) {
                    sources.push({
                        code: competitorCode,
                        label: "竞品分析结果"
                    });
                }
                if (differentiationCode) {
                    sources.push({
                        code: differentiationCode,
                        label: "差异化分析结果"
                    });
                }
                if (!sources.length) {
                    content.value = "";
                    content.dataset.sourceLoaded = "0";
                    return;
                }
                content.value = "读取分析结果中...";
                Promise.all(sources.map(function (source) {
                    return loadResult(source.code);
                })).then(function (values) {
                    content.value = sources.map(function (source, index) {
                        return "===== " + source.label + " | " +
                            sourceDisplayId(source.code) + " =====\n" +
                            values[index];
                    }).join("\n\n");
                    content.dataset.sourceLoaded = "1";
                }).catch(function (error) {
                    content.value = "";
                    setResult(form, error.message, true);
                });
            }

            if (competitorSelect) competitorSelect.addEventListener("change", refreshContent);
            if (differentiationSelect) differentiationSelect.addEventListener("change", refreshContent);
            if (filenameInput) {
                filenameInput.addEventListener("input", function () {
                    if (filenameInput.value.trim()) {
                        filenameInput.classList.remove("is-invalid");
                        filenameInput.removeAttribute("aria-invalid");
                    }
                });
            }
            function refreshLatest() {
                return Promise.all([
                    loadOptionsForForm(form),
                    loadSources(),
                    refreshSavedTaskHistory("basicInfoList", historyConfig)
                ]);
            }

            refreshLatest().catch(function (error) {
                setResult(form, error.message, true);
            });
            bindTabActivation(function () {
                return refreshLatest().catch(function (error) {
                    setResult(form, error.message, true);
                });
            });

            form.addEventListener("submit", function (event) {
                event.preventDefault();
                if (!filenameInput || !filenameInput.value.trim()) {
                    if (filenameInput) {
                        filenameInput.classList.add("is-invalid");
                        filenameInput.setAttribute("aria-invalid", "true");
                        filenameInput.focus();
                    }
                    window.alert("文件未命名，请先输入基础信息修正文件名");
                    return;
                }
                setResult(form, "正在保存基础信息...", false);
                request("/amazon-ai/api/basic-info/save", {
                    method: "POST",
                    body: JSON.stringify(formBody(form))
                }).then(function (result) {
                    setResult(form, result.msg || "基础信息修正已保存", false);
                    return refreshLatest();
                }).catch(function (error) {
                    setResult(form, error.message, true);
                });
            });
        },
        bindListingForm: function (formId) {
            var form = document.getElementById(formId);
            if (!form) return;
            registerUploadDraftForm(form);
            cleanupUploadDraft(form).catch(function (error) {
                setResult(form, "上次未运行文件清理失败：" + error.message, true);
            });
            var historyConfig = getTaskHistoryConfig("listing");
            function loadSourceSelectors() {
                var selectors = [
                    {
                        id: "listingCompetitorTaskCode",
                        type: "COMPETITOR_ANALYZE",
                        empty: "不选择竞品分析任务（可选）"
                    },
                    {
                        id: "listingDifferentiationTaskCode",
                        type: "DIFFERENTIATION_GENERATE",
                        empty: "不选择差异化分析任务（可选）"
                    },
                    {
                        id: "listingBasicInfoTaskCode",
                        type: "BASIC_INFO_CORRECT",
                        empty: "不选择基础信息修正任务（可选）"
                    }
                ];
                return Promise.all(selectors.map(function (item) {
                    return loadResultTasks(item.type).then(function (items) {
                        setOptions(
                            document.getElementById(item.id),
                            items,
                            "task_code",
                            function (task) {
                                if (task.task_type === "BASIC_INFO_CORRECT") {
                                    return task.response_filename ||
                                        displayTaskId(task);
                                }
                                return displayTaskId(task) + " · " +
                                    (task.title || task.task_type_label) +
                                    (task.finished_at ? " · " + task.finished_at : "");
                            },
                            item.empty
                        );
                    });
                }));
            }
            function refreshLatestOptions() {
                return loadOptionsForForm(form).then(function () {
                    return loadSourceSelectors();
                });
            }
            function refreshLatest() {
                return Promise.all([
                    refreshLatestOptions(),
                    refreshSavedTaskHistory("listingList", historyConfig)
                ]);
            }

            function hasListingInput() {
                var fields = [
                    '[name="skill_id"]',
                    '[name="studio_product_id"]',
                    '[name="competitor_task_code"]',
                    '[name="differentiation_task_code"]',
                    '[name="basic_info_task_code"]',
                    '[name="context"]'
                ];
                return fields.some(function (selector) {
                    var field = form.querySelector(selector);
                    return field && String(field.value || "").trim() !== "";
                }) || formUploadedAssets(form).length > 0;
            }

            refreshLatest().catch(function (error) {
                setResult(form, error.message, true);
            });
            bindTabActivation(function () {
                return refreshLatest().catch(function (error) {
                    setResult(form, error.message, true);
                });
            });
            var fileInput = form.querySelector('input[type="file"]');
            var fileList = form.querySelector(".amazon-file-list");
            var uploadPromise = Promise.resolve([]);
            function handleFiles(files) {
                uploadPromise = queueUploadFiles(
                    form,
                    files,
                    form.dataset.uploadUrl,
                    fileList && fileList.id
                );
                uploadPromise.catch(function (error) {
                    setResult(form, error.message, true);
                });
            }
            if (fileInput && fileList) {
                fileInput.addEventListener("change", function () {
                    handleFiles(fileInput.files);
                    fileInput.value = "";
                });
            }
            bindUploadDropzone(
                form.querySelector("[data-upload-dropzone]"),
                fileInput,
                handleFiles
            );
            form.addEventListener("submit", function (event) {
                event.preventDefault();
                form._amazonTaskRequestStarted = true;
                setResult(form, "任务执行中...", false);
                uploadPromise.then(function () {
                    if (!hasListingInput()) {
                        throw new Error(
                            "请至少提供一项 Listing 输入：Skill、产品、来源任务、补充文件或创作要求"
                        );
                    }
                    return request("/amazon-ai/api/listing/generate", {
                        method: "POST",
                        body: JSON.stringify(formBody(form))
                    });
                }).then(function (result) {
                    setResult(form, result.msg || "完成", false);
                    clearUploadDraft(form);
                    form._amazonTaskRequestStarted = false;
                    return refreshSavedTaskHistory("listingList", historyConfig);
                }).catch(function (error) {
                    form._amazonTaskRequestStarted = false;
                    setResult(form, error.message, true);
                });
            });
        },
    };
}());
