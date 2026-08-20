(function () {
    function request(url, options) {
        options = options || {};
        options.headers = Object.assign({
            "Content-Type": "application/json"
        }, options.headers || {});
        return fetch(url, options).then(function (response) {
            return response.json().catch(function () {
                return {success: false, msg: "服务器返回了无效响应"};
            }).then(function (payload) {
                if (!response.ok || payload.success === false) {
                    throw new Error(payload.msg || "请求失败");
                }
                return payload;
            });
        });
    }

    function uploadAssets(files, assetType, purpose) {
        files = Array.from(files || []);
        if (!files.length) return Promise.resolve([]);
        return Promise.all(files.map(function (file) {
            var query = new URLSearchParams();
            if (assetType) query.set("asset_type", assetType);
            if (purpose) query.set("purpose", purpose);
            var body = new FormData();
            body.append("file", file);
            return fetch("/studio/api/assets/upload?" + query.toString(), {
                method: "POST",
                body: body
            }).then(function (response) {
                return response.json().catch(function () {
                    return {success: false, msg: "服务器返回了无效响应"};
                }).then(function (payload) {
                    if (!response.ok || payload.success === false) {
                        throw new Error(payload.msg || "文件上传失败");
                    }
                    return payload.data;
                });
            });
        }));
    }

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function statusClass(status) {
        var map = {
            SUCCEEDED: "green",
            PROCESSING: "",
            SUBMITTED: "",
            PENDING: "gray",
            FAILED: "red",
            CANCELLED: "orange"
        };
        return map[status] || "gray";
    }

    function statusText(status) {
        var map = {
            SUCCEEDED: "已完成",
            PROCESSING: "处理中",
            SUBMITTED: "已提交",
            PENDING: "待提交",
            FAILED: "失败",
            CANCELLED: "已取消"
        };
        return map[status] || status || "未知";
    }

    function toast(message, type) {
        if (window.layer) {
            layer.msg(message, {icon: type === "error" ? 2 : 1, time: 2200});
        } else {
            window.alert(message);
        }
    }

    function formatBalance(balance) {
        balance = balance || {};
        if (balance.available === false) return "未识别余额";
        if (balance.unlimited_quota || Number(balance.remain_balance) === -1) {
            return "无限额度";
        }
        var parts = [];
        if (balance.remain_balance !== null && balance.remain_balance !== undefined) {
            parts.push("余额 " + balance.remain_balance);
        }
        if (balance.used_balance !== null && balance.used_balance !== undefined) {
            parts.push("已用 " + balance.used_balance);
        }
        if (balance.remain_credits !== null && balance.remain_credits !== undefined) {
            parts.push("积分 " + balance.remain_credits);
        }
        return parts.length ? parts.join(" · ") : "已连接";
    }

    function initLayer() {
        if (window.layui) {
            layui.use(["layer", "form"], function () {
                window.layer = layui.layer;
                window.studioForm = layui.form;
            });
        }
    }

    function valueForInput(value, valueType) {
        if (value == null) return "";
        if (valueType === "json" && typeof value !== "string") return JSON.stringify(value);
        return String(value);
    }

    function optionEntries(options) {
        if (typeof options === "string") {
            try {
                options = JSON.parse(options);
            } catch (error) {
                options = options.split(/[,\n]/);
            }
        }
        if (!Array.isArray(options)) return [];
        return options.map(function (option) {
            if (option && typeof option === "object") {
                var value = option.value;
                if (value == null) value = option.key;
                if (value == null) value = option.id;
                return {
                    value: value == null ? "" : String(value),
                    label: option.label || option.name || value
                };
            }
            return {
                value: option == null ? "" : String(option),
                label: option == null ? "" : String(option)
            };
        }).filter(function (option) {
            return option.value !== "";
        });
    }

    function parameterOptions(parameter) {
        return optionEntries(parameter && parameter.options);
    }

    function renderConstrainedControl(id, parameter, fallbackValue) {
        var current = document.getElementById(id);
        if (!current) return null;
        if (current.tagName.toLowerCase() === "select") {
            var rendered = current.nextElementSibling;
            if (rendered && rendered.classList.contains("layui-form-select")) {
                rendered.remove();
            }
        }
        var options = parameterOptions(parameter);
        var value = (parameter && parameter.value !== "" && parameter.value != null)
            ? parameter.value
            : (current.value || fallbackValue || "");
        var name = current.name || id;
        var next = current;

        if (options.length) {
            next = document.createElement("select");
            next.id = id;
            next.name = name;
            next.innerHTML = options.map(function (option) {
                return '<option value="' + escapeHtml(option.value) + '"' +
                    (String(option.value) === String(value) ? " selected" : "") + ">" +
                    escapeHtml(option.label) + "</option>";
            }).join("");
            if (!options.some(function (option) {
                return String(option.value) === String(value);
            })) {
                next.value = options[0].value;
            }
            current.parentNode.replaceChild(next, current);
        } else if (current.tagName.toLowerCase() === "select") {
            next = document.createElement("input");
            next.type = "text";
            next.id = id;
            next.name = name;
            next.className = "layui-input";
            next.value = value;
            current.parentNode.replaceChild(next, current);
        } else {
            current.value = value;
        }

        if (window.layui && next.tagName.toLowerCase() === "select") {
            layui.use("form", function () {
                layui.form.render("select");
            });
        }
        return next;
    }

    function fitLayerArea(area) {
        area = area || ["820px", "680px"];
        var requestedWidth = parseInt(area[0], 10) || 820;
        var requestedHeight = parseInt(area[1], 10) || 680;
        var viewportWidth = Math.max(
            document.documentElement.clientWidth || window.innerWidth || 320,
            320
        );
        var viewportHeight = Math.max(
            document.documentElement.clientHeight || window.innerHeight || 260,
            260
        );
        return [
            Math.min(requestedWidth, Math.max(280, viewportWidth - 24)) + "px",
            Math.min(requestedHeight, Math.max(240, viewportHeight - 24)) + "px"
        ];
    }

    function renderDynamicFields(container, schema, reservedFields) {
        reservedFields = reservedFields || [];
        schema = (schema || []).filter(function (item) {
            return item.enabled !== false &&
                reservedFields.indexOf(item.field) === -1 &&
                reservedFields.indexOf(item.runtime_key) === -1;
        });
        if (!schema.length) {
            container.innerHTML = '<div class="studio-empty studio-empty-compact">当前模型没有额外可编辑字段</div>';
            return;
        }
        container.innerHTML = schema.map(function (item) {
            var type = String(item.value_type || "string").toLowerCase();
            var label = item.label || item.field;
            var hint = item.hint ? '<div class="studio-field-hint">' + escapeHtml(item.hint) + '</div>' : "";
            var input;
            if (type === "boolean" || type === "bool") {
                var checked = String(item.value).toLowerCase() === "true" || item.value === true;
                input = '<label class="studio-checkbox"><input type="checkbox" data-dynamic-field="1" data-field="' +
                    escapeHtml(item.field) + '" data-value-type="boolean" ' + (checked ? "checked" : "") + '>启用</label>';
            } else if (type === "json" || type === "array" || type === "object") {
                input = '<textarea class="layui-textarea studio-dynamic-input" rows="2" data-dynamic-field="1" data-field="' +
                    escapeHtml(item.field) + '" data-value-type="json" placeholder="JSON">' +
                    escapeHtml(valueForInput(item.value, "json")) + '</textarea>';
            } else if (parameterOptions(item).length) {
                input = '<select class="studio-dynamic-input" data-dynamic-field="1" data-field="' +
                    escapeHtml(item.field) + '" data-value-type="' + escapeHtml(type) + '">' +
                    parameterOptions(item).map(function (option) {
                        return '<option value="' + escapeHtml(option.value) + '"' +
                            (String(option.value) === String(valueForInput(item.value, type))
                                ? " selected" : "") + ">" +
                            escapeHtml(option.label) + "</option>";
                    }).join("") + '</select>';
            } else {
                input = '<input class="layui-input studio-dynamic-input" data-dynamic-field="1" data-field="' +
                    escapeHtml(item.field) + '" data-value-type="' + escapeHtml(type) + '" value="' +
                    escapeHtml(valueForInput(item.value, type)) + '">';
            }
            return '<div class="studio-dynamic-field"><label class="studio-field-label">' +
                escapeHtml(label) + '<span class="studio-field-code">' + escapeHtml(item.field) + '</span></label>' +
                input + hint + '</div>';
        }).join("");
    }

    function collectDynamicFields(container) {
        var output = {};
        container.querySelectorAll("[data-dynamic-field]").forEach(function (input) {
            var field = input.dataset.field;
            var value;
            if (input.type === "checkbox") {
                value = input.checked;
            } else {
                value = input.value;
                if (input.dataset.valueType === "json" && value.trim()) {
                    try {
                        value = JSON.parse(value);
                    } catch (error) {
                        throw new Error("字段 " + field + " 必须填写合法 JSON");
                    }
                }
            }
            if (value !== "" && value !== null && !(Array.isArray(value) && !value.length)) {
                output[field] = value;
            }
        });
        return output;
    }

    window.Studio = {
        request: request,
        uploadAssets: uploadAssets,
        escapeHtml: escapeHtml,
        statusClass: statusClass,
        statusText: statusText,
        toast: toast,
        formatBalance: formatBalance,
        initLayer: initLayer,
        fitLayerArea: fitLayerArea,
        parameterOptions: parameterOptions,
        renderConstrainedControl: renderConstrainedControl,
        renderDynamicFields: renderDynamicFields,
        collectDynamicFields: collectDynamicFields
    };
    initLayer();
})();
