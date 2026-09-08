(function () {
    function initBatchPromptPanel(panel) {
        if (!panel || panel.dataset.batchPromptReady === "1") return;
        panel.dataset.batchPromptReady = "1";

        var configuredMediaType = String(
            panel.dataset.mediaType || "ALL"
        ).toUpperCase();
        var fixedMediaType = configuredMediaType === "IMAGE" ||
            configuredMediaType === "VIDEO"
            ? configuredMediaType
            : "ALL";
        var overlay = panel.parentElement
            ? panel.parentElement.querySelector("[data-batch-prompt-overlay]")
            : null;
        var openButtons = document.querySelectorAll("[data-batch-prompt-open]");
        var form = overlay && overlay.querySelector("[data-batch-prompt-form]");
        var mediaTypeSelect = overlay &&
            overlay.querySelector("[data-batch-prompt-media]");
        var productSelect = overlay &&
            overlay.querySelector("[data-batch-prompt-product]");
        var skillSelect = overlay &&
            overlay.querySelector("[data-batch-prompt-skill]");
        var imageAspectRatioField = overlay &&
            overlay.querySelector(
                "[data-batch-prompt-image-aspect-ratio-field]"
            );
        var imageAspectRatioSelect = overlay &&
            overlay.querySelector("[data-batch-prompt-image-aspect-ratio]");
        var imageQualityField = overlay &&
            overlay.querySelector("[data-batch-prompt-image-quality-field]");
        var imageQualitySelect = overlay &&
            overlay.querySelector("[data-batch-prompt-image-quality]");
        var creativeInput = overlay &&
            overlay.querySelector("[data-batch-prompt-creative]");
        var styleSelect = overlay &&
            overlay.querySelector("[data-batch-prompt-style]");
        var customStyleInput = overlay &&
            overlay.querySelector("[data-batch-prompt-custom-style]");
        var styleManageButton = overlay &&
            overlay.querySelector("[data-batch-prompt-style-manage]");
        var styleManager = overlay &&
            overlay.querySelector("[data-batch-prompt-style-manager]");
        var styleInput = overlay &&
            overlay.querySelector("[data-batch-prompt-style-input]");
        var styleAddButton = overlay &&
            overlay.querySelector("[data-batch-prompt-style-add]");
        var styleList = overlay &&
            overlay.querySelector("[data-batch-prompt-style-list]");
        var rangeInput = overlay &&
            overlay.querySelector("[data-batch-prompt-range]");
        var countInput = overlay &&
            overlay.querySelector("[data-batch-prompt-count]");
        var countLabel = overlay &&
            overlay.querySelector("[data-batch-prompt-count-label]");
        var message = overlay &&
            overlay.querySelector("[data-batch-prompt-message]");
        var submitButton = overlay &&
            overlay.querySelector("[data-batch-prompt-submit]");
        var history = panel.querySelector("[data-batch-prompt-history]");
        var summary = panel.querySelector("[data-batch-prompt-summary]");
        var pageInfo = panel.querySelector("[data-batch-prompt-page-info]");
        var loadMoreButton = panel.querySelector(
            "[data-batch-prompt-load-more]"
        );
        var refreshButton = panel.querySelector(
            "[data-batch-prompt-refresh]"
        );
        var historyData = [];
        var historyPage = 1;
        var historyHasMore = false;
        var historyLoading = false;
        var optionsRequestNumber = 0;
        var optionData = {
            products: [],
            skills: [],
            styles: []
        };
        var mediaType = fixedMediaType === "VIDEO" ? "VIDEO" : "IMAGE";

        if (
            !overlay ||
            !form ||
            !productSelect ||
            !skillSelect ||
            !creativeInput ||
            !rangeInput ||
            !countInput ||
            !countLabel ||
            !message ||
            !submitButton ||
            !history ||
            !summary ||
            !pageInfo ||
            !loadMoreButton ||
            !refreshButton
        ) {
            return;
        }

        if (mediaTypeSelect) {
            var queryMediaType = new URLSearchParams(
                window.location.search
            ).get("media_type");
            queryMediaType = String(queryMediaType || "").toUpperCase();
            if (queryMediaType === "IMAGE" || queryMediaType === "VIDEO") {
                mediaType = queryMediaType;
            }
            mediaTypeSelect.value = mediaType;
        }

        function setMessage(text, isError) {
            message.textContent = text || "";
            message.classList.toggle("is-error", Boolean(isError));
        }

        function setCount(value, source) {
            var number = Number(value);
            if (!Number.isFinite(number)) number = 0;
            number = Math.max(0, Math.round(number));
            countInput.value = number;
            if (source !== "number") {
                rangeInput.value = Math.min(10, number);
            } else if (number <= 10) {
                rangeInput.value = number;
            }
            countLabel.textContent = number === 0
                ? "0 个版本（默认生成 10 个）"
                : number + " 个版本";
        }

        function syncCustomStyle() {
            if (!styleSelect || !customStyleInput) return;
            var isCustom = styleSelect.value === "__custom__";
            customStyleInput.hidden = !isCustom;
            customStyleInput.required = isCustom;
            if (!isCustom) customStyleInput.value = "";
        }

        function syncImageQualityVisibility() {
            var visible = mediaType === "IMAGE";
            if (imageAspectRatioField && imageAspectRatioSelect) {
                imageAspectRatioField.hidden = !visible;
                imageAspectRatioSelect.disabled = !visible;
            }
            if (imageQualityField && imageQualitySelect) {
                imageQualityField.hidden = !visible;
                imageQualitySelect.disabled = !visible;
            }
        }

        function renderStyleManager() {
            if (!styleList) return;
            if (!optionData.styles.length) {
                styleList.innerHTML =
                    '<div class="studio-batch-prompt-style-empty">'
                    + "还没有可管理的创作风格" + "</div>";
                return;
            }
            styleList.innerHTML = optionData.styles.map(function (item) {
                var deleteButton = item.id == null
                    ? ""
                    : '<button type="button" class="studio-link-button ' +
                      'studio-batch-prompt-style-delete" ' +
                      'data-batch-prompt-style-delete="' +
                      Studio.escapeHtml(item.id) + '" title="删除创作风格">' +
                      '<i class="layui-icon layui-icon-delete"></i>' +
                      "删除</button>";
                return '<div class="studio-batch-prompt-style-row">' +
                    '<span>' + Studio.escapeHtml(item.name || item.label || "") +
                    "</span>" + deleteButton + "</div>";
            }).join("");
        }

        function renderSelects() {
            var currentProduct = productSelect.value;
            var currentSkill = skillSelect.value;
            var currentStyle = styleSelect ? styleSelect.value : "";
            productSelect.innerHTML = '<option value="">不关联产品</option>' +
                optionData.products.map(function (item) {
                    var label = item.name || "未命名产品";
                    if (item.code) label += " · " + item.code;
                    if (item.dept_name) label += " · " + item.dept_name;
                    return '<option value="' + Studio.escapeHtml(item.id) +
                        '">' + Studio.escapeHtml(label) + "</option>";
                }).join("");
            skillSelect.innerHTML = '<option value="">不使用 Skill</option>' +
                optionData.skills.filter(function (item) {
                    var type = String(item.media_type || "BOTH").toUpperCase();
                    return type === "BOTH" || type === mediaType;
                }).map(function (item) {
                    var label = item.name || item.code || "未命名 Skill";
                    if (item.dept_name) label += " · " + item.dept_name;
                    return '<option value="' + Studio.escapeHtml(item.id) +
                        '">' + Studio.escapeHtml(label) + "</option>";
                }).join("");

            if (styleSelect) {
                styleSelect.innerHTML = '<option value="">跟随 Skill</option>' +
                    optionData.styles.map(function (item) {
                        return '<option value="' +
                            Studio.escapeHtml(item.value || item.name) + '">' +
                            Studio.escapeHtml(item.label || item.name) +
                            "</option>";
                    }).join("") +
                    '<option value="__custom__">自定义风格</option>';
            }

            if (optionData.products.some(function (item) {
                return String(item.id) === String(currentProduct);
            })) {
                productSelect.value = currentProduct;
            }
            if (optionData.skills.some(function (item) {
                return String(item.id) === String(currentSkill);
            })) {
                skillSelect.value = currentSkill;
            }
            if (styleSelect) {
                var canKeepStyle = currentStyle === "" ||
                    currentStyle === "__custom__" ||
                    optionData.styles.some(function (item) {
                        return String(item.value || item.name) ===
                            String(currentStyle);
                    });
                styleSelect.value = canKeepStyle ? currentStyle : "";
                syncCustomStyle();
            }
            renderStyleManager();
            if (window.layui) {
                layui.use("form", function () {
                    layui.form.render("select");
                });
            }
        }

        function loadOptions() {
            var requestNumber = ++optionsRequestNumber;
            var requestedMediaType = mediaType;
            return Studio.request(
                "/studio/api/options?media_type=" +
                encodeURIComponent(requestedMediaType)
            ).then(function (result) {
                if (
                    requestNumber !== optionsRequestNumber ||
                    requestedMediaType !== mediaType
                ) {
                    return;
                }
                optionData.products = result.data.products || [];
                optionData.skills = result.data.skills || [];
                optionData.styles = result.data.batch_prompt_styles || [];
                renderSelects();
            });
        }

        function loadStyles() {
            return Studio.request("/studio/api/batch-prompt-styles").then(
                function (result) {
                    optionData.styles = result.data.styles || [];
                    renderSelects();
                }
            );
        }

        function openComposer() {
            overlay.classList.add("is-open");
            overlay.setAttribute("aria-hidden", "false");
            document.body.classList.add("studio-composer-open");
            setMessage("");
            loadStyles().catch(function (error) {
                Studio.toast(error.message, "error");
            });
            window.setTimeout(function () {
                if (window.layui) {
                    layui.use("form", function () {
                        layui.form.render("select");
                    });
                }
                if (mediaTypeSelect) {
                    mediaTypeSelect.focus();
                } else {
                    productSelect.focus();
                }
            }, 0);
        }

        function closeComposer() {
            overlay.classList.remove("is-open");
            overlay.setAttribute("aria-hidden", "true");
            document.body.classList.remove("studio-composer-open");
        }

        openButtons.forEach(function (button) {
            button.addEventListener("click", openComposer);
        });
        overlay.querySelectorAll("[data-batch-prompt-close]").forEach(
            function (node) {
                node.addEventListener("click", closeComposer);
            }
        );
        overlay.querySelector("[data-batch-prompt-cancel]").addEventListener(
            "click",
            closeComposer
        );

        function statusLabel(status) {
            var labels = {
                PENDING: "处理中",
                SUCCEEDED: "已完成",
                FAILED: "失败"
            };
            return labels[status] || status || "未知";
        }

        function isLocalHistoryItem(item) {
            return Boolean(
                item &&
                String(item.id || "").indexOf("local-") === 0
            );
        }

        function historyItemStatusLabel(item) {
            if (item && item.ui_stage === "ANALYZING") {
                return "模型分析中";
            }
            return statusLabel(item && item.status);
        }

        function createOptimisticHistoryItem(payload) {
            return {
                id: "local-" + Date.now() + "-" +
                    Math.random().toString(36).slice(2, 8),
                name: "批量提示词",
                media_type: payload.media_type,
                product_id: payload.product_id || null,
                product_name: payload.product_name || "",
                skill_id: payload.skill_id || null,
                skill_name: payload.skill_name || "",
                creative_style: payload.creative_style || "",
                image_aspect_ratio: payload.image_aspect_ratio || "",
                image_quality: payload.image_quality || "",
                version_count: payload.version_count || 0,
                status: "PROCESSING",
                ui_stage: "ANALYZING",
                content: "",
                content_error: "",
                error_message: "",
                file_name: "",
                download_url: "",
                created_at: "刚刚"
            };
        }

        function markHistoryItemFailed(localId, errorMessage) {
            historyData = historyData.map(function (item) {
                if (String(item.id) !== String(localId)) return item;
                return Object.assign({}, item, {
                    status: "FAILED",
                    ui_stage: "",
                    content_error: errorMessage || "批量提示词生成失败",
                    error_message: errorMessage || "批量提示词生成失败"
                });
            });
            renderHistory();
        }

        function renderHistory() {
            if (!historyData.length) {
                history.innerHTML =
                    '<div class="studio-feed-empty">' +
                    "<strong>还没有批量创作提示词</strong>" +
                    "<span>点击上方按钮生成多个不同版本。</span>" +
                    "</div>";
            } else {
                history.innerHTML = historyData.map(function (item) {
                    var meta = [
                        item.media_type === "VIDEO" ? "视频" : "图片",
                        item.product_name || "未关联产品",
                        item.skill_name || "未使用 Skill",
                        item.creative_style || "",
                        item.image_aspect_ratio || "",
                        item.image_quality || "",
                        (item.version_count || 0) + " 个版本",
                        item.file_name || "",
                        item.created_at || ""
                    ].filter(function (value) {
                        return Boolean(value);
                    });
                    var isAnalyzing = item.ui_stage === "ANALYZING";
                    var isLocal = isLocalHistoryItem(item);
                    var displayName = String(
                        item.name || "批量提示词"
                    ).trim() || "批量提示词";
                    var content = item.content
                        ? '<pre class="studio-batch-prompt-content">' +
                          Studio.escapeHtml(item.content) + "</pre>"
                        : isAnalyzing
                            ? '<div class="studio-feed-processing ' +
                              'studio-batch-prompt-processing">' +
                              '<span class="studio-feed-spinner"></span>' +
                              "<div><strong>模型分析中</strong>" +
                              "<span>正在整理创意、产品信息与 Skill</span>" +
                              "</div></div>"
                            : '<div class="studio-batch-prompt-error">' +
                              Studio.escapeHtml(
                                  item.content_error || item.error_message ||
                                  (item.status === "FAILED"
                                      ? "批量提示词生成失败"
                                      : "暂时没有可读取的文本内容")
                              ) + "</div>";
                    var canEdit = item.status === "SUCCEEDED" &&
                        Boolean(item.content);
                    var download = item.download_url
                        ? '<a class="studio-link-button" target="_blank" ' +
                          'rel="noopener" download="' +
                          Studio.escapeHtml(item.file_name || "batch-prompt.txt") +
                          '" href="' + Studio.escapeHtml(item.download_url) +
                          '">下载</a>'
                        : "";
                    return (
                        '<article class="studio-batch-prompt-item" ' +
                        'data-batch-prompt-item="' +
                        Studio.escapeHtml(item.id) + '">' +
                        '<div class="studio-batch-prompt-item-header">' +
                        "<div>" +
                        '<div class="studio-batch-prompt-title" ' +
                        'data-batch-prompt-name-container>' +
                        '<strong data-batch-prompt-name-display>' +
                        (isLocal
                            ? "批量创作提示词"
                            : Studio.escapeHtml(displayName)) +
                        "</strong>" +
                        (!isLocal
                            ? '<span class="studio-batch-prompt-id">#' +
                              Studio.escapeHtml(item.id) + "</span>" +
                              '<button type="button" ' +
                              'class="studio-link-button ' +
                              'studio-batch-prompt-name-action" ' +
                              'data-batch-action="edit-name" ' +
                              'title="编辑批量提示词名称">' +
                              "编辑名称</button>"
                            : "") +
                        "</div>" +
                        '<div class="studio-batch-prompt-meta">' +
                        meta.map(Studio.escapeHtml).join(" · ") +
                        "</div>" +
                        "</div>" +
                        '<span class="studio-pill ' +
                        (item.status === "SUCCEEDED" ? "green" :
                            item.status === "FAILED" ? "red" : "gray") +
                        '">' + Studio.escapeHtml(
                            historyItemStatusLabel(item)
                        ) +
                        "</span>" +
                        "</div>" +
                        '<div data-batch-prompt-display>' + content + "</div>" +
                        (canEdit
                            ? '<div class="studio-batch-prompt-actions">' +
                              '<button type="button" ' +
                              'class="studio-link-button" ' +
                              'data-batch-action="edit">编辑</button>' +
                              download +
                              "</div>"
                            : download
                                ? '<div class="studio-batch-prompt-actions">' +
                                  download + "</div>"
                                : "") +
                        "</article>"
                    );
                }).join("");
            }
            summary.textContent = historyData.length
                ? "已加载 " + historyData.length + " 条记录"
                : "暂无批量提示词历史";
            pageInfo.textContent = historyData.length
                ? "已加载第 " + historyPage + " 页"
                : "";
            loadMoreButton.hidden = !historyHasMore;
            loadMoreButton.disabled = historyLoading;
            loadMoreButton.textContent = historyLoading
                ? "加载中..."
                : "加载更多历史";
        }

        function mergeHistory(items, existingItems) {
            var byId = {};
            (existingItems || historyData).concat(items || []).forEach(
                function (item) {
                    var key = String(item.id);
                    if (
                        !byId[key] ||
                        isLocalHistoryItem(byId[key]) ||
                        !isLocalHistoryItem(item)
                    ) {
                        byId[key] = item;
                    }
                }
            );
            return Object.keys(byId).map(function (key) {
                return byId[key];
            }).sort(function (left, right) {
                var leftLocal = isLocalHistoryItem(left);
                var rightLocal = isLocalHistoryItem(right);
                if (leftLocal !== rightLocal) {
                    return leftLocal ? -1 : 1;
                }
                return String(right.created_at || "").localeCompare(
                    String(left.created_at || "")
                ) || Number(right.id || 0) - Number(left.id || 0);
            });
        }

        function loadHistory(reset) {
            if (historyLoading) return Promise.resolve();
            if (!reset && !historyHasMore) return Promise.resolve();
            var page = reset ? 1 : historyPage + 1;
            var query = new URLSearchParams();
            query.set(
                "media_type",
                fixedMediaType === "ALL" ? "ALL" : mediaType
            );
            query.set("page", page);
            query.set("page_size", "20");
            historyLoading = true;
            renderHistory();
            return Studio.request(
                "/studio/api/batch-prompts?" + query.toString()
            ).then(function (result) {
                var localItems = historyData.filter(isLocalHistoryItem);
                historyData = reset
                    ? mergeHistory(result.data || [], localItems)
                    : mergeHistory(result.data);
                historyPage = page;
                historyHasMore = Boolean(
                    result.meta && result.meta.has_more
                );
                renderHistory();
            }).catch(function (error) {
                Studio.toast(error.message, "error");
            }).then(function () {
                historyLoading = false;
                renderHistory();
            });
        }

        function replaceHistoryItem(item, previousId) {
            var replaced = false;
            historyData = historyData.map(function (current) {
                if (
                    String(current.id) !== String(
                        previousId == null ? item.id : previousId
                    )
                ) {
                    return current;
                }
                replaced = true;
                return item;
            });
            if (!replaced) historyData = [item].concat(historyData);
            renderHistory();
        }

        function beginEdit(itemNode, item) {
            var display = itemNode.querySelector(
                "[data-batch-prompt-display]"
            );
            var actions = itemNode.querySelector(
                ".studio-batch-prompt-actions"
            );
            if (!display || !actions) return;
            display.innerHTML =
                '<textarea class="layui-textarea ' +
                'studio-batch-prompt-editor" ' +
                'data-batch-prompt-editor>' +
                Studio.escapeHtml(item.content || "") +
                "</textarea>";
            actions.innerHTML =
                '<button type="button" class="layui-btn ' +
                'studio-btn-primary" data-batch-action="save">保存</button>' +
                '<button type="button" class="layui-btn ' +
                'studio-btn-quiet" data-batch-action="cancel">取消</button>' +
                '<span class="studio-helper" ' +
                'data-batch-prompt-edit-message></span>';
            var editor = display.querySelector(
                "[data-batch-prompt-editor]"
            );
            if (editor) editor.focus();
        }

        function beginNameEdit(itemNode, item) {
            var title = itemNode.querySelector(
                "[data-batch-prompt-name-container]"
            );
            if (!title || isLocalHistoryItem(item)) return;
            var name = String(item.name || "批量提示词").trim() ||
                "批量提示词";
            title.innerHTML =
                '<div class="studio-batch-prompt-name-editor-row">' +
                '<input type="text" class="layui-input ' +
                'studio-batch-prompt-name-editor" ' +
                'data-batch-prompt-name-editor maxlength="160" ' +
                'value="' + Studio.escapeHtml(name) + '">' +
                '<span class="studio-batch-prompt-id">#' +
                Studio.escapeHtml(item.id) + "</span>" +
                "</div>" +
                '<div class="studio-batch-prompt-name-actions">' +
                '<button type="button" class="layui-btn ' +
                'studio-btn-primary" data-batch-action="save-name">' +
                "保存名称</button>" +
                '<button type="button" class="layui-btn ' +
                'studio-btn-quiet" data-batch-action="cancel-name">' +
                "取消</button>" +
                "</div>";
            var editor = title.querySelector(
                "[data-batch-prompt-name-editor]"
            );
            if (editor) editor.focus();
        }

        function saveName(itemNode, item) {
            var editor = itemNode.querySelector(
                "[data-batch-prompt-name-editor]"
            );
            var saveButton = itemNode.querySelector(
                '[data-batch-action="save-name"]'
            );
            if (!editor || !saveButton) return;
            var name = editor.value.trim();
            if (!name) {
                Studio.toast("批量提示词名称不能为空", "error");
                editor.focus();
                return;
            }
            saveButton.disabled = true;
            saveButton.textContent = "保存中...";
            Studio.request(
                "/studio/api/batch-prompts/" + encodeURIComponent(item.id),
                {
                    method: "PUT",
                    body: JSON.stringify({name: name})
                }
            ).then(function (result) {
                replaceHistoryItem(result.data);
                Studio.toast("批量提示词名称已保存");
            }).catch(function (error) {
                saveButton.disabled = false;
                saveButton.textContent = "保存名称";
                Studio.toast(error.message, "error");
            });
        }

        function saveEdit(itemNode, item) {
            var editor = itemNode.querySelector(
                "[data-batch-prompt-editor]"
            );
            var saveButton = itemNode.querySelector(
                '[data-batch-action="save"]'
            );
            if (!editor || !saveButton) return;
            var content = editor.value;
            if (!content.trim()) {
                Studio.toast("批量提示词内容不能为空", "error");
                editor.focus();
                return;
            }
            saveButton.disabled = true;
            saveButton.textContent = "保存中...";
            Studio.request(
                "/studio/api/batch-prompts/" + encodeURIComponent(item.id),
                {
                    method: "PUT",
                    body: JSON.stringify({content: content})
                }
            ).then(function (result) {
                replaceHistoryItem(result.data);
                Studio.toast("批量提示词已保存");
            }).catch(function (error) {
                saveButton.disabled = false;
                saveButton.textContent = "保存";
                Studio.toast(error.message, "error");
            });
        }

        rangeInput.addEventListener("input", function () {
            setCount(rangeInput.value, "range");
        });
        countInput.addEventListener("input", function () {
            setCount(countInput.value, "number");
        });

        if (mediaTypeSelect) {
            mediaTypeSelect.addEventListener("change", function () {
                mediaType = String(
                    mediaTypeSelect.value || "IMAGE"
                ).toUpperCase();
                if (mediaType !== "VIDEO") mediaType = "IMAGE";
                syncImageQualityVisibility();
                optionData.skills = [];
                renderSelects();
                loadOptions().catch(function (error) {
                    setMessage(error.message, true);
                    Studio.toast(error.message, "error");
                });
            });
        }

        if (styleSelect) {
            styleSelect.addEventListener("change", syncCustomStyle);
            syncCustomStyle();
        }

        if (styleManageButton && styleManager) {
            styleManageButton.addEventListener("click", function () {
                styleManager.hidden = !styleManager.hidden;
                if (!styleManager.hidden) {
                    loadStyles().catch(function (error) {
                        Studio.toast(error.message, "error");
                    });
                }
            });
        }

        if (styleAddButton && styleInput) {
            styleAddButton.addEventListener("click", function () {
                var name = styleInput.value.trim();
                if (!name) {
                    Studio.toast("请输入创作风格", "error");
                    styleInput.focus();
                    return;
                }
                styleAddButton.disabled = true;
                styleAddButton.classList.add("layui-btn-disabled");
                Studio.request("/studio/api/batch-prompt-styles", {
                    method: "POST",
                    body: JSON.stringify({name: name})
                }).then(function (result) {
                    optionData.styles = result.data.styles || [];
                    renderSelects();
                    if (styleSelect && result.data.style) {
                        styleSelect.value = result.data.style.value ||
                            result.data.style.name || "";
                        syncCustomStyle();
                    }
                    styleInput.value = "";
                    Studio.toast("创作风格已添加");
                }).catch(function (error) {
                    Studio.toast(error.message, "error");
                }).then(function () {
                    styleAddButton.disabled = false;
                    styleAddButton.classList.remove("layui-btn-disabled");
                });
            });
            styleInput.addEventListener("keydown", function (event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    styleAddButton.click();
                }
            });
        }

        if (styleList) {
            styleList.addEventListener("click", function (event) {
                var deleteButton = event.target.closest(
                    "[data-batch-prompt-style-delete]"
                );
                if (!deleteButton) return;
                var styleId = deleteButton.dataset.batchPromptStyleDelete;
                if (!styleId || !window.confirm("确定删除这个创作风格吗？")) {
                    return;
                }
                deleteButton.disabled = true;
                Studio.request(
                    "/studio/api/batch-prompt-styles/" +
                    encodeURIComponent(styleId),
                    {method: "DELETE"}
                ).then(function (result) {
                    optionData.styles = result.data.styles || [];
                    renderSelects();
                    Studio.toast("创作风格已删除");
                }).catch(function (error) {
                    deleteButton.disabled = false;
                    Studio.toast(error.message, "error");
                });
            });
        }

        history.addEventListener("click", function (event) {
            var actionNode = event.target.closest("[data-batch-action]");
            if (!actionNode) return;
            var itemNode = actionNode.closest("[data-batch-prompt-item]");
            if (!itemNode) return;
            var item = historyData.find(function (current) {
                return String(current.id) === String(
                    itemNode.dataset.batchPromptItem
                );
            });
            if (!item) return;
            var action = actionNode.dataset.batchAction;
            if (action === "edit") {
                beginEdit(itemNode, item);
            } else if (action === "edit-name") {
                beginNameEdit(itemNode, item);
            } else if (action === "save") {
                saveEdit(itemNode, item);
            } else if (action === "save-name") {
                saveName(itemNode, item);
            } else if (action === "cancel") {
                renderHistory();
            } else if (action === "cancel-name") {
                renderHistory();
            }
        });

        history.addEventListener("keydown", function (event) {
            var editor = event.target.closest(
                "[data-batch-prompt-name-editor]"
            );
            if (!editor) return;
            if (event.key === "Enter") {
                event.preventDefault();
                var title = editor.closest(
                    "[data-batch-prompt-name-container]"
                );
                var saveButton = title && title.querySelector(
                    '[data-batch-action="save-name"]'
                );
                if (saveButton) saveButton.click();
            } else if (event.key === "Escape") {
                event.preventDefault();
                renderHistory();
            }
        });

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            var count = Number(countInput.value);
            if (!Number.isInteger(count) || count < 0) {
                setMessage("生成版本数量只能为 0 或 1-50", true);
                countInput.focus();
                return;
            }
            if (count > 50) {
                setMessage("生成版本数量不能超过 50", true);
                countInput.focus();
                return;
            }
            var productId = productSelect.value || null;
            var skillId = skillSelect.value || null;
            var creativePrompt = creativeInput.value.trim();
            var selectedStyle = styleSelect ? styleSelect.value : "";
            var customStyle = customStyleInput
                ? customStyleInput.value.trim()
                : "";
            if (selectedStyle === "__custom__" && !customStyle) {
                setMessage("请输入自定义创作风格", true);
                if (customStyleInput) customStyleInput.focus();
                return;
            }
            if (mediaType === "IMAGE" && !productId) {
                setMessage(
                    "图片批量提示词必须先选择产品中心，才能保存产品参考图",
                    true
                );
                productSelect.focus();
                return;
            }
            if (!creativePrompt && !productId && !skillId) {
                setMessage(
                    "请至少填写批量创作要求，或选择产品/Skill",
                    true
                );
                return;
            }
            var effectiveCount = count === 0 ? 10 : count;
            var payload = {
                media_type: mediaType,
                product_id: productId,
                skill_id: skillId,
                creative_prompt: creativePrompt,
                creative_style: selectedStyle === "__custom__"
                    ? "__custom__"
                    : selectedStyle,
                custom_style: selectedStyle === "__custom__"
                    ? customStyle
                    : "",
                image_resolution: mediaType === "IMAGE" &&
                    imageQualitySelect
                    ? imageQualitySelect.value
                    : "",
                image_aspect_ratio: mediaType === "IMAGE" &&
                    imageAspectRatioSelect
                    ? imageAspectRatioSelect.value
                    : "",
                count: count
            };
            var optimisticItem = createOptimisticHistoryItem({
                media_type: mediaType,
                product_id: productId,
                product_name: productSelect.options[
                    productSelect.selectedIndex
                ]
                    ? productSelect.options[
                        productSelect.selectedIndex
                    ].textContent
                    : "",
                skill_id: skillId,
                skill_name: skillSelect.options[
                    skillSelect.selectedIndex
                ]
                    ? skillSelect.options[
                        skillSelect.selectedIndex
                    ].textContent
                    : "",
                creative_style: selectedStyle === "__custom__"
                    ? customStyle
                    : selectedStyle,
                image_aspect_ratio: payload.image_aspect_ratio,
                image_quality: payload.image_resolution,
                version_count: effectiveCount
            });
            submitButton.disabled = true;
            setMessage(
                "正在调用全局语言模型生成 " + effectiveCount + " 个版本..."
            );
            historyData = [optimisticItem].concat(historyData);
            renderHistory();
            closeComposer();
            creativeInput.value = "";
            if (styleSelect) styleSelect.value = "";
            if (customStyleInput) customStyleInput.value = "";
            if (imageAspectRatioSelect) {
                imageAspectRatioSelect.value = "2.44:1";
            }
            if (imageQualitySelect) imageQualitySelect.value = "2k";
            syncCustomStyle();
            syncImageQualityVisibility();
            setCount(0, "number");
            Studio.request("/studio/api/batch-prompts", {
                method: "POST",
                body: JSON.stringify(payload)
            }).then(function (result) {
                if (!result.data) {
                    throw new Error("批量提示词接口没有返回有效结果");
                }
                replaceHistoryItem(result.data, optimisticItem.id);
                historyPage = 1;
                Studio.toast("批量创作提示词已生成");
            }).catch(function (error) {
                markHistoryItemFailed(
                    optimisticItem.id,
                    error.message
                );
                setMessage(error.message, true);
                Studio.toast(error.message, "error");
            }).then(function () {
                submitButton.disabled = false;
            });
        });

        refreshButton.addEventListener("click", function () {
            loadHistory(true);
        });
        loadMoreButton.addEventListener("click", function () {
            loadHistory(false);
        });
        document.addEventListener("keydown", function (event) {
            if (
                event.key === "Escape" &&
                overlay.classList.contains("is-open")
            ) {
                closeComposer();
            }
        });

        setCount(0, "number");
        if (imageAspectRatioSelect) {
            imageAspectRatioSelect.value = "2.44:1";
        }
        if (imageQualitySelect) imageQualitySelect.value = "2k";
        syncImageQualityVisibility();
        loadOptions().catch(function (error) {
            summary.textContent = "选项加载失败";
            Studio.toast(error.message, "error");
        });
        loadHistory(true);
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-batch-prompt-panel]").forEach(
            initBatchPromptPanel
        );
    });
})();
